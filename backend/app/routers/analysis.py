"""Analysis router — Dialog analysis and results endpoints.

Endpoints:
  POST /analyze          — Run dictionary matching + optional LLM analysis
  GET  /results/{id}     — Retrieve stored analysis results
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from app.models import AnalysisRequest, AnalysisResponse, LLMResult, SearchResult
from app.services.llm import analyze_dialogue, get_provider
from app.services.search import run_hierarchical_search
from app.utils.session import session_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/analyze", response_model=AnalysisResponse, summary="Run dictionary analysis")
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    """Run phrase-matching analysis on a previously uploaded dialogue.

    Optionally includes LLM-based summarization and dialogue restructuring.

    Uses hierarchical dictionary matching via services.search.
    """
    # ── Validate session ──────────────────────────────────────────
    session = session_store.get(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{request.session_id}' not found. Upload a dialogue first.",
        )

    if session.dialog is None:
        raise HTTPException(
            status_code=400,
            detail="No dialogue uploaded for this session. Upload an RTF file first.",
        )

    if not session.dictionaries:
        raise HTTPException(
            status_code=400,
            detail="No dictionaries uploaded for this session. Upload an XML dictionary first.",
        )

    analysis_id = uuid.uuid4().hex[:12]

    # ── Run dictionary search ─────────────────────────────────────
    dict_list = list(session.dictionaries.values())

    # Filter by requested dictionary names
    selected_names = request.dictionary_ids if request.dictionary_ids else None

    try:
        search_result = await run_hierarchical_search(
            dialog=session.dialog,
            dictionaries=dict_list,
            selected_dict_names=selected_names,
        )
    except Exception as exc:
        logger.error("Search failed for session %s: %s", request.session_id, exc)
        search_result = SearchResult(segments=[], total_matches=0, matches=[], matches_by_level={})

    # ── Run LLM analysis (if requested) ──────────────────────────
    llm_result: LLMResult | None = None
    warning: str | None = None

    if request.include_summary or request.include_restructured:
        try:
            # Build dialogue text for LLM
            dialogue_text = _build_dialogue_text(session.dialog.turns)
            llm_result = await analyze_dialogue(
                dialogue_text=dialogue_text,
                provider_id=request.llm_provider,
                model=request.llm_model,
            )
        except ValueError as exc:
            warning = f"LLM provider error: {exc}"
            logger.warning("LLM analysis failed for session %s: %s", request.session_id, exc)
        except ConnectionError as exc:
            warning = f"LLM service unavailable: {exc}"
            logger.warning("LLM connection failed for session %s: %s", request.session_id, exc)
        except Exception as exc:
            warning = f"LLM analysis error: {exc}"
            logger.error("Unexpected LLM error for session %s: %s", request.session_id, exc)

    # ── Determine status ──────────────────────────────────────────
    if llm_result is not None:
        status = "completed"
    elif warning is not None:
        status = "partial"
    else:
        status = "completed"

    # ── Build and store response ──────────────────────────────────
    response = AnalysisResponse(
        analysis_id=analysis_id,
        session_id=request.session_id,
        status=status,
        search_result=search_result,
        llm_result=llm_result,
        warning=warning,
    )

    session_store.add_analysis(request.session_id, response)

    return response


@router.get(
    "/results/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Get analysis results",
)
async def get_results(analysis_id: str) -> AnalysisResponse:
    """Retrieve stored analysis results by analysis ID."""
    result = session_store.get_analysis(analysis_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Analysis '{analysis_id}' not found.",
        )
    return result


def _build_dialogue_text(turns) -> str:
    """Build a formatted dialogue text string for LLM consumption.

    Args:
        turns: List of DialogueTurn objects.

    Returns:
        Formatted dialogue string with speaker labels.
    """
    lines: list[str] = []
    for turn in turns:
        lines.append(f"{turn.speaker}: {turn.text}")
    return "\n".join(lines)

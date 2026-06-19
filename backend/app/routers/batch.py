"""Batch analysis router — Sequential processing of multiple RTF files.

Endpoints:
  POST /batch                  — Submit batch analysis (multiple RTF files)
  GET  /batch/{batch_id}/status — Poll batch processing progress
  GET  /batch/{batch_id}/results — Get batch results with analysis IDs

Processing model:
  - Files are processed sequentially (one by one) in a background task.
  - Progress is tracked per file: pending → processing → completed | failed.
  - If some files succeed and some fail, batch status = "partial".
  - Max 10 files per batch (memory protection for in-memory sessions).
  - Each completed file's analysis is stored in the session and can be
    retrieved via the existing GET /api/analysis/results/{analysis_id} endpoint.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.config import settings
from app.models import AnalysisResponse, BatchAnalysisResponse, BatchItemStatus, LLMResult, SearchResult
from app.services.llm import analyze_dialogue
from app.services.rtf_parser import parse_rtf_bytes
from app.services.search import run_hierarchical_search
from app.utils.session import batch_store, session_store

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum number of files in a single batch request
MAX_BATCH_FILES = 10


# ═══════════════════════════════════════════════════════════
# POST /batch — Submit batch analysis
# ═══════════════════════════════════════════════════════════


@router.post(
    "/batch",
    response_model=BatchAnalysisResponse,
    summary="Submit batch analysis for multiple RTF files",
)
async def submit_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="RTF files to analyze (1-10)"),
    session_id: str = Form(..., description="Session with uploaded dictionaries"),
    llm_provider: str = Form("ollama", description="LLM provider"),
    llm_model: Optional[str] = Form(None, description="Optional LLM model override"),
    include_summary: bool = Form(False, description="Include LLM summary"),
    include_restructured: bool = Form(False, description="Include restructured dialogue"),
    dictionary_ids: Optional[str] = Form(
        None, description="Comma-separated dictionary names (empty = all)"
    ),
) -> BatchAnalysisResponse:
    """Submit multiple RTF files for sequential batch analysis.

    Accepts 1-10 RTF files along with a session_id that has dictionaries
    already uploaded. Files are processed one by one in the background.
    Use GET /batch/{batch_id}/status to poll progress.

    Returns immediately with batch_id and initial status "processing".
    """
    # ── Validate file count ──────────────────────────────────────
    if len(files) < 1:
        raise HTTPException(
            status_code=400,
            detail="Batch must contain at least 1 file.",
        )
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Batch must contain at most {MAX_BATCH_FILES} files. Got {len(files)}.",
        )

    # ── Validate file extensions ────────────────────────────────
    for f in files:
        filename = f.filename or "unknown"
        if not filename.lower().endswith(".rtf"):
            raise HTTPException(
                status_code=400,
                detail=f"All files must be .rtf format. Got: '{filename}'",
            )

    # ── Validate session exists ─────────────────────────────────
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found. Create a session and upload dictionaries first.",
        )

    # ── Validate session has dictionaries ────────────────────────
    if not session.dictionaries:
        raise HTTPException(
            status_code=400,
            detail="No dictionaries uploaded for this session. Upload XML dictionaries first.",
        )

    # ── Read all file contents upfront ──────────────────────────
    # UploadFile objects may be closed after the response is sent,
    # so we must read all content before starting the background task.
    file_data: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        filename = f.filename or "unknown.rtf"

        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Empty file uploaded: '{filename}'",
            )
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: '{filename}' "
                       f"(max {settings.max_upload_size_mb}MB, "
                       f"got {len(content) / (1024 * 1024):.1f}MB)",
            )

        file_data.append((filename, content))

    # ── Parse dictionary_ids (comma-separated) ──────────────────
    dict_ids: list[str] = []
    if dictionary_ids:
        dict_ids = [d.strip() for d in dictionary_ids.split(",") if d.strip()]

    # ── Create batch ────────────────────────────────────────────
    batch_id = uuid.uuid4().hex[:12]
    items = [BatchItemStatus(filename=name) for name, _ in file_data]

    batch = BatchAnalysisResponse(
        batch_id=batch_id,
        session_id=session_id,
        total_files=len(file_data),
        status="processing",
        items=items,
    )

    batch_store.create(batch)

    # ── Start background sequential processing ──────────────────
    background_tasks.add_task(
        _process_batch_background,
        batch_id=batch_id,
        file_data=file_data,
        session_id=session_id,
        llm_provider=llm_provider,
        llm_model=llm_model,
        include_summary=include_summary,
        include_restructured=include_restructured,
        dictionary_ids=dict_ids,
    )

    return batch


# ═══════════════════════════════════════════════════════════
# GET /batch/{batch_id}/status — Poll batch progress
# ═══════════════════════════════════════════════════════════


@router.get(
    "/batch/{batch_id}/status",
    response_model=BatchAnalysisResponse,
    summary="Poll batch processing progress",
)
async def get_batch_status(batch_id: str) -> BatchAnalysisResponse:
    """Get the current processing status of a batch.

    Returns per-file status (pending/processing/completed/failed)
    and overall batch status (processing/completed/partial/failed).
    """
    batch = batch_store.get(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch '{batch_id}' not found.",
        )
    return batch


# ═══════════════════════════════════════════════════════════
# GET /batch/{batch_id}/results — Get batch results
# ═══════════════════════════════════════════════════════════


@router.get(
    "/batch/{batch_id}/results",
    response_model=BatchAnalysisResponse,
    summary="Get batch analysis results",
)
async def get_batch_results(batch_id: str) -> BatchAnalysisResponse:
    """Get batch results with analysis IDs for completed items.

    For each completed item, the analysis_id can be used with
    GET /api/analysis/results/{analysis_id} to retrieve full results.
    Failed items include an error message instead of an analysis_id.
    """
    batch = batch_store.get(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch '{batch_id}' not found.",
        )

    # Only return results if processing has started or completed
    if batch.status == "pending":
        raise HTTPException(
            status_code=400,
            detail="Batch has not started processing yet.",
        )

    return batch


# ═══════════════════════════════════════════════════════════
# Background processing
# ═══════════════════════════════════════════════════════════


async def _process_batch_background(
    batch_id: str,
    file_data: list[tuple[str, bytes]],
    session_id: str,
    llm_provider: str,
    llm_model: Optional[str],
    include_summary: bool,
    include_restructured: bool,
    dictionary_ids: list[str],
) -> None:
    """Process batch files sequentially in the background.

    For each file:
      1. Parse RTF → ParsedDialog
      2. Run hierarchical search → SearchResult
      3. Run LLM analysis (if requested) → LLMResult
      4. Store AnalysisResponse in session
      5. Update BatchItemStatus

    On error: mark item as "failed" and continue with next file.
    After all files: determine batch status (completed/partial/failed).
    """
    batch = batch_store.get(batch_id)
    if batch is None:
        logger.error("Batch %s not found at start of background processing", batch_id)
        return

    session = session_store.get(session_id)
    if session is None:
        batch.status = "failed"
        batch.error = "Session expired during processing"
        batch_store.update(batch)
        logger.error("Session %s expired during batch %s processing", session_id, batch_id)
        return

    dict_list = list(session.dictionaries.values())
    selected_names = dictionary_ids if dictionary_ids else None

    completed = 0
    failed = 0

    for i, (filename, content) in enumerate(file_data):
        # ── Mark item as processing ──────────────────────────────
        batch = batch_store.get(batch_id)
        if batch is None:
            logger.error("Batch %s disappeared during processing", batch_id)
            return

        batch.items[i].status = "processing"
        batch_store.update(batch)

        try:
            # ── Parse RTF ────────────────────────────────────────
            parsed = await parse_rtf_bytes(content, filename)

            if not parsed.turns:
                raise ValueError(
                    "No dialogue could be extracted from the RTF file. "
                    "The file may not contain valid RTF dialogue content."
                )

            # ── Run hierarchical search ──────────────────────────
            try:
                search_result = await run_hierarchical_search(
                    dialog=parsed,
                    dictionaries=dict_list,
                    selected_dict_names=selected_names,
                )
            except Exception as exc:
                logger.error("Search failed for '%s' in batch %s: %s", filename, batch_id, exc)
                search_result = SearchResult(
                    segments=[], total_matches=0, matches=[], matches_by_level={}
                )

            # ── Run LLM analysis (if requested) ──────────────────
            llm_result: LLMResult | None = None
            warning: str | None = None

            if include_summary or include_restructured:
                try:
                    dialogue_text = _build_dialogue_text(parsed.turns)
                    llm_result = await analyze_dialogue(
                        dialogue_text=dialogue_text,
                        provider_id=llm_provider,
                        model=llm_model,
                    )
                except ValueError as exc:
                    warning = f"LLM provider error: {exc}"
                    logger.warning(
                        "LLM analysis failed for '%s' in batch %s: %s",
                        filename, batch_id, exc,
                    )
                except ConnectionError as exc:
                    warning = f"LLM service unavailable: {exc}"
                    logger.warning(
                        "LLM connection failed for '%s' in batch %s: %s",
                        filename, batch_id, exc,
                    )
                except Exception as exc:
                    warning = f"LLM analysis error: {exc}"
                    logger.error(
                        "Unexpected LLM error for '%s' in batch %s: %s",
                        filename, batch_id, exc,
                    )

            # ── Determine item status ────────────────────────────
            item_status = "completed"
            if llm_result is None and warning is not None:
                item_status = "partial"

            # ── Create and store analysis ─────────────────────────
            analysis_id = uuid.uuid4().hex[:12]

            analysis = AnalysisResponse(
                analysis_id=analysis_id,
                session_id=session_id,
                status=item_status,
                search_result=search_result,
                llm_result=llm_result,
                warning=warning,
            )

            session_store.add_analysis(session_id, analysis)

            # ── Update batch item ─────────────────────────────────
            batch.items[i].status = "completed"
            batch.items[i].analysis_id = analysis_id
            batch.items[i].total_matches = search_result.total_matches
            batch.items[i].matches_by_level = dict(search_result.matches_by_level)
            completed += 1

        except Exception as exc:
            logger.error(
                "Failed to process file '%s' in batch %s: %s",
                filename, batch_id, exc,
            )
            batch.items[i].status = "failed"
            batch.items[i].error = str(exc)[:500]  # Truncate very long errors
            failed += 1

        # ── Update counts ─────────────────────────────────────────
        batch.completed_count = completed
        batch.failed_count = failed
        batch_store.update(batch)

    # ── Determine final batch status ────────────────────────────
    batch = batch_store.get(batch_id)
    if batch is None:
        return

    if completed == batch.total_files:
        batch.status = "completed"
    elif failed == batch.total_files:
        batch.status = "failed"
    else:
        batch.status = "partial"

    batch_store.update(batch)
    logger.info(
        "Batch %s completed: %d/%d files processed, %d failed",
        batch_id, completed, batch.total_files, failed,
    )


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

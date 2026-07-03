"""Analysis router — Dialog analysis and results endpoints.

Endpoints:
  POST /analyze          — Run dictionary matching + optional LLM analysis
  GET  /results/{id}     — Retrieve stored analysis results
  POST /sentiment        — Per-utterance sentiment analysis (IP-3.2)
  POST /conflict         — Conflict / aggression detection (IP-3.3)
  POST /profanity        — Profanity / offensive language detection (IP-3.4)
  POST /topic            — Topic detection (IP-3.5)
  POST /full             — Run all analyses via LLMOrchestrator (IP-3.6)
  POST /quality-score    — Quality scoring across 12 categories (IP-4.1)
  POST /validate         — Dialogue quality validation (ID-12)
  POST /resolution-sentiment — Auto-resolution + sentiment trajectory (ID-3)
  POST /errors           — Error classification (IP-5.2)
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import (
    AnalysisAnnotation,
    AnalysisRequest,
    AnalysisResponse,
    ConflictAnalysisResult,
    DialogueValidationResult,
    DomainType,
    ErrorClassificationResult,
    LLMResult,
    ProfanityAnalysisResult,
    QualityScoreResult,
    ResolutionSentimentResult,
    SearchResult,
    SentimentAnalysisResult,
    TopicAnalysisResult,
)
from app.services.llm import (
    LLMOrchestrator,
    analyze_conflict,
    analyze_dialogue,
    analyze_dialogue_validation,
    analyze_errors,
    analyze_profanity,
    analyze_quality,
    analyze_resolution_sentiment,
    analyze_sentiment,
    analyze_topic,
    get_provider,
)
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
    if selected_names:
        # Filter dict_list to only include requested dictionaries
        dict_list = [d for d in dict_list if d.name in selected_names]

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
            # Check if LLM actually produced a result (graceful degradation)
            if llm_result.provider == "none":
                warning = "LLM unavailable: all providers failed"
                logger.warning(
                    "LLM analysis degraded for session %s: all providers failed",
                    request.session_id,
                )
        except Exception as exc:
            warning = f"LLM analysis error: {exc}"
            logger.error("Unexpected LLM error for session %s: %s", request.session_id, exc)

    # ── Determine status ──────────────────────────────────────────
    if llm_result is not None and llm_result.provider != "none":
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


# ═══════════════════════════════════════════════════════════
# Shared request model for new analysis endpoints
# ═══════════════════════════════════════════════════════════


class AnalysisEndpointRequest(BaseModel):
    """Common request body for the 4 new analysis endpoints."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    provider_id: str = Field(
        "beeline",
        description="LLM provider: ollama, yandexgpt, gigachat, beeline",
    )


# ═══════════════════════════════════════════════════════════
# IP-3.2: Sentiment Analysis
# ═══════════════════════════════════════════════════════════


@router.post(
    "/sentiment",
    response_model=SentimentAnalysisResult,
    summary="Sentiment analysis (per-utterance)",
)
async def sentiment_analysis(
    request: AnalysisEndpointRequest,
) -> SentimentAnalysisResult:
    """Analyze per-utterance sentiment of a previously uploaded dialogue.

    Returns per-utterance sentiment labels, overall sentiment, and
    sentiment trajectory over the dialogue.
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)
    return await analyze_sentiment(
        dialogue_text=dialogue_text,
        provider_id=request.provider_id,
    )


# ═══════════════════════════════════════════════════════════
# IP-3.3: Conflict Detection
# ═══════════════════════════════════════════════════════════


@router.post(
    "/conflict",
    response_model=ConflictAnalysisResult,
    summary="Conflict / aggression detection",
)
async def conflict_analysis(
    request: AnalysisEndpointRequest,
) -> ConflictAnalysisResult:
    """Detect conflict, aggression, and escalation in a previously uploaded dialogue.

    Returns conflict level, escalation points, and de-escalation
    attempt count.
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)
    return await analyze_conflict(
        dialogue_text=dialogue_text,
        provider_id=request.provider_id,
    )


# ═══════════════════════════════════════════════════════════
# IP-3.4: Profanity Detection
# ═══════════════════════════════════════════════════════════


@router.post(
    "/profanity",
    response_model=ProfanityAnalysisResult,
    summary="Profanity / offensive language detection",
)
async def profanity_analysis(
    request: AnalysisEndpointRequest,
) -> ProfanityAnalysisResult:
    """Detect profanity and offensive language in a previously uploaded dialogue.

    Returns per-instance profanity detections with category, severity,
    and context, plus a total count.
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)
    return await analyze_profanity(
        dialogue_text=dialogue_text,
        provider_id=request.provider_id,
    )


# ═══════════════════════════════════════════════════════════
# IP-3.5: Topic Detection
# ═══════════════════════════════════════════════════════════


@router.post(
    "/topic",
    response_model=TopicAnalysisResult,
    summary="Topic detection",
)
async def topic_analysis(
    request: AnalysisEndpointRequest,
) -> TopicAnalysisResult:
    """Detect topics discussed in a previously uploaded dialogue.

    Returns detected topics with confidence scores, key phrases,
    and the primary topic.
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)
    return await analyze_topic(
        dialogue_text=dialogue_text,
        provider_id=request.provider_id,
    )


# ═══════════════════════════════════════════════════════════
# IP-4.1: Quality Scoring (12 categories)
# ═══════════════════════════════════════════════════════════


class QualityScoreRequest(BaseModel):
    """Request body for the quality-score endpoint."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    provider_id: str = Field(
        "beeline",
        description="LLM provider: ollama, yandexgpt, gigachat, beeline",
    )


@router.post(
    "/quality-score",
    response_model=QualityScoreResult,
    summary="Quality scoring across 12 categories",
)
async def quality_score_analysis(
    request: QualityScoreRequest,
) -> QualityScoreResult:
    """Analyse dialogue quality across 12 categories.

    Returns per-category scores (high/medium/low), overall score and
    level, strengths, weaknesses, and improvement recommendations.

    On LLM failure, returns all categories at *medium* with empty
    justifications (graceful degradation).
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)
    return await analyze_quality(
        dialogue_text=dialogue_text,
        session_id=request.session_id,
        provider_id=request.provider_id,
    )


# ═══════════════════════════════════════════════════════════
# ID-12: Dialogue Validation
# ═══════════════════════════════════════════════════════════


class DialogueValidationRequest(BaseModel):
    """Request body for the dialogue validation endpoint."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    provider_id: str = Field(
        "beeline",
        description="LLM provider: ollama, yandexgpt, gigachat, beeline",
    )


@router.post(
    "/validate",
    response_model=DialogueValidationResult,
    summary="Dialogue quality validation",
)
async def dialogue_validation(
    request: DialogueValidationRequest,
) -> DialogueValidationResult:
    """Validate whether a previously uploaded dialogue is meaningful.

    Checks if the uploaded text constitutes a real client-operator
    dialogue (vs. noise, artifacts, or non-dialogue text).

    Returns is_valid_dialogue flag with confidence, reason, and
    detected language. On LLM failure, returns is_valid_dialogue=False
    with an explanatory reason (graceful degradation).
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)
    return await analyze_dialogue_validation(
        dialogue_text=dialogue_text,
        provider_id=request.provider_id,
    )


# ═══════════════════════════════════════════════════════════
# Shared helpers for new endpoints
# ═══════════════════════════════════════════════════════════


def _validate_session(session_id: str):
    """Validate that a session exists and has an uploaded dialogue.

    Args:
        session_id: Session identifier.

    Returns:
        Session object.

    Raises:
        HTTPException: 404 if session not found, 400 if no dialogue.
    """
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found. Upload a dialogue first.",
        )
    if session.dialog is None:
        raise HTTPException(
            status_code=400,
            detail="No dialogue uploaded for this session. Upload an RTF file first.",
        )
    return session


# ═══════════════════════════════════════════════════════════
# IP-3.6: Full Analysis (LLMOrchestrator)
# ═══════════════════════════════════════════════════════════


class FullAnalysisRequest(BaseModel):
    """Request body for the full analysis endpoint."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    provider_id: str = Field(
        "beeline",
        description="LLM provider: ollama, yandexgpt, gigachat, beeline",
    )
    include_summary: bool = Field(
        True,
        description="Whether to also run dialogue summary analysis",
    )
    domain: str = Field(
        "general",
        description="Domain type for domain-specific analysis: general, insurance, banking, healthcare, telecom",
    )


@router.post(
    "/full",
    response_model=AnalysisAnnotation,
    summary="Full LLM analysis (all types)",
)
async def full_analysis(
    request: FullAnalysisRequest,
) -> AnalysisAnnotation:
    """Run all LLM analyses sequentially via LLMOrchestrator.

    Executes sentiment, conflict, profanity, and topic analysis in
    sequence with progress tracking and graceful degradation. If a
    step fails, it is recorded in ``progress.error_steps`` and the
    overall result remains valid (partial).

    Optionally includes a dialogue summary (``include_summary=True``).

    The ``domain`` parameter (IP-6.1) enables domain-specific analysis
    by adding evaluation criteria for insurance, banking, healthcare,
    or telecom domains. Default is "general" (no domain additions).

    Returns:
        :class:`AnalysisAnnotation` with all results, progress, domain, and metadata.
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)

    # Validate domain parameter
    valid_domains = [d.value for d in DomainType]
    domain = request.domain if request.domain in valid_domains else "general"

    orchestrator = LLMOrchestrator()
    return await orchestrator.run_all_analyses(
        dialogue_text=dialogue_text,
        session_id=request.session_id,
        provider_id=request.provider_id,
        include_summary=request.include_summary,
        domain=domain,
    )


# ═══════════════════════════════════════════════════════════
# ID-3: Auto-Resolution + Sentiment Trajectory
# ═══════════════════════════════════════════════════════════


class ResolutionSentimentRequest(BaseModel):
    """Request body for the resolution-sentiment endpoint."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    provider_id: str = Field(
        "beeline",
        description="LLM provider: ollama, yandexgpt, gigachat, beeline",
    )
    domain: str = Field(
        "general",
        description="Domain type for domain-specific analysis: general, insurance, banking, healthcare, telecom",
    )


@router.post(
    "/resolution-sentiment",
    response_model=ResolutionSentimentResult,
    summary="Auto-resolution + sentiment trajectory (ID-3)",
)
async def resolution_sentiment_analysis(
    request: ResolutionSentimentRequest,
) -> ResolutionSentimentResult:
    """Classify dialogue resolution and track sentiment trajectory.

    Returns the resolution classification (resolved/unresolved/escalated/
    redirected), per-utterance sentiment trajectory with cumulative
    tracking, and the overall trajectory direction.

    This is DIFFERENT from IP-3.2 sentiment analysis (per-utterance only).
    ID-3 adds automatic resolution classification and cumulative sentiment
    trajectory tracking.

    The ``domain`` parameter (IP-6.1) enables domain-specific criteria.
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)

    # Validate domain parameter
    valid_domains = [d.value for d in DomainType]
    domain = request.domain if request.domain in valid_domains else "general"

    return await analyze_resolution_sentiment(
        dialogue_text=dialogue_text,
        session_id=request.session_id,
        provider_id=request.provider_id,
        domain=domain,
    )


# ═══════════════════════════════════════════════════════════
# IP-5.2: Error Classification
# ═══════════════════════════════════════════════════════════


class ErrorClassificationRequest(BaseModel):
    """Request body for the error classification endpoint."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    provider_id: str = Field(
        "beeline",
        description="LLM provider: ollama, yandexgpt, gigachat, beeline",
    )
    domain: str = Field(
        "general",
        description="Domain type for domain-specific analysis: general, insurance, banking, healthcare, telecom",
    )


@router.post(
    "/errors",
    response_model=ErrorClassificationResult,
    summary="Error classification (IP-5.2)",
)
async def error_classification(
    request: ErrorClassificationRequest,
) -> ErrorClassificationResult:
    """Classify errors in a previously uploaded dialogue.

    Identifies and categorises errors into 7 categories:
    communication_error, procedural_error, information_error,
    service_error, compliance_violation, empathy_failure, response_delay.

    Each error includes severity, description, and a suggested fix.

    The ``domain`` parameter (IP-6.1) enables domain-specific criteria
    (e.g. compliance_violation is more critical in banking/healthcare).
    """
    session = _validate_session(request.session_id)
    dialogue_text = _build_dialogue_text(session.dialog.turns)

    # Validate domain parameter
    valid_domains = [d.value for d in DomainType]
    domain = request.domain if request.domain in valid_domains else "general"

    return await analyze_errors(
        dialogue_text=dialogue_text,
        session_id=request.session_id,
        provider_id=request.provider_id,
        domain=domain,
    )

"""PII Masking API — 152-ФЗ compliance endpoints.

Endpoints:
  POST /mask   — Mask PII entities in text (Presidio + custom NER)
  GET  /status — PII masking subsystem status & statistics

Rate limits (slowapi):
  POST /mask   → 30/minute  (Presidio analysis is CPU-intensive)
  GET  /status → unlimited  (lightweight stats query)

Variant A (strict blocking): if Presidio is unavailable, all masking
requests return 503 — PII data is NEVER passed downstream unmasked.
This satisfies 152-FZ compliance requirements.

PII Leak Prevention (152-FZ):
  - API responses use PIIDetectionPublic (no raw PII text)
  - Error responses use generic messages (no PII context leaked)
  - PIIDetection with raw PII is internal-only, never serialized to API
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request

from app.middleware.rate_limiter import limiter
from app.models import (
    PIIDetection,
    PIIDetectionPublic,
    PIIEntityType,
    PIIMaskRequest,
    PIIMaskResponse,
    PIIMaskingConfig,
    PIIMaskingResult,
    PIIStatusResponse,
)

logger = logging.getLogger(__name__)

# Generic compliance error message — no PII context leaked via API
_COMPLIANCE_BLOCKED_MESSAGE = "PII masking unavailable — processing blocked for compliance"

router = APIRouter()


@router.post(
    "/mask",
    response_model=PIIMaskResponse,
    summary="Mask PII in text",
    description=(
        "Mask PII entities in the provided text using Microsoft Presidio "
        "and custom Russian/telecom recognizers for 152-FZ compliance. "
        "If PII masking service is unavailable, returns 503 (Variant A — "
        "strict blocking: unmasked PII data is never returned)."
    ),
)
@limiter.limit("30/minute")
async def mask_text(request: Request, body: PIIMaskRequest) -> PIIMaskResponse:
    """Mask PII entities in the provided text.

    Uses Microsoft Presidio + custom Russian recognizers for 152-FZ compliance.
    If PII masking service is unavailable, returns 503 (Variant A — strict blocking).
    """
    pii_service = getattr(request.app.state, "pii_masking_service", None)
    if not pii_service or not pii_service.is_available():
        raise HTTPException(
            status_code=503,
            detail=_COMPLIANCE_BLOCKED_MESSAGE,
        )

    # Build PIIMaskingConfig only when non-default options are requested
    config: PIIMaskingConfig | None = None
    if body.entity_types or body.min_score != 0.5:
        entity_types: List[PIIEntityType] = body.entity_types or list(PIIEntityType)
        config = PIIMaskingConfig(
            entity_types=entity_types,
            min_score=body.min_score,
        )

    result: PIIMaskingResult = pii_service.mask_text(body.text, config=config)
    if result.error:
        # Log full error server-side (may contain context), but return generic message
        logger.error("PII masking failed: %s", result.error)
        raise HTTPException(
            status_code=503,
            detail=_COMPLIANCE_BLOCKED_MESSAGE,
        )

    # Convert internal PIIDetection → PIIDetectionPublic (strip raw PII text)
    public_detections: List[PIIDetectionPublic] = [
        PIIDetectionPublic(
            entity_type=d.entity_type,
            start=d.start,
            end=d.end,
            score=d.score,
            recognizer=d.recognizer,
        )
        for d in result.detections
    ]

    return PIIMaskResponse(
        masked_text=result.masked_text,
        detections=public_detections,
        entity_counts=result.entity_counts,
        processing_time_ms=result.processing_time_ms,
    )


@router.get(
    "/status",
    response_model=PIIStatusResponse,
    summary="PII masking status",
    description=(
        "Get PII masking subsystem status including availability, "
        "circuit breaker state, and usage statistics."
    ),
)
async def pii_status(request: Request) -> PIIStatusResponse:
    """Get PII masking subsystem status.

    Returns availability, circuit breaker state, and usage statistics.
    """
    pii_service = getattr(request.app.state, "pii_masking_service", None)
    if not pii_service:
        return PIIStatusResponse(
            available=False,
            circuit_breaker_state="unknown",
            total_masked=0,
            entity_counts={},
            avg_latency_ms=0.0,
            language="ru",
            recognizers=[],
        )

    stats = pii_service.get_stats()
    return PIIStatusResponse(
        available=pii_service.is_available(),
        circuit_breaker_state=stats.get("circuit_breaker_state", "unknown"),
        total_masked=stats.get("total_masked", 0),
        entity_counts=stats.get("entity_counts", {}),
        avg_latency_ms=stats.get("avg_latency_ms", 0.0),
        language=stats.get("language", "ru"),
        recognizers=stats.get("recognizers", []),
    )

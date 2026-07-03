"""RAG router — Q&A over analyzed dialogues with hybrid search retrieval + LLM generation.

Endpoints:
  POST /api/rag/query — Ask a question about analyzed dialogues
  GET  /api/rag/status — RAG service status (FRIDA, vector store, providers)

Rate limits (slowapi):
  POST /query  → 30/minute  (FRIDA embed + FAISS search + LLM generation)
  GET  /status → unlimited  (lightweight check)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.middleware.rate_limiter import limiter
from app.models import RagQueryRequest, RagQueryResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# Input sanitization
# ═══════════════════════════════════════════════════════════

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _sanitize_text(text: str) -> str:
    """Remove control characters from text (XSS / injection protection).

    Preserves newline (\\n = \\x0a) and tab (\\t = \\x09) characters.
    Same pattern as FridaEmbeddingService._sanitize_text().
    """
    return _CONTROL_CHAR_PATTERN.sub("", text)


# ═══════════════════════════════════════════════════════════
# Response models (router-specific)
# ═══════════════════════════════════════════════════════════


class RagStatusResponse(BaseModel):
    """RAG service status response."""

    frida_available: bool = Field(..., description="Whether FRIDA embedding API is reachable")
    vectors_stored: int = Field(..., description="Total vectors in the FAISS index")
    unique_dialogues: int = Field(..., description="Number of unique indexed dialogues")
    index_size_bytes: int = Field(..., description="Estimated FAISS index size in bytes")
    rag_model: str = Field(..., description="LLM model used for RAG inference")
    rag_model_note: str = Field(
        "",
        description="Note about RAG model constraints",
    )
    providers: dict = Field(
        default_factory=dict,
        description="Per-provider status (configured, circuit_breaker_state)",
    )


# ═══════════════════════════════════════════════════════════
# Dependency: get services from app.state
# ═══════════════════════════════════════════════════════════


def _get_rag_service(request: Request):
    """Get RAGService from app state.

    Raises HTTPException 503 if service is not initialized.
    """
    rag_service = getattr(request.app.state, "rag_service", None)
    if rag_service is None:
        raise HTTPException(
            status_code=503,
            detail="RAG service not initialized. Server may still be starting up.",
        )
    return rag_service


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════


@router.post(
    "/query",
    response_model=RagQueryResponse,
    summary="RAG Q&A",
    description=(
        "Ask a question about analyzed dialogues. The system retrieves relevant "
        "fragments via hybrid search (morphology + FRIDA semantics + NER) and "
        "generates an answer using LLM with source citations. "
        "CRITICAL: Uses GLM-5.1 model only for RAG inference "
        "(Qwen gives HTTP 500 on /api/v2/Rag/inference)."
    ),
)
@limiter.limit("30/minute")
async def rag_query(
    request: Request,
    body: RagQueryRequest,
) -> RagQueryResponse:
    """RAG Q&A: retrieve relevant fragments → generate answer with sources."""
    # Sanitize question
    sanitized_question = _sanitize_text(body.question)
    if not sanitized_question:
        raise HTTPException(
            status_code=422,
            detail="Question must contain non-control characters.",
        )

    rag_service = _get_rag_service(request)

    try:
        result = await rag_service.query(
            question=sanitized_question,
            session_id=body.session_id,
            top_k=body.top_k,
            provider_id=body.provider_id,
        )
    except Exception as exc:
        logger.error("RAG query failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"RAG query failed: {exc}",
        )

    # If there's a non-empty error, return appropriate status code
    if result.error is not None:
        # Check for specific error types
        error_lower = result.error.lower()
        if "no dialogues indexed" in error_lower:
            # Client should index dialogues first — 404
            raise HTTPException(
                status_code=404,
                detail=result.error,
            )
        if "retrieval succeeded but answer generation failed" in error_lower:
            # Retrieval worked but LLM didn't — return result as-is (200 with error field)
            pass

    return result


@router.get(
    "/status",
    response_model=RagStatusResponse,
    summary="RAG service status",
    description="Check FRIDA availability, vector store stats, and LLM provider status.",
)
async def get_rag_status(request: Request) -> RagStatusResponse:
    """Get RAG service status for monitoring."""
    rag_service = _get_rag_service(request)

    try:
        status = await rag_service.get_status()
    except Exception as exc:
        logger.error("RAG status check failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"RAG status check failed: {exc}",
        )

    vector_store = status.get("vector_store", {})
    return RagStatusResponse(
        frida_available=status.get("frida_available", False),
        vectors_stored=vector_store.get("total_vectors", 0),
        unique_dialogues=vector_store.get("unique_dialogues", 0),
        index_size_bytes=vector_store.get("index_size_bytes", 0),
        rag_model=status.get("rag_model", "unknown"),
        rag_model_note=status.get("rag_model_note", ""),
        providers=status.get("providers", {}),
    )

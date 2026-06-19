"""Embeddings router — FRIDA vector embeddings and search endpoints.

Endpoints:
  POST /index              — Index a dialogue (embed + store vectors)
  POST /search/semantic    — Semantic search via FRIDA embeddings
  POST /search/hybrid      — Hybrid search (morphology + semantics + NER)
  GET  /status             — FRIDA + NLP services status

Rate limits (slowapi):
  POST /index          → 10/minute  (heavy: embedding + FAISS add)
  POST /search/*       → 100/minute (light but FRIDA rate limited)
  GET  /status         → unlimited  (lightweight check)
"""

from __future__ import annotations

import logging
import re
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.middleware.rate_limiter import limiter
from app.models import HybridSearchResult, VectorSearchResult

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
# Request / Response models
# ═══════════════════════════════════════════════════════════


class EmbeddingIndexRequest(BaseModel):
    """Request to index (vectorize) a dialogue."""

    session_id: str = Field(
        ..., min_length=1, max_length=100,
        description="Session ID of the uploaded dialogue",
    )
    chunk_type: Optional[str] = Field(
        "utterance", min_length=1, max_length=50,
        description="Chunking strategy: utterance, overlap, full_dialogue",
    )

    @field_validator("session_id")
    @classmethod
    def sanitize_session_id(cls, v: str) -> str:
        """Remove control characters from session_id."""
        return _sanitize_text(v)

    @field_validator("chunk_type")
    @classmethod
    def sanitize_chunk_type(cls, v: Optional[str]) -> Optional[str]:
        """Remove control characters from chunk_type."""
        if v is None:
            return v
        return _sanitize_text(v)


class EmbeddingIndexResponse(BaseModel):
    """Response after indexing a dialogue."""

    session_id: str = Field(..., description="Session ID that was indexed")
    chunks_indexed: int = Field(..., description="Number of chunks created")
    vectors_stored: int = Field(..., description="Total vectors in the store after indexing")


class SearchRequest(BaseModel):
    """Request for semantic or hybrid search."""

    query: str = Field(
        ..., min_length=1, max_length=2000,
        description="Search query text",
    )
    session_id: Optional[str] = Field(
        None, min_length=1, max_length=100,
        description="Optional session ID to restrict search scope",
    )
    top_k: int = Field(10, ge=1, le=100, description="Number of results to return")
    use_semantic: bool = Field(True, description="Include semantic (FRIDA) search")
    use_ner: bool = Field(True, description="Include NER boost in ranking")
    include_llm_summary: bool = Field(
        False, description="Include LLM summary in hybrid results (future)",
    )

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Remove control characters from query."""
        return _sanitize_text(v)

    @field_validator("session_id")
    @classmethod
    def sanitize_session_id(cls, v: Optional[str]) -> Optional[str]:
        """Remove control characters from session_id."""
        if v is None:
            return v
        return _sanitize_text(v)


class SemanticSearchResponse(BaseModel):
    """Response from semantic search."""

    results: List[VectorSearchResult] = Field(
        default_factory=list, description="Search results sorted by score desc",
    )
    query: str = Field(..., description="Original query text")
    total: int = Field(..., description="Total number of results returned")


class HybridSearchResponse(BaseModel):
    """Response from hybrid search."""

    results: List[HybridSearchResult] = Field(
        default_factory=list, description="Search results sorted by combined_score desc",
    )
    query: str = Field(..., description="Original query text")
    total: int = Field(..., description="Total number of results returned")


class EmbeddingStatusResponse(BaseModel):
    """Status of FRIDA embedding and NLP services."""

    frida_available: bool = Field(..., description="Whether FRIDA API is reachable")
    vectors_stored: int = Field(..., description="Total vectors in the store")
    unique_dialogues: int = Field(..., description="Number of unique dialogues indexed")
    index_size_bytes: int = Field(..., description="Estimated FAISS index size in bytes")
    nlp_provider: Literal["natasha", "deeppavlov", "none"] = Field(
        ..., description="Active NLP provider",
    )
    natasha_available: bool = Field(..., description="Whether Natasha NER is available")
    deeppavlov_available: bool = Field(
        False, description="Whether DeepPavlov NER is available",
    )


# ═══════════════════════════════════════════════════════════
# Dependency: get services from app.state
# ═══════════════════════════════════════════════════════════


def _get_embedding_service(request: Request):
    """Get FridaEmbeddingService from app state."""
    return request.app.state.embedding_service


def _get_vector_store(request: Request):
    """Get VectorStore from app state."""
    return request.app.state.vector_store


def _get_hybrid_search_service(request: Request):
    """Get HybridSearchService from app state."""
    return request.app.state.hybrid_search_service


def _get_chunker(request: Request):
    """Get Chunker from app state."""
    return request.app.state.chunker


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════


@router.post(
    "/index",
    response_model=EmbeddingIndexResponse,
    summary="Index a dialogue",
    description="Vectorize a dialogue: chunk → embed via FRIDA → store in VectorStore.",
)
@limiter.limit("10/minute")
async def index_dialogue(
    request: Request,
    body: EmbeddingIndexRequest,
) -> EmbeddingIndexResponse:
    """Index a dialogue: chunk it, embed via FRIDA, and store vectors."""
    from app.utils.session import session_store

    embedding_service = _get_embedding_service(request)
    vector_store = _get_vector_store(request)
    chunker = _get_chunker(request)

    # Validate session
    session = session_store.get(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{body.session_id}' not found. Upload a dialogue first.",
        )

    if session.dialog is None:
        raise HTTPException(
            status_code=400,
            detail="No dialogue uploaded for this session. Upload an RTF file first.",
        )

    # Check FRIDA availability
    try:
        frida_available = await embedding_service.is_available()
    except Exception:
        frida_available = False

    if not frida_available:
        raise HTTPException(
            status_code=503,
            detail="FRIDA embedding service unavailable. Please try again later.",
        )

    # Step 1: Chunk dialogue
    chunks = chunker.chunk_dialogue(session.dialog, dialogue_id=body.session_id)

    if not chunks:
        return EmbeddingIndexResponse(
            session_id=body.session_id,
            chunks_indexed=0,
            vectors_stored=vector_store.get_stats()["total_vectors"],
        )

    # Step 2: Embed chunks via FRIDA
    texts = [chunk.text for chunk in chunks]

    try:
        embeddings = await embedding_service.embed_batch(texts)
    except ConnectionError as exc:
        logger.error("FRIDA connection error during indexing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="FRIDA embedding service unavailable (circuit breaker open).",
        )
    except Exception as exc:
        logger.error("Embedding failed during indexing: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Embedding failed: {exc}",
        )

    # Step 3: Build metadata and add to VectorStore
    metadata = [chunk.metadata.model_dump() for chunk in chunks]

    try:
        vector_store.add(embeddings, metadata)
    except Exception as exc:
        logger.error("VectorStore add failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Vector store add failed: {exc}",
        )

    return EmbeddingIndexResponse(
        session_id=body.session_id,
        chunks_indexed=len(chunks),
        vectors_stored=vector_store.get_stats()["total_vectors"],
    )


@router.post(
    "/search/semantic",
    response_model=SemanticSearchResponse,
    summary="Semantic search",
    description="Search via FRIDA embeddings + FAISS vector similarity.",
)
@limiter.limit("100/minute")
async def search_semantic(
    request: Request,
    body: SearchRequest,
) -> SemanticSearchResponse:
    """Semantic search: embed query → VectorStore.search → results."""
    embedding_service = _get_embedding_service(request)
    vector_store = _get_vector_store(request)

    # Check FRIDA availability
    try:
        frida_available = await embedding_service.is_available()
    except Exception:
        frida_available = False

    if not frida_available:
        raise HTTPException(
            status_code=503,
            detail="FRIDA embedding service unavailable. Cannot perform semantic search.",
        )

    # Embed query
    try:
        query_vector = await embedding_service.embed(body.query)
    except ConnectionError as exc:
        logger.error("FRIDA connection error during search: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="FRIDA embedding service unavailable (circuit breaker open).",
        )
    except Exception as exc:
        logger.error("Query embedding failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Query embedding failed: {exc}",
        )

    # Search VectorStore
    results = vector_store.search(query_vector, k=body.top_k)

    # Filter by session_id if provided
    if body.session_id:
        results = [r for r in results if r.dialogue_id == body.session_id]

    return SemanticSearchResponse(
        results=results,
        query=body.query,
        total=len(results),
    )


@router.post(
    "/search/hybrid",
    response_model=HybridSearchResponse,
    summary="Hybrid search",
    description="Hybrid search: morphology + semantics + NER boost via RRF.",
)
@limiter.limit("100/minute")
async def search_hybrid(
    request: Request,
    body: SearchRequest,
) -> HybridSearchResponse:
    """Hybrid search: morphological + semantic + NER via RRF."""
    from app.utils.session import session_store

    hybrid_search_service = _get_hybrid_search_service(request)

    # Get dialogue and dictionaries from session (for morphological search)
    dialogue = None
    dictionaries = None

    if body.session_id:
        session = session_store.get(body.session_id)
        if session is not None:
            dialogue = session.dialog
            if session.dictionaries:
                dictionaries = list(session.dictionaries.values())

    # Run hybrid search
    try:
        results = await hybrid_search_service.search(
            query=body.query,
            dialogue=dialogue,
            dictionaries=dictionaries,
            top_k=body.top_k,
            use_semantic=body.use_semantic,
            use_ner=body.use_ner,
        )
    except Exception as exc:
        logger.error("Hybrid search failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Hybrid search failed: {exc}",
        )

    return HybridSearchResponse(
        results=results,
        query=body.query,
        total=len(results),
    )


@router.get(
    "/status",
    response_model=EmbeddingStatusResponse,
    summary="Embedding service status",
    description="Check FRIDA availability, vector store stats, and NLP provider status.",
)
async def get_status(request: Request) -> EmbeddingStatusResponse:
    """Get status of FRIDA embeddings and NLP services."""
    embedding_service = _get_embedding_service(request)
    vector_store = _get_vector_store(request)
    hybrid_search_service = _get_hybrid_search_service(request)

    # Check FRIDA availability
    try:
        frida_available = await embedding_service.is_available()
    except Exception:
        frida_available = False

    # Get vector store stats
    stats = vector_store.get_stats()

    # Determine NLP provider
    natasha_available = hybrid_search_service._has_ner
    nlp_provider: Literal["natasha", "deeppavlov", "none"]
    if natasha_available:
        nlp_provider = "natasha"
    else:
        nlp_provider = "none"

    return EmbeddingStatusResponse(
        frida_available=frida_available,
        vectors_stored=stats["total_vectors"],
        unique_dialogues=stats["unique_dialogues"],
        index_size_bytes=stats["index_size_bytes"],
        nlp_provider=nlp_provider,
        natasha_available=natasha_available,
        deeppavlov_available=False,
    )

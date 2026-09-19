"""FastAPI application entry point with CORS, rate limiting, structured logging, and healthcheck."""

import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.middleware.rate_limiter import limiter
from app.middleware.structured_logging import StructuredLoggingMiddleware, setup_structured_logging
from app.routers import upload, analysis, batch, providers, embeddings, feedback, dictionary, export, rag, health, pii, mining


# ── Make smartlogger importable ──────────────────────────────
_TRANSCRIB_DIR = Path(__file__).resolve().parent.parent.parent / "Transcrib"
if _TRANSCRIB_DIR.is_dir() and str(_TRANSCRIB_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSCRIB_DIR))


# ── OpenAPI tags ─────────────────────────────────────────────
_OPENAPI_TAGS = [
    {"name": "upload", "description": "File upload (RTF, XML dictionaries, batch RTF)"},
    {"name": "analysis", "description": "Dialog analysis and results"},
    {"name": "batch", "description": "Batch analysis"},
    {"name": "providers", "description": "LLM provider management"},
    {"name": "embeddings", "description": "Vector embeddings and search (FRIDA)"},
    {"name": "feedback", "description": "Phrase match feedback (AG-UIREWORK-4)"},
    {"name": "dictionary", "description": "Dictionary display tokens (SpeechLab)"},
    {"name": "export", "description": "Export analysis results (Excel, PDF)"},
    {"name": "rag", "description": "RAG Q&A over analyzed dialogues (retrieval + LLM generation)"},
    {"name": "health", "description": "System health check and monitoring (ID-15)"},
    {"name": "pii", "description": "PII masking for 152-FZ compliance (Presidio + custom NER)"},
    {"name": "mining", "description": "Offline corpus mining (discovery layer, НЕ production runtime)"},
]


def _init_services(embedding_service=None) -> None:
    """Initialize embedding services and attach to app.state.

    Called during lifespan startup. Services are singletons shared
    across all requests via app.state.

    Args:
        embedding_service: Pre-resolved embedding service (frida or local
            TF-IDF fallback) from resolve_embedding_service(). When None
            (legacy/test path), a FRIDA service is created directly.
    """
    from app.services.chunker import Chunker
    from app.services.embedding import FridaEmbeddingService
    from app.services.hybrid_search import HybridSearchService
    from app.services.vector_store import VectorStore

    if embedding_service is None:
        # Legacy sync path (direct _init_services() calls in tests):
        # default to FRIDA exactly as before the provider switch existed.
        embedding_service = FridaEmbeddingService(
            api_key=settings.beeline_api_key,
            base_url=settings.frida_base_url,
            model=settings.frida_model,
            max_batch_size=settings.frida_batch_size,
            max_context_tokens=settings.frida_max_context_tokens,
        )
        app.state.embedding_provider = "frida"
        app.state.embedding_mode = "frida"

    # VectorStore (FAISS IndexFlatIP, auto-save to configured dir)
    vector_store = VectorStore(
        dimension=settings.vector_store_dimension,
        index_path=str(settings.vector_store_index_dir),
        auto_save=settings.vector_store_auto_save,
    )

    # Load existing index if available
    index_dir = settings.vector_store_index_dir
    if index_dir.exists() and (index_dir / "index.faiss").exists():
        try:
            vector_store.load(str(index_dir))
            logger.info("VectorStore loaded from %s (%d vectors)", index_dir, vector_store.index.ntotal)
        except Exception as exc:
            logger.warning("VectorStore load failed: %s. Starting with empty index.", exc)

    # Local TF-IDF provider: restore the fitted vocabulary so persisted
    # FAISS vectors remain valid across restarts (see local_embedding.py).
    if getattr(embedding_service, "provider_name", "frida") == "local":
        try:
            embedding_service.load(str(settings.vector_store_index_dir))
        except Exception as exc:
            logger.warning("Local TF-IDF vocabulary load failed: %s", exc)

    # Chunker (razdel + Natasha NER)
    chunker = Chunker()

    # SearchCache (P2 optimization — caches run_hierarchical_search results
    # so repeated "Анализировать" clicks on the same dialog + dictionaries
    # do not re-run the expensive morphological search).
    from app.services.search_cache import SearchCache
    search_cache = SearchCache(max_entries=256, ttl_seconds=3600)

    # HybridSearchService (RRF + NER boost)
    hybrid_search_service = HybridSearchService(
        embedding_service=embedding_service,
        vector_store=vector_store,
        rrf_k=settings.hybrid_search_rrf_k,
        ner_boost_per_match=settings.hybrid_search_ner_boost_per_match,
        ner_per_weight=settings.hybrid_search_ner_per_weight,
    )

    # Attach to app.state
    app.state.embedding_service = embedding_service
    app.state.vector_store = vector_store
    app.state.chunker = chunker
    app.state.hybrid_search_service = hybrid_search_service
    app.state.search_cache = search_cache

    # Track B — offline corpus mining (composition over FRIDA + FAISS + LLM).
    # NEВ production-runtime: dict_mining does NOT call into search.py runtime.
    from app.services.dict_mining import DictionaryMiningService
    from app.services.session_store_sqlite import MiningStore

    mining_store = MiningStore(db_path=str(settings.session_db_path))
    mining_service = DictionaryMiningService(
        embedding_service=embedding_service,
        vector_store=vector_store,
        chunker=chunker,
        mining_store=mining_store,
    )
    app.state.mining_store = mining_store
    app.state.mining_service = mining_service

    # RAG service (uses existing HybridSearch + FRIDA + LLM providers)
    from app.services.rag import RAGService
    rag_service = RAGService(
        hybrid_search_service=hybrid_search_service,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    app.state.rag_service = rag_service

    # PIIMaskingService (ID-4) — 152-FZ compliance
    if settings.pii_masking_enabled:
        from app.services.pii_masking import PIIMaskingService

        pii_service = PIIMaskingService(
            language=settings.pii_masking_language,
            min_score_threshold=settings.pii_masking_min_score,
            circuit_reset_timeout=settings.pii_masking_circuit_reset_seconds,
            failure_threshold=settings.pii_masking_failure_threshold,
        )
        app.state.pii_masking_service = pii_service

        if not pii_service.is_available():
            logger.warning(
                "PII masking enabled but Presidio unavailable — processing will be blocked",
            )
    else:
        app.state.pii_masking_service = None
        logger.warning("PII masking DISABLED — not compliant with 152-FZ")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup / shutdown hooks."""
    # Startup
    logger.info("Call Center AI backend starting - debug=%s", settings.debug)
    logger.info("Transcrib dir: %s (exists=%s)", _TRANSCRIB_DIR, _TRANSCRIB_DIR.is_dir())

    # Initialize embedding services (provider: frida | local | auto-fallback)
    from app.services.embedding_factory import resolve_embedding_service

    embedding_service, provider_name, provider_mode = await resolve_embedding_service()
    app.state.embedding_provider = provider_name
    app.state.embedding_mode = provider_mode
    _init_services(embedding_service=embedding_service)
    logger.info(
        "Embedding services initialized (provider=%s, mode=%s)",
        provider_name,
        provider_mode,
    )

    # Fetch and log dynamic LLM concurrency limits from Beeline AI
    # (observability only — semaphores are not resized at runtime).
    try:
        from app.services.llm_limits import fetch_and_log_all_limits
        await fetch_and_log_all_limits()
    except Exception as exc:  # noqa: BLE001 — startup must not fail on monitoring
        logger.warning("Startup: LLM limits fetch skipped — %s", exc)

    yield

    # Shutdown — clean up expired sessions, vacuum DB
    from app.utils.session import session_store
    removed = session_store.cleanup_expired()
    if removed:
        logger.info("Cleaned up %d expired sessions", removed)

    # Vacuum the session database to reclaim free pages and truncate WAL.
    # Safe to call on memory backends (no-op) and on SQLite with no free pages.
    if hasattr(session_store, "vacuum"):
        try:
            session_store.vacuum()
        except Exception as exc:
            logger.warning("Session DB vacuum on shutdown failed: %s", exc)

    # Close FRIDA HTTP client (local TF-IDF provider has no HTTP client —
    # persist its vocabulary instead so restarts keep the vector space).
    if hasattr(app.state, "embedding_service"):
        service = app.state.embedding_service
        try:
            if getattr(service, "provider_name", "frida") == "local":
                service.save(str(settings.vector_store_index_dir))
                logger.info("Local TF-IDF vocabulary saved")
            else:
                await service.http_client.aclose()
                logger.info("FRIDA HTTP client closed")
        except Exception as exc:
            logger.warning("Embedding service shutdown failed: %s", exc)

    logger.info("Call Center AI backend shutting down")


app = FastAPI(
    title="Call Center AI — Dialog Analysis",
    version=settings.app_version,
    description="FastAPI backend for RTF/XML dialog analysis with LLM support, "
                "FRIDA embeddings, and hybrid search",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)

# ── Rate limiting (slowapi) ────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # Already specific: localhost:5173, localhost:3000
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── GZip compression (P4 Level 1) ─────────────────────────────
# Compress HTTP responses larger than 100 KB. This turns a ~62 MB
# dictionary payload into a ~5 MB transfer over the wire (≈90% reduction)
# with negligible CPU cost — clients send `Accept-Encoding: gzip`
# automatically. Must be added after CORS so that headers are not
# stripped before compression runs.
app.add_middleware(GZipMiddleware, minimum_size=100 * 1024)

# ── Structured logging middleware (opt-in, does not replace existing handlers) ──
app.add_middleware(StructuredLoggingMiddleware)
setup_structured_logging()

# ── Routers ──────────────────────────────────────────────────
app.include_router(upload.sessions_router, prefix="/api/sessions", tags=["upload"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(batch.router, prefix="/api/analysis", tags=["batch"])
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
app.include_router(embeddings.router, prefix="/api/embeddings", tags=["embeddings"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(dictionary.router, prefix="/api/dictionary", tags=["dictionary"])
app.include_router(export.router, prefix="/api", tags=["export"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(pii.router, prefix="/api/pii", tags=["pii"])
app.include_router(mining.router, prefix="/api", tags=["mining"])


# ── Legacy healthcheck (kept for backward compatibility) ─────
@app.get("/health", summary="Health check (legacy)", deprecated=True)
async def healthcheck():
    """Return service health status.

    Deprecated: use GET /api/health instead for structured health data.
    """
    smartlogger_ok = True
    try:
        import smartlogger  # noqa: F401
    except ImportError:
        smartlogger_ok = False

    return {
        "status": "ok",
        "version": settings.app_version,
        "smartlogger_available": smartlogger_ok,
        "transcrib_dir": str(_TRANSCRIB_DIR),
        "transcrib_exists": _TRANSCRIB_DIR.is_dir(),
    }

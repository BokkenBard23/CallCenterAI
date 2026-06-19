"""FastAPI application entry point with CORS, rate limiting, and healthcheck."""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.middleware.rate_limiter import limiter
from app.routers import upload, analysis, batch, providers, embeddings, feedback


# ── Make smartlogger importable ──────────────────────────────
_TRANSCRIB_DIR = Path(__file__).resolve().parent.parent.parent / "Transcrib"
if _TRANSCRIB_DIR.is_dir() and str(_TRANSCRIB_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSCRIB_DIR))


# ── OpenAPI tags ─────────────────────────────────────────────
_OPENAPI_TAGS = [
    {"name": "upload", "description": "File upload (RTF, XML dictionaries)"},
    {"name": "analysis", "description": "Dialog analysis and results"},
    {"name": "batch", "description": "Batch analysis"},
    {"name": "providers", "description": "LLM provider management"},
    {"name": "embeddings", "description": "Vector embeddings and search (FRIDA)"},
    {"name": "feedback", "description": "Phrase match feedback (AG-UIREWORK-4)"},
]


def _init_services() -> None:
    """Initialize FRIDA embedding services and attach to app.state.

    Called during lifespan startup. Services are singletons shared
    across all requests via app.state.
    """
    from app.services.chunker import Chunker
    from app.services.embedding import FridaEmbeddingService
    from app.services.hybrid_search import HybridSearchService
    from app.services.vector_store import VectorStore

    # FridaEmbeddingService (reuses BEELINE_API_KEY from settings)
    api_key = settings.beeline_api_key
    embedding_service = FridaEmbeddingService(
        api_key=api_key,
        base_url=settings.frida_base_url,
        model=settings.frida_model,
        max_batch_size=settings.frida_batch_size,
        max_context_tokens=settings.frida_max_context_tokens,
    )

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
            print(f"[OK] VectorStore loaded from {index_dir} ({vector_store.index.ntotal} vectors)")
        except Exception as exc:
            print(f"[WARN] VectorStore load failed: {exc}. Starting with empty index.")

    # Chunker (razdel + Natasha NER)
    chunker = Chunker()

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup / shutdown hooks."""
    # Startup
    print(f"[OK] Call Center AI backend starting - debug={settings.debug}")
    print(f"  Transcrib dir: {_TRANSCRIB_DIR} (exists={_TRANSCRIB_DIR.is_dir()})")

    # Initialize FRIDA services
    _init_services()
    print("[OK] FRIDA embedding services initialized")

    yield

    # Shutdown — clean up expired sessions
    from app.utils.session import session_store
    removed = session_store.cleanup_expired()
    if removed:
        print(f"[OK] Cleaned up {removed} expired sessions")

    # Close FRIDA HTTP client
    if hasattr(app.state, "embedding_service"):
        try:
            await app.state.embedding_service.http_client.aclose()
            print("[OK] FRIDA HTTP client closed")
        except Exception as exc:
            print(f"[WARN] FRIDA HTTP client close failed: {exc}")

    print("[OK] Call Center AI backend shutting down")


app = FastAPI(
    title="Call Center AI — Dialog Analysis",
    version="0.1.0",
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
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(batch.router, prefix="/api/analysis", tags=["batch"])
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
app.include_router(embeddings.router, prefix="/api/embeddings", tags=["embeddings"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])


# ── Healthcheck ──────────────────────────────────────────────
@app.get("/health", summary="Health check")
@app.get("/api/health", summary="Health check (API prefix)")
async def healthcheck():
    """Return service health status."""
    smartlogger_ok = True
    try:
        import smartlogger  # noqa: F401
    except ImportError:
        smartlogger_ok = False

    return {
        "status": "ok",
        "version": "0.1.0",
        "smartlogger_available": smartlogger_ok,
        "transcrib_dir": str(_TRANSCRIB_DIR),
        "transcrib_exists": _TRANSCRIB_DIR.is_dir(),
    }

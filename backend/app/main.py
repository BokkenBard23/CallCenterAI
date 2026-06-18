"""FastAPI application entry point with CORS and healthcheck."""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import upload, analysis, providers


# ── Make smartlogger importable ──────────────────────────────
_TRANSCRIB_DIR = Path(__file__).resolve().parent.parent.parent / "Transcrib"
if _TRANSCRIB_DIR.is_dir() and str(_TRANSCRIB_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSCRIB_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup / shutdown hooks."""
    # Startup
    print(f"[OK] Call Center AI backend starting - debug={settings.debug}")
    print(f"  Transcrib dir: {_TRANSCRIB_DIR} (exists={_TRANSCRIB_DIR.is_dir()})")
    yield
    # Shutdown
    print("[OK] Call Center AI backend shutting down")


app = FastAPI(
    title="Call Center AI — Dialog Analysis",
    version="0.1.0",
    description="FastAPI backend for RTF/XML dialog analysis with LLM support",
    lifespan=lifespan,
)

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
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])


# ── Healthcheck ──────────────────────────────────────────────
@app.get("/health", summary="Health check")
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

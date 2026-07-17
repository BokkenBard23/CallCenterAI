"""Health check router — System status and service availability.

Endpoints:
  GET / — Health check with system metrics and service availability

This endpoint does NOT require authentication. It provides:
  - Overall health status (healthy / degraded / unhealthy)
  - Application version and uptime
  - Service availability checks (session store, FRIDA, vector store)
  - Active sessions count and vector store size
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Tuple

from fastapi import APIRouter, Request

from app.config import settings
from app.models import HealthCheckResult
from app.utils.session import session_store

logger = logging.getLogger(__name__)

router = APIRouter()

# Application start time (module-level constant, set once on import)
_START_TIME: float = time.monotonic()

# Application version (matches config.py app_version)
APP_VERSION: str = "1.0.0"


def _compute_uptime() -> float:
    """Return seconds elapsed since application start."""
    return round(time.monotonic() - _START_TIME, 2)


def _check_session_store() -> str:
    """Check if session store is operational."""
    try:
        # Try listing sessions — if store is broken, this will raise
        session_store.list_sessions()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_frida(request: Request) -> Tuple[str, bool]:
    """Check FRIDA embedding service availability.

    Returns:
        Tuple of (check_result, frida_available_bool).
    """
    try:
        embedding_service = getattr(request.app.state, "embedding_service", None)
        if embedding_service is None:
            return "error: embedding service not initialized", False

        is_available = await embedding_service.is_available()
        if is_available:
            return "ok", True
        return "error: FRIDA service unavailable", False
    except Exception as exc:
        return f"error: {exc}", False


def _check_vector_store(request: Request) -> str:
    """Check vector store availability."""
    try:
        vector_store = getattr(request.app.state, "vector_store", None)
        if vector_store is None:
            return "error: vector store not initialized"
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


# Mining tables whose absence degrades offline-corpus-mining functionality.
# If any are missing, mining jobs cannot run — but the core search/upload
# pipeline is unaffected, so this degrades (not breaks) overall health.
_MINING_TABLES = ["mining_jobs", "mining_corpus", "mining_checkpoints"]


def _check_mining_db(request: Request) -> str:
    """Check that mining DB tables exist.

    Returns ``"ok"`` when all required mining tables are present, or
    ``"missing"`` when any are absent (e.g. after DB recreation). Errors
    during the check itself are reported as ``"error: <detail>"``.
    """
    try:
        mining_store = getattr(request.app.state, "mining_store", None)
        if mining_store is None:
            return "missing"
        existence = mining_store.verify_tables_exist(_MINING_TABLES)
        if all(existence.values()):
            return "ok"
        return "missing"
    except Exception as exc:
        return f"error: {exc}"


def _count_active_sessions() -> int:
    """Count non-expired sessions."""
    try:
        sessions = session_store.list_sessions()
        return len(sessions)
    except Exception:
        return 0


def _get_vector_store_size(request: Request) -> int:
    """Get number of vectors in the FAISS index."""
    try:
        vector_store = getattr(request.app.state, "vector_store", None)
        if vector_store is None:
            return 0
        stats = vector_store.get_stats()
        return stats.get("total_vectors", 0)
    except Exception:
        return 0


@router.get("", response_model=HealthCheckResult, summary="Health check")
async def health_check(request: Request) -> HealthCheckResult:
    """Return system health status with service availability checks.

    Checks: session store, FRIDA embedding service, vector store.
    Returns version, uptime, active sessions count, and vector store size.
    """
    if not settings.health_check_enabled:
        return HealthCheckResult(
            status="healthy",
            version=settings.app_version,
            uptime_seconds=_compute_uptime(),
            checks={"health_check": "disabled"},
            active_sessions=0,
            frida_available=False,
            vector_store_size=0,
            pii_masking={
                "enabled": settings.pii_masking_enabled,
                "available": False,
                "circuit_breaker_state": "unknown",
            },
        )

    # ── Run service checks ───────────────────────────────────────
    checks: Dict[str, str] = {}

    checks["session_store"] = _check_session_store()
    frida_check, frida_available = await _check_frida(request)
    checks["frida"] = frida_check
    checks["vector_store"] = _check_vector_store(request)
    checks["mining_db"] = _check_mining_db(request)

    # ── Compute aggregate status ─────────────────────────────────
    # Core services: session_store, frida, vector_store.
    # mining_db is a secondary/offline subsystem: a "missing" mining_db
    # degrades health (mining unavailable) but does NOT make the app
    # unhealthy, since core search/upload still work.
    core_checks = ["session_store", "frida", "vector_store"]
    core_ok = all(checks.get(c) == "ok" for c in core_checks)
    mining_ok = checks.get("mining_db") == "ok"
    any_core_error = any(
        checks.get(c, "").startswith("error") for c in core_checks
    )

    if core_ok and mining_ok:
        status = "healthy"
    elif any_core_error:
        # If session store is down → unhealthy (core functionality broken)
        session_ok = checks.get("session_store") == "ok"
        if session_ok:
            status = "degraded"
        else:
            status = "unhealthy"
    else:
        # Core OK but mining missing/error → degraded (not healthy, not unhealthy)
        status = "degraded"

    # ── PII Masking status ──────────────────────────────────────────
    pii_masking_service = getattr(request.app.state, "pii_masking_service", None)
    pii_masking = {
        "enabled": settings.pii_masking_enabled,
        "available": pii_masking_service.is_available() if pii_masking_service else False,
        "circuit_breaker_state": (
            pii_masking_service.get_stats().get("circuit_breaker_state", "unknown")
            if pii_masking_service
            else "unknown"
        ),
    }

    # ── Collect metrics ──────────────────────────────────────────
    active_sessions = _count_active_sessions()
    vector_store_size = _get_vector_store_size(request)

    return HealthCheckResult(
        status=status,
        version=settings.app_version,
        uptime_seconds=_compute_uptime(),
        checks=checks,
        active_sessions=active_sessions,
        frida_available=frida_available,
        vector_store_size=vector_store_size,
        pii_masking=pii_masking,
    )

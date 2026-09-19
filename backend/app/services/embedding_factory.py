"""Embedding provider factory: EMBEDDING_PROVIDER=frida | local | auto.

Resolves which embedding backend the application uses:

  - ``frida`` — always use the FRIDA API (Beeline AI), previous behaviour.
  - ``local`` — always use the offline TF-IDF provider
    (:class:`app.services.local_embedding.LocalTfidfEmbeddingService`).
  - ``auto`` (default) — probe FRIDA ONCE with a short timeout at startup;
    if it is unreachable, fall back to the local provider and remember the
    decision for the lifetime of the process.

The active provider is exposed on ``app.state.embedding_provider`` and
reported by ``GET /api/health`` and ``GET /api/embeddings/status``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = {"frida", "local", "auto"}
_DEFAULT_PROBE_TIMEOUT = 5.0


def _normalize_mode(mode: str) -> str:
    """Validate the EMBEDDING_PROVIDER setting.

    Unknown values are logged and treated as ``auto`` (safe default:
    prefer the full-featured FRIDA backend, degrade to local on failure).
    """
    value = (mode or "auto").strip().lower()
    if value not in _VALID_PROVIDERS:
        logger.warning(
            "EMBEDDING_PROVIDER=%r is invalid (expected one of %s) — "
            "falling back to 'auto'",
            mode,
            sorted(_VALID_PROVIDERS),
        )
        return "auto"
    return value


async def resolve_embedding_service() -> Tuple[Any, str, str]:
    """Create the embedding service according to EMBEDDING_PROVIDER.

    Args:
        None (reads settings).

    Returns:
        Tuple of (embedding_service, provider_name, mode) where
        provider_name is "frida" | "local" (the ACTIVELY used backend) and
        mode is the configured EMBEDDING_PROVIDER value ("frida" | "local"
        | "auto").

    Notes:
        This function never raises on a missing BEELINE_API_KEY: with
        ``mode == "frida"`` an empty key only logs a warning (FRIDA
        requests will later fail with 401); with ``mode == "auto"`` an
        unreachable FRIDA (timeout or probe error) results in a fallback
        to the local TF-IDF provider.
    """
    from app.services.embedding import FridaEmbeddingService
    from app.services.local_embedding import LocalTfidfEmbeddingService

    mode = _normalize_mode(settings.embedding_provider)
    probe_timeout = float(getattr(settings, "embedding_probe_timeout", _DEFAULT_PROBE_TIMEOUT))

    def _make_frida() -> FridaEmbeddingService:
        return FridaEmbeddingService(
            api_key=settings.beeline_api_key,
            base_url=settings.frida_base_url,
            model=settings.frida_model,
            max_batch_size=settings.frida_batch_size,
            max_context_tokens=settings.frida_max_context_tokens,
        )

    def _make_local() -> LocalTfidfEmbeddingService:
        return LocalTfidfEmbeddingService(
            dimension=settings.vector_store_dimension,
        )

    if mode == "frida":
        if not settings.beeline_api_key:
            logger.warning(
                "EMBEDDING_PROVIDER=frida but BEELINE_API_KEY is empty — "
                "FRIDA requests will fail with 401"
            )
        service = _make_frida()
        return service, "frida", mode

    if mode == "local":
        service = _make_local()
        logger.info("Embedding provider: local (TF-IDF, offline)")
        return service, "local", mode

    # ── auto: probe FRIDA once with a short timeout ──────────────
    frida = _make_frida()
    frida_ok = False
    try:
        frida_ok = await asyncio.wait_for(frida.is_available(), timeout=probe_timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "Embedding auto-probe: FRIDA did not respond within %.1fs", probe_timeout
        )
    except Exception as exc:  # noqa: BLE001 — any probe failure means "unavailable"
        logger.warning("Embedding auto-probe: FRIDA check failed — %s", exc)

    if frida_ok:
        logger.info("Embedding provider: frida (auto-probe succeeded)")
        return frida, "frida", "auto"

    # FRIDA unreachable → close its HTTP client and fall back to local.
    try:
        await frida.http_client.aclose()
    except Exception as exc:  # noqa: BLE001 — cleanup must not break startup
        logger.warning("Failed to close unused FRIDA client: %s", exc)

    logger.info(
        "Embedding provider: local (FRIDA unavailable — auto-fallback to TF-IDF)"
    )
    return _make_local(), "local", "auto"


def provider_status(app_state: Any) -> Dict[str, str]:
    """Read the active embedding provider info from app.state.

    Returns a dict {"provider": ..., "mode": ...} with conservative
    defaults ("frida"/"unknown") when the state is not populated (e.g.
    during tests that bypass the lifespan).
    """
    provider = getattr(app_state, "embedding_provider", "frida")
    mode = getattr(app_state, "embedding_mode", "unknown")
    return {"provider": provider, "mode": mode}

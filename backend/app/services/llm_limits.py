"""Dynamic LLM concurrency limits via Beeline AI API.

Queries ``GET /api/v3/me/limits?model={publicModelName}`` to get the actual
``requestCapacity.limit`` (concurrent request limit) per model. Cached with a
TTL to avoid excessive API calls.

This module is used as an **observability / monitoring** feature:
  - On application startup (see :func:`app.main.lifespan`) the limits are
    fetched for every configured model and logged.
  - The configured ``asyncio.Semaphore`` sizes in :mod:`app.services.llm`
    remain driven by ``Settings.glm_max_concurrent`` / ``qwen35_max_concurrent``
    / ``qwen36_max_concurrent`` (fallback defaults).
  - If a dynamically-queried limit differs from the configured value, a
    ``WARNING`` is logged so the operator can update config — semaphores are
    **not** resized at runtime (semaphore size is fixed at creation, and
    resizing would introduce complex concurrency hazards).

Reference:
    https://docs.ai.beeline.ru/quickstart/models/  (Limits API section)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Iterable, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Beeline AI base URL (same endpoint family used by chat completions / embeddings).
_BASE_URL = "https://api.ai.beeline.ru/api/v3"

# Cache TTL in seconds. Limits rarely change; 5 min keeps API call volume low.
_CACHE_TTL_SECONDS = 300

# model → (limit, fetched_at_epoch). Module-level cache shared across calls.
_limits_cache: Dict[str, Tuple[int, float]] = {}

# Guard so we only fire the startup background fetch once per process.
_startup_fetch_done: bool = False


async def get_concurrent_limit(
    model: str,
    api_key: Optional[str] = None,
    fallback: int = 1,
    *,
    force_refresh: bool = False,
) -> int:
    """Get the concurrent request limit for a model from Beeline AI API.

    Calls ``GET /api/v3/me/limits?model={model}`` and returns
    ``requestCapacity.limit``. Falls back to ``fallback`` if the API is
    unreachable or the response cannot be parsed. Cached for
    :data:`_CACHE_TTL_SECONDS` seconds per model.

    Args:
        model: Public Beeline AI model name (e.g. ``"glm-xlarge"``,
            ``"qwen-medium"``).
        api_key: Beeline AI API key. Defaults to ``settings.beeline_api_key``.
        fallback: Value returned if the API call fails. Callers should pass
            the corresponding ``Settings.*_max_concurrent`` value.
        force_refresh: If True, ignore cache and re-fetch.

    Returns:
        The concurrent request limit (int) for the model.
    """
    now = time.time()
    cached = _limits_cache.get(model)
    if cached is not None and not force_refresh and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    key = api_key if api_key is not None else settings.beeline_api_key
    if not key:
        logger.debug(
            "llm_limits: no api_key configured — using fallback %d for %s",
            fallback, model,
        )
        _limits_cache[model] = (fallback, now)
        return fallback

    try:
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(timeout=10.0, verify=ssl_context) as client:
            resp = await client.get(
                f"{_BASE_URL}/me/limits",
                params={"model": model},
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        capacity = data.get("requestCapacity") or {}
        raw_limit = capacity.get("limit", fallback)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            logger.warning(
                "llm_limits: requestCapacity.limit for %s is not an int (%r) — using fallback %d",
                model, raw_limit, fallback,
            )
            limit = fallback
        _limits_cache[model] = (limit, now)
        logger.info(
            "llm_limits: %s → %d concurrent slots (from API; used=%s remaining=%s)",
            model, limit,
            capacity.get("used"), capacity.get("remaining"),
        )
        return limit
    except Exception as exc:  # noqa: BLE001 — broad on purpose: this is a monitoring path
        logger.debug(
            "llm_limits: could not fetch limits for %s: %s (using fallback %d)",
            model, exc, fallback,
        )
        _limits_cache[model] = (fallback, now)
        return fallback


def get_cached_limit(model: str, fallback: int = 1) -> int:
    """Synchronous accessor for a cached limit (no API call).

    Returns ``fallback`` if the model has never been fetched or the cache
    entry has expired.
    """
    cached = _limits_cache.get(model)
    if cached is None:
        return fallback
    limit, fetched_at = cached
    if (time.time() - fetched_at) >= _CACHE_TTL_SECONDS:
        return fallback
    return limit


def clear_cache() -> None:
    """Clear the in-memory limits cache (used by tests)."""
    _limits_cache.clear()


async def fetch_and_log_all_limits(
    models: Optional[Iterable[str]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, int]:
    """Fetch limits for every configured model and log them.

    Compares each fetched limit with the configured fallback default and
    logs a ``WARNING`` if they differ — this is the **only** observable
    effect of this module at runtime (semaphores are not resized).

    Safe to call from :func:`app.main.lifespan` startup. Failures are
    swallowed (logged at DEBUG) so a limits-API outage never blocks app boot.

    Args:
        models: Iterable of model names to query. Defaults to the four
            configured Beeline AI family codes.
        api_key: Optional API key override.

    Returns:
        Mapping ``model → fetched_limit`` (or fallback value on failure).
    """
    global _startup_fetch_done
    _startup_fetch_done = True

    if models is None:
        models = (
            settings.beeline_default_model,
            settings.beeline_fast_model,
            settings.qwen35_model,
            settings.qwen36_model,
        )

    # Map model family code → configured fallback semaphore size.
    fallback_by_model = {
        settings.beeline_default_model: settings.glm_max_concurrent,
        settings.beeline_fast_model: settings.glm_max_concurrent,
        settings.qwen35_model: settings.qwen35_max_concurrent,
        settings.qwen36_model: settings.qwen36_max_concurrent,
    }

    results: Dict[str, int] = {}

    async def _one(model: str) -> None:
        fallback = fallback_by_model.get(model, 1)
        limit = await get_concurrent_limit(
            model, api_key=api_key, fallback=fallback, force_refresh=True,
        )
        results[model] = limit
        if limit != fallback:
            logger.warning(
                "llm_limits: configured semaphore size for %s (%d) differs from "
                "API limit (%d). Update config to match — semaphores are NOT "
                "resized at runtime.",
                model, fallback, limit,
            )

    # Run fetches concurrently — they're independent and we don't want a
    # single slow model to delay startup meaningfully.
    await asyncio.gather(*(_one(m) for m in models), return_exceptions=True)
    return results

"""Providers router — LLM provider listing and status.

Endpoints:
  GET /              — List all configured LLM providers
  GET /{provider_id}/status — Check single provider availability
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models import ProviderInfo
from app.services.llm import get_all_providers, get_provider

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", summary="List available LLM providers")
async def list_providers():
    """List all configured LLM providers with their availability status."""
    providers = get_all_providers()
    result: list[dict] = []

    for provider_id, provider in providers.items():
        # Check availability (with timeout)
        available = False
        try:
            available = await provider.is_available()
        except Exception as exc:
            logger.warning("Availability check failed for %s: %s", provider_id, exc)

        result.append({
            "id": provider_id,
            "name": provider.get_name(),
            "models": provider.get_models(),
            "configured": True,
            "available": available,
        })

    return {"providers": result}


@router.get("/{provider_id}/status", summary="Check provider status")
async def provider_status(provider_id: str):
    """Check availability of a specific LLM provider."""
    provider = get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown provider: '{provider_id}'. Supported: ollama, yandexgpt, gigachat, beeline",
        )

    available = False
    error: str | None = None
    try:
        available = await provider.is_available()
    except Exception as exc:
        error = str(exc)
        logger.warning("Availability check failed for %s: %s", provider_id, exc)

    return {
        "id": provider_id,
        "name": provider.get_name(),
        "models": provider.get_models(),
        "configured": True,
        "available": available,
        "error": error,
    }

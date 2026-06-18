"""Providers router — LLM provider listing and status.

TODO (coder stage):
  - Implement /providers endpoint: list available providers with status
  - Implement /providers/{provider}/status endpoint: check single provider
  - Add Ollama health check (GET /api/tags)
  - Add YandexGPT auth validation
  - Add GigaChat auth validation
"""

from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter()


@router.get("/", summary="List available LLM providers")
async def list_providers():
    """List all configured LLM providers with their availability status."""
    providers = []

    # Ollama (local)
    providers.append({
        "id": "ollama",
        "name": "Ollama (Local)",
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "configured": True,
        "available": False,  # TODO: health check
    })

    # YandexGPT
    providers.append({
        "id": "yandexgpt",
        "name": "YandexGPT",
        "model": settings.yandexgpt_model,
        "configured": bool(settings.yandexgpt_api_key),
        "available": bool(settings.yandexgpt_api_key),  # TODO: validate
    })

    # GigaChat
    providers.append({
        "id": "gigachat",
        "name": "GigaChat",
        "scope": settings.gigachat_scope,
        "configured": bool(settings.gigachat_auth_key),
        "available": bool(settings.gigachat_auth_key),  # TODO: validate
    })

    return {"providers": providers}


@router.get("/{provider_id}/status", summary="Check provider status")
async def provider_status(provider_id: str):
    """Check availability of a specific LLM provider."""
    # TODO: Implement actual health checks per provider
    raise HTTPException(status_code=501, detail=f"Provider status check not yet implemented for '{provider_id}'")

"""LLM client abstraction service.

Provides a unified interface for multiple LLM providers:
  - Ollama (local, REST API)
  - YandexGPT (cloud, REST API)
  - GigaChat (cloud, REST API)

TODO (coder stage):
  - Implement analyze_dialogue() for each provider
  - Implement Ollama client (POST /api/generate or /api/chat)
  - Implement YandexGPT client (POST completion endpoint)
  - Implement GigaChat client (POST chat/completions)
  - Build structured LLMResult from raw responses
  - Add retry/fallback logic
  - Add request timeout configuration
"""

from typing import Optional

from app.models import LLMResult


async def analyze_dialogue(
    dialogue_text: str,
    provider: str = "ollama",
    model: str | None = None,
) -> LLMResult:
    """Analyze a dialogue using the specified LLM provider.

    Args:
        dialogue_text: Full dialogue text for analysis
        provider: LLM provider id (ollama, yandexgpt, gigachat)
        model: Optional model override

    Returns:
        LLMResult with structured analysis

    Raises:
        ValueError: If provider is not supported
        ConnectionError: If LLM service is unavailable
    """
    # TODO: Route to provider-specific client
    raise NotImplementedError("LLM analysis not yet implemented")

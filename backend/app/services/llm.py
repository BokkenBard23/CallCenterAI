"""LLM client abstraction service.

Provides a unified async interface for multiple LLM providers:
  - Ollama (local, REST API at localhost:11434)
  - YandexGPT (cloud, REST API)
  - GigaChat (cloud, REST API)
  - Beeline AI (cloud, OpenAI-compatible REST API at api.ai.beeline.ru)

CRITICAL PROMPT requirements:
  - Must instruct model to IGNORE continuous block artifacts
  - Must instruct model to reconstruct dialogue as alternating short replicas
  - Must request JSON output format
  - 30-second timeout, 1 retry on failure
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.models import LLMResult

logger = logging.getLogger(__name__)

# Default timeout in seconds
_DEFAULT_TIMEOUT = 30.0

# Default max retries
_MAX_RETRIES = 1


# ═══════════════════════════════════════════════════════════
# System prompt — critical for dialogue restructuring
# ═══════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """Ты — аналитик колл-центра. Проанализируй следующий диалог между клиентом и сотрудником.

ВАЖНО — ИГНОРИРУЙ артефакты сплошного текста:
Группировка большими блоками является артефактом записи, а не реальной структурой диалога.
Восстанови истинный порядок коротких реплик клиента и сотрудника — они чередуются.

Ответь в формате JSON со следующей структурой:
{
  "topic": "Краткая тема диалога",
  "result": "Общий исход (решено/не решено/эскалация/частично)",
  "key_points": ["ключевой момент 1", "ключевой момент 2", ...],
  "client_sentiment": "positive/neutral/negative/mixed",
  "resolution": "resolved/unresolved/escalated/partial",
  "summary": "Краткое резюме диалога в 2-3 предложениях",
  "restructured_dialogue": "Восстановленный диалог в виде чередующихся коротких реплик:\\nКлиент: ...\\nСотрудник: ...\\nКлиент: ...\\n..."
}

Ответь ТОЛЬКО валидным JSON, без markdown-обёрток."""


# ═══════════════════════════════════════════════════════════
# Abstract provider interface
# ═══════════════════════════════════════════════════════════

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate text from the LLM.

        Args:
            prompt: User prompt text.
            model: Optional model override.

        Returns:
            Raw generated text.

        Raises:
            ConnectionError: If the LLM service is unavailable.
            TimeoutError: If the request times out.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is reachable.

        Returns:
            True if the provider is currently available.
        """

    @abstractmethod
    def get_name(self) -> str:
        """Return provider identifier."""

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model name."""

    @abstractmethod
    def get_models(self) -> List[str]:
        """Return list of available models."""


# ═══════════════════════════════════════════════════════════
# Ollama provider
# ═══════════════════════════════════════════════════════════

class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, base_url: str, default_model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def generate(self, prompt: str, model: Optional[str] = None) -> str:
        model_name = model or self._default_model
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": model_name,
            "prompt": f"{_SYSTEM_PROMPT}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": 0.3},
        }

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return data.get("response", "")
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < _MAX_RETRIES:
                    logger.warning("Ollama request failed (attempt %d): %s — retrying", attempt + 1, exc)
                    continue
                raise ConnectionError(f"Ollama unavailable after {_MAX_RETRIES + 1} attempts: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(f"Ollama HTTP error: {exc.response.status_code}") from exc

        return ""  # Unreachable but satisfies type checker

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    def get_name(self) -> str:
        return "ollama"

    def get_default_model(self) -> str:
        return self._default_model

    def get_models(self) -> List[str]:
        return [self._default_model]


# ═══════════════════════════════════════════════════════════
# YandexGPT provider
# ═══════════════════════════════════════════════════════════

class YandexGPTProvider(LLMProvider):
    """YandexGPT cloud LLM provider."""

    def __init__(self, api_key: str, folder_id: str, default_model: str) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._default_model = default_model
        self._base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    async def generate(self, prompt: str, model: Optional[str] = None) -> str:
        if not self._api_key or not self._folder_id:
            raise ConnectionError("YandexGPT not configured: missing api_key or folder_id")

        model_uri = f"gpt://{self._folder_id}/{model or self._default_model}"
        payload = {
            "modelUri": model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,
                "maxTokens": 2000,
            },
            "messages": [
                {"role": "system", "text": _SYSTEM_PROMPT},
                {"role": "user", "text": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                    response = await client.post(
                        self._base_url, json=payload, headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                    # YandexGPT returns: {"result": {"alternatives": [{"message": {"text": "..."}}]}}
                    alternatives = data.get("result", {}).get("alternatives", [])
                    if alternatives:
                        return alternatives[0].get("message", {}).get("text", "")
                    return ""
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < _MAX_RETRIES:
                    logger.warning("YandexGPT request failed (attempt %d): %s — retrying", attempt + 1, exc)
                    continue
                raise ConnectionError(f"YandexGPT unavailable after {_MAX_RETRIES + 1} attempts: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(f"YandexGPT HTTP error: {exc.response.status_code}") from exc

        return ""

    async def is_available(self) -> bool:
        return bool(self._api_key and self._folder_id)

    def get_name(self) -> str:
        return "yandexgpt"

    def get_default_model(self) -> str:
        return self._default_model

    def get_models(self) -> List[str]:
        return [self._default_model, "yandexgpt", "yandexgpt-lite", "yandexgpt-32k"]


# ═══════════════════════════════════════════════════════════
# GigaChat provider
# ═══════════════════════════════════════════════════════════

class GigaChatProvider(LLMProvider):
    """GigaChat cloud LLM provider."""

    def __init__(self, auth_key: str, scope: str = "GIGACHAT_API_PERS") -> None:
        self._auth_key = auth_key
        self._scope = scope
        self._base_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    async def generate(self, prompt: str, model: Optional[str] = None) -> str:
        if not self._auth_key:
            raise ConnectionError("GigaChat not configured: missing auth_key")

        payload = {
            "model": model or "GigaChat",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }
        headers = {
            "Authorization": f"Bearer {self._auth_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=_DEFAULT_TIMEOUT, verify=False
                ) as client:
                    response = await client.post(
                        self._base_url, json=payload, headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                    # GigaChat returns: {"choices": [{"message": {"content": "..."}}]}
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")
                    return ""
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < _MAX_RETRIES:
                    logger.warning("GigaChat request failed (attempt %d): %s — retrying", attempt + 1, exc)
                    continue
                raise ConnectionError(f"GigaChat unavailable after {_MAX_RETRIES + 1} attempts: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(f"GigaChat HTTP error: {exc.response.status_code}") from exc

        return ""

    async def is_available(self) -> bool:
        return bool(self._auth_key)

    def get_name(self) -> str:
        return "gigachat"

    def get_default_model(self) -> str:
        return "GigaChat"

    def get_models(self) -> List[str]:
        return ["GigaChat", "GigaChat-Pro", "GigaChat-Max"]


# ═══════════════════════════════════════════════════════════
# Beeline AI provider (OpenAI-compatible API)
# ═══════════════════════════════════════════════════════════

class BeelineProvider(LLMProvider):
    """Beeline AI cloud LLM provider.

    Uses the OpenAI-compatible chat completions API at api.ai.beeline.ru.
    Endpoints:
      - POST /api/v3/chat/completions — generate response
      - GET  /api/v3/models          — list available models
    """

    def __init__(self, api_key: str, default_model: str = "glm-5.1") -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._base_url = "https://api.ai.beeline.ru/api/v3"

    async def generate(self, prompt: str, model: Optional[str] = None) -> str:
        if not self._api_key:
            raise ConnectionError("Beeline AI not configured: missing api_key")

        model_name = model or self._default_model
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": model_name,
            "stream": False,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Use verify=False for corporate TLS compatibility (same as GigaChat)
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=_DEFAULT_TIMEOUT, verify=ssl_context
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    # OpenAI-compatible format:
                    # {"choices": [{"message": {"content": "..."}}]}
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")
                    return ""
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Beeline AI request failed (attempt %d): %s — retrying",
                        attempt + 1, exc,
                    )
                    continue
                raise ConnectionError(
                    f"Beeline AI unavailable after {_MAX_RETRIES + 1} attempts: {exc}"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(
                    f"Beeline AI HTTP error: {exc.response.status_code}"
                ) from exc

        return ""  # Unreachable but satisfies type checker

    async def is_available(self) -> bool:
        """Check availability by calling the models endpoint."""
        if not self._api_key:
            return False
        try:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            async with httpx.AsyncClient(timeout=5.0, verify=ssl_context) as client:
                response = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return response.status_code == 200
        except Exception:
            return False

    def get_name(self) -> str:
        return "beeline"

    def get_default_model(self) -> str:
        return self._default_model

    def get_models(self) -> List[str]:
        """Return default model list; actual models fetched dynamically via /v3/models."""
        return [self._default_model, "llm-medium-moe-instruct"]


# ═══════════════════════════════════════════════════════════
# Provider factory and main entry point
# ═══════════════════════════════════════════════════════════

_PROVIDERS: Dict[str, LLMProvider] = {}


def get_provider(provider_id: str) -> Optional[LLMProvider]:
    """Get or create an LLM provider by ID.

    Args:
        provider_id: Provider identifier (ollama, yandexgpt, gigachat).

    Returns:
        LLMProvider instance, or None if unknown provider.
    """
    if provider_id in _PROVIDERS:
        return _PROVIDERS[provider_id]

    if provider_id == "ollama":
        provider = OllamaProvider(
            base_url=settings.ollama_base_url,
            default_model=settings.ollama_model,
        )
    elif provider_id == "yandexgpt":
        provider = YandexGPTProvider(
            api_key=settings.yandexgpt_api_key,
            folder_id=settings.yandexgpt_folder_id,
            default_model=settings.yandexgpt_model,
        )
    elif provider_id == "gigachat":
        provider = GigaChatProvider(
            auth_key=settings.gigachat_auth_key,
            scope=settings.gigachat_scope,
        )
    elif provider_id == "beeline":
        provider = BeelineProvider(
            api_key=settings.beeline_api_key,
            default_model=settings.beeline_default_model,
        )
    else:
        return None

    _PROVIDERS[provider_id] = provider
    return provider


def get_all_providers() -> Dict[str, LLMProvider]:
    """Get all configured providers."""
    result: Dict[str, LLMProvider] = {}
    for pid in ("ollama", "yandexgpt", "gigachat", "beeline"):
        provider = get_provider(pid)
        if provider is not None:
            result[pid] = provider
    return result


async def analyze_dialogue(
    dialogue_text: str,
    provider_id: str = "ollama",
    model: Optional[str] = None,
) -> LLMResult:
    """Analyze a dialogue using the specified LLM provider.

    Sends the dialogue text with the critical restructuring prompt,
    parses the JSON response, and returns a structured LLMResult.

    Args:
        dialogue_text: Full dialogue text for analysis.
        provider_id: LLM provider id (ollama, yandexgpt, gigachat).
        model: Optional model override.

    Returns:
        LLMResult with structured analysis.

    Raises:
        ValueError: If provider is not supported.
        ConnectionError: If LLM service is unavailable.
    """
    provider = get_provider(provider_id)
    if provider is None:
        raise ValueError(f"Unknown LLM provider: '{provider_id}'. Supported: ollama, yandexgpt, gigachat, beeline")

    # Generate response
    raw_response = await provider.generate(dialogue_text, model=model)

    # Parse JSON response
    parsed = _parse_llm_response(raw_response)

    return LLMResult(
        summary=parsed.get("summary", ""),
        restructured_dialogue=parsed.get("restructured_dialogue", ""),
        topic=parsed.get("topic", ""),
        result=parsed.get("result", ""),
        key_points=parsed.get("key_points", []),
        client_sentiment=parsed.get("client_sentiment", ""),
        resolution=parsed.get("resolution", ""),
        provider=provider_id,
        model=model or provider.get_default_model(),
        raw_response=raw_response if settings.debug else None,
    )


def _parse_llm_response(raw: str) -> Dict[str, Any]:
    """Parse LLM JSON response with graceful error handling.

    Handles common LLM response issues:
    - JSON wrapped in markdown code blocks (```json ... ```)
    - Extra text before/after JSON
    - Invalid JSON (return partial results)

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed dictionary with whatever fields could be extracted.
    """
    if not raw:
        return {}

    # Strip markdown code block wrapper if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (``` markers)
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Try to parse as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object within the text
    import re
    json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # If all parsing fails, return raw text as summary
    logger.warning("Could not parse LLM response as JSON, using raw text as summary")
    return {"summary": raw[:500]}

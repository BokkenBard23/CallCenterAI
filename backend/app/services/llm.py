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
import re
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.models import (
    LLMResult,
    ClientSentiment,
    Resolution,
    _CLIENT_SENTIMENT_RU_MAP,
    _RESOLUTION_RU_MAP,
    ConflictAnalysisResult,
    EscalationPoint,
    ProfanityAnalysisResult,
    ProfanityInstance,
    SentimentAnalysisResult,
    TopicAnalysisResult,
    DetectedTopic,
    UtteranceSentiment,
    QualityCategory,
    QualityLevel,
    CategoryScore,
    QualityScoreResult,
    QUALITY_CATEGORY_LABELS,
    DialogueValidationResult,
    ResolutionClassification,
    ResolutionSentimentResult,
    SentimentTrajectoryPoint,
    ErrorCategory,
    ClassifiedError,
    ErrorClassificationResult,
    DomainType,
)

logger = logging.getLogger(__name__)

# Default timeout in seconds
_DEFAULT_TIMEOUT = 30.0

# Default max retries
_MAX_RETRIES = 3


# ═══════════════════════════════════════════════════════════
# Circuit Breaker for LLM providers
# ═══════════════════════════════════════════════════════════

class CircuitBreaker:
    """Circuit breaker for LLM providers.

    Three states: CLOSED (normal), OPEN (blocked), HALF-OPEN (probing).

    State transitions:
        CLOSED    → OPEN:      After N consecutive failures (failure_threshold)
        OPEN      → HALF-OPEN: After reset_timeout seconds (auto-reset)
        HALF-OPEN → CLOSED:    After one successful request
        HALF-OPEN → OPEN:      After one failure (probe failed)

    Follows the same pattern as FridaEmbeddingService circuit breaker
    in app.services.embedding, but as a reusable per-provider class.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
        provider_name: str = "unknown",
    ) -> None:
        """Initialize CircuitBreaker.

        Args:
            failure_threshold: Consecutive failures before opening circuit.
            reset_timeout: Seconds before auto-reset from OPEN to HALF-OPEN.
            provider_name: Provider name for logging.
        """
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._provider_name = provider_name
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state: str = "closed"  # closed | open | half-open

    @property
    def state(self) -> str:
        """Current circuit breaker state (with auto-transition to half-open)."""
        if self._state == "open" and self._last_failure_time is not None:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._reset_timeout:
                return "half-open"
        return self._state

    def can_execute(self) -> bool:
        """Check if a request can be executed.

        Returns:
            True if circuit breaker is closed or half-open (probe allowed).
        """
        current_state = self.state
        if current_state == "closed":
            return True
        if current_state == "half-open":
            return True
        return False

    def record_success(self) -> None:
        """Record a successful request — reset failure count and close circuit."""
        old_state = self._state
        self._failure_count = 0
        self._state = "closed"
        if old_state != "closed":
            logger.info(
                "Circuit breaker [%s]: %s → closed (success)",
                self._provider_name,
                old_state,
            )

    def record_failure(self) -> None:
        """Record a failed request — increment failure count and potentially open circuit."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == "half-open":
            self._state = "open"
            logger.warning(
                "Circuit breaker [%s]: half-open → open (probe failed)",
                self._provider_name,
            )
        elif self._failure_count >= self._failure_threshold:
            self._state = "open"
            logger.error(
                "Circuit breaker [%s]: closed → open after %d failures. "
                "Auto-reset in %.0f sec.",
                self._provider_name,
                self._failure_count,
                self._reset_timeout,
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "provider": self._provider_name,
            "state": self.state,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "reset_timeout": self._reset_timeout,
            "last_failure_time": self._last_failure_time,
        }


# Per-provider circuit breaker registry
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def _get_circuit_breaker(provider_id: str) -> CircuitBreaker:
    """Get or create circuit breaker for a provider.

    Args:
        provider_id: Provider identifier.

    Returns:
        CircuitBreaker instance for the provider.
    """
    if provider_id not in _circuit_breakers:
        _circuit_breakers[provider_id] = CircuitBreaker(
            failure_threshold=settings.llm_circuit_breaker_failures,
            reset_timeout=settings.llm_circuit_breaker_reset_seconds,
            provider_name=provider_id,
        )
    return _circuit_breakers[provider_id]


def get_circuit_breaker_stats() -> Dict[str, Dict[str, Any]]:
    """Get circuit breaker stats for all providers.

    Returns:
        Dictionary mapping provider_id to circuit breaker stats.
    """
    return {pid: cb.get_stats() for pid, cb in _circuit_breakers.items()}


def _get_fallback_order(primary_provider_id: str) -> List[str]:
    """Get ordered list of provider IDs for fallback chain.

    The requested provider comes first, then others in a stable order.

    Args:
        primary_provider_id: The initially requested provider.

    Returns:
        List of provider IDs starting with the primary, then others.
    """
    all_providers = ["ollama", "yandexgpt", "gigachat", "beeline"]

    if primary_provider_id in all_providers:
        order = [primary_provider_id]
        order.extend(p for p in all_providers if p != primary_provider_id)
        return order

    # Unknown provider — return all in default order
    return list(all_providers)


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
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate text from the LLM.

        Args:
            prompt: User prompt text.
            model: Optional model override.
            system_prompt: Optional system prompt override.
                When *None*, the provider uses its default system prompt.

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

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        model_name = model or self._default_model
        url = f"{self._base_url}/api/generate"
        effective_system = system_prompt if system_prompt is not None else _SYSTEM_PROMPT
        payload = {
            "model": model_name,
            "prompt": f"{effective_system}\n\n{prompt}",
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
                    await asyncio.sleep(2 ** attempt)
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

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not self._api_key or not self._folder_id:
            raise ConnectionError("YandexGPT not configured: missing api_key or folder_id")

        model_uri = f"gpt://{self._folder_id}/{model or self._default_model}"
        effective_system = system_prompt if system_prompt is not None else _SYSTEM_PROMPT
        payload = {
            "modelUri": model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,
                "maxTokens": 2000,
            },
            "messages": [
                {"role": "system", "text": effective_system},
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
                    await asyncio.sleep(2 ** attempt)
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

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not self._auth_key:
            raise ConnectionError("GigaChat not configured: missing auth_key")

        effective_system = system_prompt if system_prompt is not None else _SYSTEM_PROMPT
        payload = {
            "model": model or "GigaChat",
            "messages": [
                {"role": "system", "content": effective_system},
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
                    await asyncio.sleep(2 ** attempt)
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

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not self._api_key:
            raise ConnectionError("Beeline AI not configured: missing api_key")

        model_name = model or self._default_model
        url = f"{self._base_url}/chat/completions"
        effective_system = system_prompt if system_prompt is not None else _SYSTEM_PROMPT
        payload = {
            "model": model_name,
            "stream": False,
            "messages": [
                {"role": "system", "content": effective_system},
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
                    await asyncio.sleep(2 ** attempt)
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
# LLM response validation (IP-3.1)
# ═══════════════════════════════════════════════════════════

class FieldValidation(Dict[str, Any]):
    """Per-field validation record."""

    field: str
    received: Any
    fallback: Any
    reason: str


class ValidatedLLMResult(BaseModel if False else object):
    """Pydantic-validated LLM response with fallback metadata.

    Attributes:
        summary: Dialogue summary (str, safe default "").
        restructured_dialogue: Restructured dialogue text (str, safe default "").
        topic: Dialogue topic (str, safe default "").
        result: Overall result text (str, safe default "").
        key_points: Key discussion points (list[str], safe default []).
        client_sentiment: Validated sentiment (str, safe default "neutral").
        resolution: Validated resolution (str, safe default "unresolved").
        invalid_fields: Fields that failed validation and were replaced.
    """

    __slots__ = (
        "summary",
        "restructured_dialogue",
        "topic",
        "result",
        "key_points",
        "client_sentiment",
        "resolution",
        "invalid_fields",
    )

    def __init__(self, **kwargs: Any) -> None:
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


class LLMResultHandler:
    """Validate and parse raw LLM JSON responses.

    Workflow:
        1. Strip markdown wrappers (existing ``_parse_llm_response`` logic).
        2. Parse JSON.
        3. Validate ``client_sentiment`` and ``resolution`` against their
           enums, normalising Russian forms to English canonical values.
        4. On invalid field: log a WARNING with the field name, received
           value and the fallback used; substitute a safe default.
        5. Return a :class:`ValidatedLLMResult` with validation metadata.
    """

    # Safe defaults for every field
    _DEFAULTS: Dict[str, Any] = {
        "summary": "",
        "restructured_dialogue": "",
        "topic": "",
        "result": "",
        "key_points": [],
        "client_sentiment": ClientSentiment.neutral.value,
        "resolution": Resolution.unresolved.value,
    }

    # ---- public API ----

    def validate_and_parse(self, raw: str) -> ValidatedLLMResult:
        """Parse *raw* LLM output and return a validated result.

        Args:
            raw: Raw text returned by the LLM.

        Returns:
            ValidatedLLMResult with all fields populated (defaults where
            the LLM output was missing or invalid) and ``invalid_fields``
            listing any substitutions made.
        """
        parsed = self._extract_json(raw)
        if parsed is None:
            logger.warning(
                "LLMResultHandler: failed to extract JSON from response, "
                "using all defaults"
            )
            return ValidatedLLMResult(
                **self._DEFAULTS,
                invalid_fields=[
                    {
                        "field": "raw_response",
                        "received": raw[:200] if raw else "",
                        "fallback": "all_defaults",
                        "reason": "json_parse_failed",
                    }
                ],
            )

        invalid_fields: List[Dict[str, Any]] = []

        # Validate enum fields
        cs = self._validate_enum_field(
            parsed,
            field_name="client_sentiment",
            enum_cls=ClientSentiment,
            ru_map=_CLIENT_SENTIMENT_RU_MAP,
            default=self._DEFAULTS["client_sentiment"],
            invalid_fields=invalid_fields,
        )
        res = self._validate_enum_field(
            parsed,
            field_name="resolution",
            enum_cls=Resolution,
            ru_map=_RESOLUTION_RU_MAP,
            default=self._DEFAULTS["resolution"],
            invalid_fields=invalid_fields,
        )

        # Build result with validated values and safe defaults
        result = ValidatedLLMResult(
            summary=self._str_field(parsed, "summary", invalid_fields),
            restructured_dialogue=self._str_field(
                parsed, "restructured_dialogue", invalid_fields
            ),
            topic=self._str_field(parsed, "topic", invalid_fields),
            result=self._str_field(parsed, "result", invalid_fields),
            key_points=self._list_field(parsed, "key_points", invalid_fields),
            client_sentiment=cs,
            resolution=res,
            invalid_fields=invalid_fields,
        )
        return result

    # ---- private helpers ----

    def _extract_json(self, raw: str) -> Optional[Dict[str, Any]]:
        """Extract JSON dict from raw LLM text.

        Reuses the same markdown-stripping and regex-fallback logic as the
        original ``_parse_llm_response``.
        """
        if not raw:
            return None

        text = raw.strip()

        # Strip markdown code block wrapper
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Direct JSON parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Regex fallback: find first JSON object
        json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return None

    def _validate_enum_field(
        self,
        parsed: Dict[str, Any],
        field_name: str,
        enum_cls: type,
        ru_map: Dict[str, str],
        default: str,
        invalid_fields: List[Dict[str, Any]],
    ) -> str:
        """Validate and normalise an enum field.

        Returns the canonical English value or *default* with a logged
        warning on invalid input.
        """
        raw_value = parsed.get(field_name)
        if raw_value is None:
            logger.warning(
                "LLMResultHandler: missing field '%s', "
                "using default '%s'",
                field_name,
                default,
            )
            invalid_fields.append(
                {
                    "field": field_name,
                    "received": None,
                    "fallback": default,
                    "reason": "missing",
                }
            )
            return default

        if not isinstance(raw_value, str):
            logger.warning(
                "LLMResultHandler: field '%s' has non-string value "
                "%r, using default '%s'",
                field_name,
                raw_value,
                default,
            )
            invalid_fields.append(
                {
                    "field": field_name,
                    "received": repr(raw_value),
                    "fallback": default,
                    "reason": "wrong_type",
                }
            )
            return default

        normalised = raw_value.strip().lower()

        # Check Russian mapping first
        if normalised in ru_map:
            return ru_map[normalised]

        # Check canonical English enum values
        for member in enum_cls:
            if normalised == member.value:
                return member.value

        logger.warning(
            "LLMResultHandler: invalid value '%s' for field '%s', "
            "using default '%s'",
            raw_value,
            field_name,
            default,
        )
        invalid_fields.append(
            {
                "field": field_name,
                "received": raw_value,
                "fallback": default,
                "reason": "invalid_value",
            }
        )
        return default

    @staticmethod
    def _str_field(
        parsed: Dict[str, Any],
        field_name: str,
        invalid_fields: List[Dict[str, Any]],
    ) -> str:
        """Extract a string field with safe default ``""``."""
        value = parsed.get(field_name, "")
        if not isinstance(value, str):
            logger.warning(
                "LLMResultHandler: field '%s' is not string (%s), "
                "defaulting to empty string",
                field_name,
                type(value).__name__,
            )
            invalid_fields.append(
                {
                    "field": field_name,
                    "received": repr(value),
                    "fallback": "",
                    "reason": "wrong_type",
                }
            )
            return ""
        return value

    @staticmethod
    def _list_field(
        parsed: Dict[str, Any],
        field_name: str,
        invalid_fields: List[Dict[str, Any]],
    ) -> List[str]:
        """Extract a list-of-str field with safe default ``[]``."""
        value = parsed.get(field_name, [])
        if not isinstance(value, list):
            logger.warning(
                "LLMResultHandler: field '%s' is not list (%s), "
                "defaulting to empty list",
                field_name,
                type(value).__name__,
            )
            invalid_fields.append(
                {
                    "field": field_name,
                    "received": repr(value),
                    "fallback": [],
                    "reason": "wrong_type",
                }
            )
            return []
        # Ensure all items are strings
        result: List[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            else:
                result.append(str(item))
        return result


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
    """Analyze a dialogue with fallback chain across LLM providers.

    Sends the dialogue text with the critical restructuring prompt,
    parses the JSON response, and returns a structured LLMResult.

    Fallback order:
      1. Try requested provider
      2. Try other available providers (in order: ollama, yandexgpt, gigachat, beeline)
      3. If all fail, return LLMResult with empty summary and provider="none"

    Circuit breaker:
      Each provider has its own circuit breaker. If a provider's circuit
      breaker is open, it is skipped. After reset_timeout seconds, the
      circuit breaker transitions to half-open and allows one probe request.

    Args:
        dialogue_text: Full dialogue text for analysis.
        provider_id: LLM provider id (ollama, yandexgpt, gigachat, beeline).
        model: Optional model override.

    Returns:
        LLMResult with structured analysis. If all providers fail,
        returns a degraded result with empty summary and provider="none".
    """
    # Build ordered list of providers to try
    provider_order = _get_fallback_order(provider_id)

    last_error: Optional[Exception] = None

    for pid in provider_order:
        cb = _get_circuit_breaker(pid)

        # Check circuit breaker
        if not cb.can_execute():
            logger.info(
                "Circuit breaker [%s] is %s — skipping",
                pid,
                cb.state,
            )
            continue

        provider = get_provider(pid)
        if provider is None:
            continue

        # Try to generate
        try:
            raw_response = await provider.generate(dialogue_text, model=model)

            # Validate and parse using LLMResultHandler
            handler = LLMResultHandler()
            validated = handler.validate_and_parse(raw_response)

            # Record success in circuit breaker
            cb.record_success()

            return LLMResult(
                summary=validated.summary,
                restructured_dialogue=validated.restructured_dialogue,
                topic=validated.topic,
                result=validated.result,
                key_points=validated.key_points,
                client_sentiment=validated.client_sentiment,
                resolution=validated.resolution,
                provider=pid,
                model=model or provider.get_default_model(),
                raw_response=raw_response if settings.debug else None,
            )

        except (ConnectionError, TimeoutError) as exc:
            # Only record circuit breaker failure for transient errors,
            # not for "not configured" errors (which are permanent)
            error_msg = str(exc).lower()
            if "not configured" not in error_msg:
                cb.record_failure()
            last_error = exc
            logger.warning(
                "Provider %s failed: %s — trying next provider",
                pid,
                exc,
            )
            continue
        except Exception as exc:
            cb.record_failure()
            last_error = exc
            logger.error(
                "Provider %s unexpected error: %s",
                pid,
                exc,
            )
            continue

    # All providers failed — return degraded result
    logger.error(
        "All LLM providers failed. Last error: %s",
        last_error,
    )
    return LLMResult(
        summary="",
        restructured_dialogue="",
        topic="",
        result="",
        key_points=[],
        client_sentiment=ClientSentiment.neutral.value,
        resolution=Resolution.unresolved.value,
        provider="none",
        model="",
        raw_response=None,
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


# ═══════════════════════════════════════════════════════════
# Shared JSON extraction for new analysis types
# ═══════════════════════════════════════════════════════════


def _extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """Extract the outermost JSON object from raw LLM text.

    Handles markdown wrappers, extra text, and nested JSON.
    Unlike the simple regex in ``_parse_llm_response``, this correctly
    matches nested ``{…}`` by brace-counting.

    Args:
        raw: Raw text returned by the LLM.

    Returns:
        Parsed dict, or *None* if no JSON object could be extracted.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strip markdown code block wrapper
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Direct parse attempt
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Brace-counting extraction: find the first '{' and match to its '}'
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    result = json.loads(candidate)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    break

    return None


def _safe_parse_model(raw: str, model_class: type, **extra: Any) -> Any:
    """Parse raw LLM JSON into a Pydantic model with fallback defaults.

    On parse/validation failure, returns an instance populated with
    Pydantic model defaults plus any ``extra`` keyword arguments
    (typically ``provider`` and ``model``).

    Args:
        raw: Raw LLM response text.
        model_class: Pydantic model class to validate against.
        **extra: Extra keyword arguments merged into the model
            (e.g. ``provider="ollama"``, ``model="llama3.2"``).

    Returns:
        Validated model instance or a default instance on failure.
    """
    parsed = _extract_json_object(raw)
    if parsed is not None:
        try:
            merged = {**parsed, **extra}
            return model_class.model_validate(merged)
        except Exception:
            logger.warning(
                "LLM analysis: validation failed for %s, using defaults",
                model_class.__name__,
            )
    return model_class(**extra)


# ═══════════════════════════════════════════════════════════
# Analysis prompts (IP-3.2 – IP-3.5)
# ═══════════════════════════════════════════════════════════

# Common preamble — shared across all analysis prompts.
_ARTIFACT_IGNORE_INSTRUCTION = """\
ВАЖНО — ИГНОРИРУЙ артефакты сплошного текста:
Группировка большими блоками является артефактом записи, а не реальной структурой диалога.
Восстанови истинный порядок коротких реплик клиента и сотрудника — они чередуются."""

_JSON_ONLY_INSTRUCTION = "\n\nОтветь ТОЛЬКО валидным JSON, без markdown-обёрток."


# --- IP-3.2: Sentiment Analysis ---

_SENTIMENT_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Определи настроение каждой реплики в диалоге.

{_ARTIFACT_IGNORE_INSTRUCTION}

Для каждой реплики определи:
- sentiment: positive / neutral / negative / mixed
- confidence: число от 0.0 до 1.0

Также определи общее настроение диалога и его траекторию (улучшается / ухудшается / стабильное / волатильное).

Ответь в формате JSON:
{{
  "utterances": [
    {{"turn_index": 0, "speaker": "Клиент", "sentiment": "neutral", "confidence": 0.8, "text_snippet": "первые слова реплики..."}},
    {{"turn_index": 1, "speaker": "Сотрудник", "sentiment": "positive", "confidence": 0.9, "text_snippet": "первые слова реплики..."}}
  ],
  "overall_sentiment": "positive/neutral/negative/mixed",
  "sentiment_trajectory": "improving/declining/stable/volatile"
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- IP-3.3: Conflict Detection ---

_CONFLICT_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Обнаружь конфликты, агрессию и эскалацию в диалоге между клиентом и сотрудником.

{_ARTIFACT_IGNORE_INSTRUCTION}

Определи:
- Есть ли конфликт в диалоге
- Уровень конфликта: none / low / medium / high / critical
- Точки эскалации — моменты, где конфликт обостряется
- Попытки деэскалации со стороны сотрудника

Ответь в формате JSON:
{{
  "has_conflict": true/false,
  "conflict_level": "none/low/medium/high/critical",
  "escalation_points": [
    {{"turn_index": 3, "speaker": "Клиент", "trigger": "описание триггера", "level": "medium"}}
  ],
  "de_escalation_attempts": 0,
  "justification": "Обоснование оценки конфликта"
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- IP-3.4: Profanity Detection ---

_PROFANITY_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Обнаружь ненормативную лексику, оскорбления и грубость в диалоге.

{_ARTIFACT_IGNORE_INSTRUCTION}

Для каждого обнаруженного случая укажи:
- category: obscenity (нецензурная лексика) / insult (оскорбление) / slur (уничижительное выражение) / slang (грубый сленг)
- severity: low / medium / high

Ответь в формате JSON:
{{
  "has_profanity": true/false,
  "instances": [
    {{"turn_index": 2, "speaker": "Клиент", "category": "insult", "severity": "medium", "context": "контекст употребления"}}
  ],
  "total_count": 0
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- IP-3.5: Topic Detection ---

_TOPIC_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Определи темы, которые обсуждаются в диалоге между клиентом и сотрудником.

{_ARTIFACT_IGNORE_INSTRUCTION}

Для каждой темы укажи:
- name: краткое название темы
- confidence: число от 0.0 до 1.0
- key_phrases: ключевые фразы, связанные с темой
- turn_indices: номера реплик, где обсуждается эта тема

Ответь в формате JSON:
{{
  "topics": [
    {{"name": "Название темы", "confidence": 0.9, "key_phrases": ["фраза 1", "фраза 2"], "turn_indices": [0, 1, 3]}}
  ],
  "primary_topic": "Главная тема диалога",
  "topic_count": 2
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- IP-4.1: Quality Scoring (12 categories) ---

# Build the category list section of the prompt dynamically from the enum
# so that adding a new QualityCategory member automatically updates the prompt.
_QUALITY_CATEGORY_LIST = "\n".join(
    f"{i}. {cat.value} — {QUALITY_CATEGORY_LABELS[cat.value]}"
    for i, cat in enumerate(QualityCategory, 1)
)

_QUALITY_SYSTEM_PROMPT = f"""\
Ты — эксперт по оценке качества диалогов колл-центра. Оцени диалог по 12 категориям.

{_ARTIFACT_IGNORE_INSTRUCTION}

Категории:
{_QUALITY_CATEGORY_LIST}

Для каждой категории:
- level: high / medium / low
- score: число от 0.0 до 1.0 (low ≈ 0.33, medium ≈ 0.66, high ≈ 1.0)
- justification: 1-2 предложения, почему присвоен этот уровень

Также определи:
- strengths: список категорий с высоким уровнем (high)
- weaknesses: список категорий с низким уровнем (low)
- recommendations: 1-3 конкретных рекомендации по улучшению

Ответь в формате JSON:
{{
  "categories": [
    {{"category": "communication_skills", "level": "high", "score": 0.9, "justification": "Обоснование..."}},
    ...все 12 категорий...
  ],
  "strengths": ["communication_skills", "professionalism"],
  "weaknesses": ["efficiency"],
  "recommendations": ["Рекомендация 1", "Рекомендация 2"]
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- ID-12: Dialogue Validation ---

_VALIDATION_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Определи, является ли предоставленный текст осмысленным диалогом между клиентом и сотрудником.

{_ARTIFACT_IGNORE_INSTRUCTION}

Критерии валидного диалога:
- Есть минимум 2 реплики от разных спикеров (клиент и сотрудник)
- Реплики связаны по смыслу (не случайный набор фраз)
- Текст на русском языке (или преимущественно на русском)

Ответь в формате JSON:
{{
  "is_valid_dialogue": true/false,
  "confidence": 0.9,
  "reason": "Обоснование: почему это валидный или невалидный диалог",
  "language_detected": "ru"
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- ID-3: Auto-Resolution + Sentiment Trajectory ---

_RESOLUTION_SENTIMENT_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Определи результативность диалога и отслеживай траекторию настроения клиента.

{_ARTIFACT_IGNORE_INSTRUCTION}

1. Классифицируй результат диалога:
   - resolved: проблема клиента полностью решена
   - unresolved: проблема клиента не решена
   - escalated: диалог передан на эскалацию (старший специалист, руководитель)
   - redirected: клиент перенаправлен в другой отдел/канал

2. Для каждой реплики определи:
   - sentiment: positive / neutral / negative
   - cumulative_sentiment: среднее настроение от -1.0 (очень негативный) до 1.0 (очень позитивный) с начала диалога до текущей реплики включительно

3. Определи общую траекторию настроения:
   - improving: настроение клиента улучшается к концу диалога
   - declining: настроение клиента ухудшается к концу диалога
   - stable: настроение клиента стабильно на протяжении диалога
   - volatile: настроение клиента резко колеблется

Ответь в формате JSON:
{{
  "session_id": "",
  "resolution": "resolved/unresolved/escalated/redirected",
  "resolution_confidence": 0.9,
  "resolution_reason": "Обоснование классификации результата",
  "sentiment_trajectory": [
    {{"turn_index": 0, "speaker": "Клиент", "sentiment": "negative", "cumulative_sentiment": -0.5}},
    {{"turn_index": 1, "speaker": "Сотрудник", "sentiment": "positive", "cumulative_sentiment": -0.2}}
  ],
  "sentiment_start": "negative",
  "sentiment_end": "neutral",
  "trajectory_direction": "improving"
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- IP-5.2: Error Classifier ---

_ERROR_CLASSIFIER_SYSTEM_PROMPT = f"""\
Ты — аналитик колл-центра. Обнаружь и классифицируй ошибки в диалоге между клиентом и сотрудником.

{_ARTIFACT_IGNORE_INSTRUCTION}

Категории ошибок:
- communication_error: некорректная коммуникация (невежливость, непонятные объяснения, игнорирование вопросов)
- procedural_error: нарушение процедур (неправильный порядок действий, пропуск обязательных шагов)
- information_error: неверная или неполная информация (ошибочные данные, устаревшие тарифы, неверные инструкции)
- service_error: ошибки обслуживания (долгое ожидание, перевод не туда, технические сбои)
- compliance_violation: нарушение нормативных требований (разглашение персональных данных, нарушение регламента)
- empathy_failure: отсутствие эмпатии (равнодушие к проблеме клиента, формальные ответы без сочувствия)
- response_delay: существенная задержка ответа (долгие паузы, отсутствие реакции на запрос клиента)

Для каждой обнаруженной ошибки укажи:
- severity: low / medium / high
- description: описание ошибки
- suggested_fix: рекомендация по исправлению

Ответь в формате JSON:
{{
  "session_id": "",
  "has_errors": true/false,
  "errors": [
    {{"turn_index": 2, "speaker": "Сотрудник", "category": "communication_error", "severity": "medium", "description": "Сотрудник перебил клиента", "suggested_fix": "Дать клиенту закончить мысль"}}
  ],
  "total_errors": 1,
  "errors_by_category": {{"communication_error": 1}}
}}
{_JSON_ONLY_INSTRUCTION}"""


# --- IP-6.1: Domain-Specific Analysis Context ---

_DOMAIN_PROMPT_ADDITIONS: Dict[str, str] = {
    DomainType.insurance.value: """\

ДОМЕН: СТРАХОВАНИЕ
Дополнительные критерии оценки:
- Обработка страховых случаев: корректность приёма заявления, полнота консультации по покрытию
- Объяснение условий полиса: ясность формулировок, предупреждение об исключениях
- Проверка покрытия: точная проверка страхового покрытия по номеру полиса
- Соблюдение страхового регламента: идентификация клиента, проверка полномочий, соблюдение сроков уведомления
- Внимание к исключениям и ограничениям покрытия""",

    DomainType.banking.value: """\

ДОМЕН: БАНКИНГ
Дополнительные критерии оценки:
- Безопасность счёта: верификация личности, защита конфиденциальной информации, предупреждение мошенничества
- Подтверждение транзакций: корректная проверка операций, информация о комиссиях и лимитах
- Регуляторное соответствие: соблюдение требований ЦБ, антиотмывочного законодательства (115-ФЗ)
- Обнаружение мошенничества: подозрительные операции, несанкционированный доступ, социальная инженерия
- Защита персональных данных: минимизация запрашиваемой информации, безопасное хранение""",

    DomainType.healthcare.value: """\

ДОМЕН: ЗДРАВООХРАНЕНИЕ
Дополнительные критерии оценки:
- Конфиденциальность пациента: соблюдение врачебной тайны, защита медицинских данных
- Точность медицинской терминологии: корректное использование терминов, ясные объяснения для пациента
- Запись на приём: корректная запись, проверка доступности специалистов, напоминания
- Процедура направления: правильное оформление направлений, информирование о порядке прохождения
- Этические нормы: уважительное отношение, информированное согласие, право на отказ""",

    DomainType.telecom.value: """\

ДОМЕН: ТЕЛЕКОММУНИКАЦИИ
Дополнительные критерии оценки:
- Активация услуг: корректное подключение, проверка совместимости, информирование об условиях
- Диагностика проблем: пошаговая проверка, исключение типичных неисправностей, эскалация при необходимости
- Биллинговые споры: проверка начислений, объяснение тарификации, корректировка при ошибках
- Условия контракта: точная информация о тарифах, сроках, штрафах за досрочное расторжение
- Качество связи: диагностика, сроки устранения, компенсация за недоступность""",
}


def get_domain_prompt_addition(domain: str) -> str:
    """Get domain-specific prompt addition for analysis.

    Args:
        domain: Domain type value (e.g. 'insurance', 'banking').

    Returns:
        Domain-specific prompt text to prepend to analysis prompts.
        Empty string for 'general' or unknown domains.
    """
    return _DOMAIN_PROMPT_ADDITIONS.get(domain, "")


# ═══════════════════════════════════════════════════════════
# Generic analysis runner with circuit breaker + fallback
# ═══════════════════════════════════════════════════════════


async def _run_llm_analysis(
    dialogue_text: str,
    system_prompt: str,
    model_class: type,
    default_instance: Any,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> Any:
    """Run an LLM analysis with circuit breaker and fallback chain.

    Follows the same pattern as :func:`analyze_dialogue`:
    try requested provider → try others → return default on total failure.

    Args:
        dialogue_text: Full dialogue text for analysis.
        system_prompt: Analysis-specific system prompt.
        model_class: Pydantic model class for response validation.
        default_instance: Default instance to return on total failure.
        provider_id: Primary LLM provider id.
        model: Optional model override.

    Returns:
        Validated model instance or ``default_instance`` on total failure.
    """
    provider_order = _get_fallback_order(provider_id)
    last_error: Optional[Exception] = None

    for pid in provider_order:
        cb = _get_circuit_breaker(pid)

        if not cb.can_execute():
            logger.info(
                "Circuit breaker [%s] is %s — skipping", pid, cb.state,
            )
            continue

        provider = get_provider(pid)
        if provider is None:
            continue

        try:
            raw_response = await provider.generate(
                dialogue_text, model=model, system_prompt=system_prompt,
            )
            result = _safe_parse_model(
                raw_response,
                model_class,
                provider=pid,
                model=model or provider.get_default_model(),
            )
            cb.record_success()
            return result

        except (ConnectionError, TimeoutError) as exc:
            error_msg = str(exc).lower()
            if "not configured" not in error_msg:
                cb.record_failure()
            last_error = exc
            logger.warning(
                "Provider %s failed: %s — trying next provider", pid, exc,
            )
            continue
        except Exception as exc:
            cb.record_failure()
            last_error = exc
            logger.error(
                "Provider %s unexpected error: %s", pid, exc,
            )
            continue

    # All providers failed
    logger.error(
        "All LLM providers failed for %s. Last error: %s",
        model_class.__name__,
        last_error,
    )
    return default_instance


# ═══════════════════════════════════════════════════════════
# Public analysis functions (IP-3.2 – IP-3.5)
# ═══════════════════════════════════════════════════════════


async def analyze_sentiment(
    dialogue_text: str,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> SentimentAnalysisResult:
    """Analyze per-utterance sentiment of a dialogue (IP-3.2).

    Args:
        dialogue_text: Full dialogue text for analysis.
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.

    Returns:
        SentimentAnalysisResult with per-utterance sentiment,
        overall sentiment, and trajectory. Falls back to neutral
        defaults on total LLM failure.
    """
    default = SentimentAnalysisResult(
        utterances=[],
        overall_sentiment="neutral",
        sentiment_trajectory="stable",
        provider="none",
        model="",
    )
    return await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=_SENTIMENT_SYSTEM_PROMPT,
        model_class=SentimentAnalysisResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )


async def analyze_conflict(
    dialogue_text: str,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> ConflictAnalysisResult:
    """Detect conflict and aggression in a dialogue (IP-3.3).

    Args:
        dialogue_text: Full dialogue text for analysis.
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.

    Returns:
        ConflictAnalysisResult with conflict level, escalation
        points, and de-escalation count. Falls back to
        no-conflict defaults on total LLM failure.
    """
    default = ConflictAnalysisResult(
        has_conflict=False,
        conflict_level="none",
        escalation_points=[],
        de_escalation_attempts=0,
        justification="",
        provider="none",
        model="",
    )
    return await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=_CONFLICT_SYSTEM_PROMPT,
        model_class=ConflictAnalysisResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )


async def analyze_profanity(
    dialogue_text: str,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> ProfanityAnalysisResult:
    """Detect profanity and offensive language in a dialogue (IP-3.4).

    Args:
        dialogue_text: Full dialogue text for analysis.
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.

    Returns:
        ProfanityAnalysisResult with instances, count, and
        severity. Falls back to no-profanity defaults on total
        LLM failure.
    """
    default = ProfanityAnalysisResult(
        has_profanity=False,
        instances=[],
        total_count=0,
        provider="none",
        model="",
    )
    return await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=_PROFANITY_SYSTEM_PROMPT,
        model_class=ProfanityAnalysisResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )


async def analyze_topic(
    dialogue_text: str,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> TopicAnalysisResult:
    """Detect topics discussed in a dialogue (IP-3.5).

    Args:
        dialogue_text: Full dialogue text for analysis.
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.

    Returns:
        TopicAnalysisResult with detected topics, primary topic,
        and topic count. Falls back to empty defaults on total
        LLM failure.
    """
    default = TopicAnalysisResult(
        topics=[],
        primary_topic="",
        topic_count=0,
        provider="none",
        model="",
    )
    return await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=_TOPIC_SYSTEM_PROMPT,
        model_class=TopicAnalysisResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )


def _compute_quality_derived_fields(result: QualityScoreResult) -> QualityScoreResult:
    """Compute overall_score, overall_level, strengths, weaknesses from categories.

    This is called after LLM parsing so that derived fields are always
    consistent with the actual category scores, even if the LLM omits them.

    Args:
        result: Parsed QualityScoreResult (may have empty derived fields).

    Returns:
        QualityScoreResult with computed overall_score, overall_level,
        strengths, and weaknesses.
    """
    if not result.categories:
        return result

    # overall_score = average of all category scores
    overall_score = sum(c.score for c in result.categories) / len(result.categories)
    overall_score = round(overall_score, 4)

    # overall_level derived from overall_score
    if overall_score > 0.75:
        overall_level = QualityLevel.high
    elif overall_score >= 0.5:
        overall_level = QualityLevel.medium
    else:
        overall_level = QualityLevel.low

    # strengths = categories with high level
    strengths = [c.category.value for c in result.categories if c.level == QualityLevel.high]

    # weaknesses = categories with low level
    weaknesses = [c.category.value for c in result.categories if c.level == QualityLevel.low]

    # Keep LLM-provided recommendations if present
    return QualityScoreResult(
        session_id=result.session_id,
        categories=result.categories,
        overall_score=overall_score,
        overall_level=overall_level,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=result.recommendations,
        provider=result.provider,
        model=result.model,
    )


def _build_quality_fallback_result(session_id: str) -> QualityScoreResult:
    """Build a fallback QualityScoreResult with all categories at medium.

    Used when all LLM providers fail.

    Args:
        session_id: Session identifier.

    Returns:
        QualityScoreResult with 12 categories all at medium level,
        no justifications, empty recommendations.
    """
    categories = [
        CategoryScore(
            category=cat,
            level=QualityLevel.medium,
            score=0.66,
            justification="",
        )
        for cat in QualityCategory
    ]
    result = QualityScoreResult(
        session_id=session_id,
        categories=categories,
        provider="none",
        model="",
    )
    return _compute_quality_derived_fields(result)


async def analyze_quality(
    dialogue_text: str,
    session_id: str,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> QualityScoreResult:
    """Analyse dialogue quality across 12 categories (IP-4.1).

    Uses the same circuit-breaker + fallback-chain pattern as the
    other analysis functions.  On total LLM failure returns a result
    with all categories at *medium* and empty justifications.

    After successful LLM parsing, derived fields (overall_score,
    overall_level, strengths, weaknesses) are recomputed from the
    actual category scores so they are always consistent.

    Args:
        dialogue_text: Full dialogue text for analysis.
        session_id: Session identifier (included in result).
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.

    Returns:
        QualityScoreResult with per-category scores, overall
        score/level, strengths, weaknesses, and recommendations.
    """
    default = _build_quality_fallback_result(session_id)
    raw_result = await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=_QUALITY_SYSTEM_PROMPT,
        model_class=QualityScoreResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )

    # Ensure session_id is set (LLM may not return it)
    if raw_result.session_id != session_id:
        raw_result = QualityScoreResult(
            session_id=session_id,
            categories=raw_result.categories,
            overall_score=raw_result.overall_score,
            overall_level=raw_result.overall_level,
            strengths=raw_result.strengths,
            weaknesses=raw_result.weaknesses,
            recommendations=raw_result.recommendations,
            provider=raw_result.provider,
            model=raw_result.model,
        )

    # Recompute derived fields from actual category scores
    return _compute_quality_derived_fields(raw_result)


async def analyze_dialogue_validation(
    dialogue_text: str,
    provider_id: str = "beeline",
    model: Optional[str] = None,
) -> DialogueValidationResult:
    """Validate whether a text is a meaningful client-operator dialogue (ID-12).

    Uses the same circuit-breaker + fallback-chain pattern as the
    other analysis functions.  On total LLM failure returns a result
    with is_valid_dialogue=False, confidence=0.0, and an explanatory
    reason.

    Args:
        dialogue_text: Full dialogue text for validation.
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.

    Returns:
        DialogueValidationResult with is_valid_dialogue flag,
        confidence, reason, and language_detected.
    """
    default = DialogueValidationResult(
        is_valid_dialogue=False,
        confidence=0.0,
        reason="LLM unavailable: all providers failed",
        language_detected="ru",
        provider="none",
        model="",
    )
    return await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=_VALIDATION_SYSTEM_PROMPT,
        model_class=DialogueValidationResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )


# ═══════════════════════════════════════════════════════════
# ID-3: Auto-Resolution + Sentiment Trajectory
# ═══════════════════════════════════════════════════════════


async def analyze_resolution_sentiment(
    dialogue_text: str,
    session_id: str = "",
    provider_id: str = "beeline",
    model: Optional[str] = None,
    domain: str = "general",
) -> ResolutionSentimentResult:
    """Classify dialogue resolution and track sentiment trajectory (ID-3).

    This is DIFFERENT from analyze_sentiment (IP-3.2, which does
    per-utterance sentiment only). ID-3 adds automatic resolution
    classification (resolved/unresolved/escalated/redirected) and
    cumulative sentiment trajectory tracking.

    Args:
        dialogue_text: Full dialogue text for analysis.
        session_id: Session identifier (included in result).
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.
        domain: Domain type for domain-specific prompt addition (default: general).

    Returns:
        ResolutionSentimentResult with resolution classification,
        per-utterance sentiment trajectory, and trajectory direction.
        Falls back to unresolved/neutral defaults on total LLM failure.
    """
    default = ResolutionSentimentResult(
        session_id=session_id,
        resolution=ResolutionClassification.unresolved,
        resolution_confidence=0.0,
        resolution_reason="LLM unavailable: all providers failed",
        sentiment_trajectory=[],
        sentiment_start="neutral",
        sentiment_end="neutral",
        trajectory_direction="stable",
        provider="none",
        model="",
    )

    # Build system prompt with optional domain addition
    system_prompt = _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
    domain_addition = get_domain_prompt_addition(domain)
    if domain_addition:
        system_prompt = domain_addition + "\n\n" + system_prompt

    raw_result = await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=system_prompt,
        model_class=ResolutionSentimentResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )

    # Ensure session_id is set (LLM may not return it)
    if raw_result.session_id != session_id:
        raw_result = ResolutionSentimentResult(
            session_id=session_id,
            resolution=raw_result.resolution,
            resolution_confidence=raw_result.resolution_confidence,
            resolution_reason=raw_result.resolution_reason,
            sentiment_trajectory=raw_result.sentiment_trajectory,
            sentiment_start=raw_result.sentiment_start,
            sentiment_end=raw_result.sentiment_end,
            trajectory_direction=raw_result.trajectory_direction,
            provider=raw_result.provider,
            model=raw_result.model,
        )

    return raw_result


# ═══════════════════════════════════════════════════════════
# IP-5.2: Error Classifier
# ═══════════════════════════════════════════════════════════


async def analyze_errors(
    dialogue_text: str,
    session_id: str = "",
    provider_id: str = "beeline",
    model: Optional[str] = None,
    domain: str = "general",
) -> ErrorClassificationResult:
    """Classify errors in a dialogue (IP-5.2).

    Identifies and categorises dialogue errors into 7 categories:
    communication_error, procedural_error, information_error,
    service_error, compliance_violation, empathy_failure, response_delay.

    Args:
        dialogue_text: Full dialogue text for analysis.
        session_id: Session identifier (included in result).
        provider_id: LLM provider id (default: beeline).
        model: Optional model override.
        domain: Domain type for domain-specific prompt addition (default: general).

    Returns:
        ErrorClassificationResult with classified errors, total count,
        and per-category breakdown. Falls back to no-errors defaults
        on total LLM failure.
    """
    default = ErrorClassificationResult(
        session_id=session_id,
        has_errors=False,
        errors=[],
        total_errors=0,
        errors_by_category={},
        provider="none",
        model="",
    )

    # Build system prompt with optional domain addition
    system_prompt = _ERROR_CLASSIFIER_SYSTEM_PROMPT
    domain_addition = get_domain_prompt_addition(domain)
    if domain_addition:
        system_prompt = domain_addition + "\n\n" + system_prompt

    raw_result = await _run_llm_analysis(
        dialogue_text=dialogue_text,
        system_prompt=system_prompt,
        model_class=ErrorClassificationResult,
        default_instance=default,
        provider_id=provider_id,
        model=model,
    )

    # Ensure session_id is set (LLM may not return it)
    if raw_result.session_id != session_id:
        raw_result = ErrorClassificationResult(
            session_id=session_id,
            has_errors=raw_result.has_errors,
            errors=raw_result.errors,
            total_errors=raw_result.total_errors,
            errors_by_category=raw_result.errors_by_category,
            provider=raw_result.provider,
            model=raw_result.model,
        )

    return raw_result


# ═══════════════════════════════════════════════════════════
# IP-3.6: LLM Orchestrator — sequential analysis with progress
# ═══════════════════════════════════════════════════════════

from datetime import datetime, timezone

from app.models import AnalysisAnnotation, ProgressInfo


class LLMOrchestrator:
    """Run all LLM analyses sequentially with progress tracking and
    graceful degradation (IP-3.6).

    Each step is independent: failure of one does NOT block the others.
    Failed steps produce safe default results and are recorded in
    ``ProgressInfo.error_steps``. The overall result
    (:class:`AnalysisAnnotation`) is always valid, though it may be
    partial.

    Usage::

        orchestrator = LLMOrchestrator()
        annotation = await orchestrator.run_all_analyses(
            dialogue_text="...",
            session_id="abc",
            provider_id="beeline",
        )
    """

    # Step name → module-level function name (resolved dynamically)
    _STEP_FUNCTION_NAMES: Dict[str, str] = {
        "sentiment": "analyze_sentiment",
        "conflict": "analyze_conflict",
        "profanity": "analyze_profanity",
        "topic": "analyze_topic",
    }

    # Step name → AnalysisAnnotation field name
    _STEP_RESULT_FIELDS: Dict[str, str] = {
        "sentiment": "sentiment",
        "conflict": "conflict",
        "profanity": "profanity",
        "topic": "topic",
    }

    def __init__(
        self,
        steps: Optional[List[str]] = None,
    ) -> None:
        """Initialize orchestrator with configurable step order.

        Args:
            steps: Ordered list of analysis step names.
                Defaults to ``settings.llm_orchestrator_steps``.
                Pass an empty list to run no analysis steps.
        """
        self._steps = steps if steps is not None else list(settings.llm_orchestrator_steps)

    @property
    def steps(self) -> List[str]:
        """Configured analysis steps."""
        return list(self._steps)

    def _get_step_function(self, step_name: str):
        """Resolve an analysis function by step name at call time.

        Dynamic lookup ensures that ``unittest.mock.patch`` on the
        module-level function name works correctly in tests.
        """
        func_name = self._STEP_FUNCTION_NAMES.get(step_name)
        if func_name is None:
            return None
        return globals().get(func_name)

    async def run_all_analyses(
        self,
        dialogue_text: str,
        session_id: str,
        provider_id: str = "beeline",
        include_summary: bool = False,
        domain: str = "general",
    ) -> AnalysisAnnotation:
        """Run all configured LLM analyses sequentially.

        Args:
            dialogue_text: Full dialogue text for analysis.
            session_id: Session identifier.
            provider_id: LLM provider id (default: beeline).
            include_summary: If True, also run ``analyze_dialogue()``
                and include the summary in the result.
            domain: Domain type for domain-specific prompt additions
                (IP-6.1). Default: "general".

        Returns:
            :class:`AnalysisAnnotation` with individual results,
            progress info, domain, and metadata.
        """
        completed: List[str] = []
        error_steps: List[str] = []
        remaining = list(self._steps)
        results: Dict[str, Any] = {}

        # Track the first successful provider for annotation metadata
        first_provider: str = "none"
        first_model: str = ""

        for step_name in self._steps:
            remaining.remove(step_name)

            func = self._get_step_function(step_name)
            if func is None:
                logger.warning(
                    "Unknown analysis step '%s' — skipping", step_name,
                )
                error_steps.append(step_name)
                continue

            try:
                result = await func(
                    dialogue_text=dialogue_text,
                    provider_id=provider_id,
                )
                results[step_name] = result
                completed.append(step_name)

                # Capture first successful provider/model
                if first_provider == "none" and hasattr(result, "provider"):
                    result_provider = getattr(result, "provider", "none")
                    if result_provider != "none":
                        first_provider = result_provider
                        first_model = getattr(result, "model", "")

            except Exception as exc:
                logger.error(
                    "Orchestrator step '%s' failed: %s — graceful degradation",
                    step_name,
                    exc,
                )
                error_steps.append(step_name)

        # Optional: run summary analysis
        summary_result: Optional[LLMResult] = None
        if include_summary:
            try:
                summary_result = await analyze_dialogue(
                    dialogue_text=dialogue_text,
                    provider_id=provider_id,
                )
                # If summary succeeded, use its provider if we don't have one yet
                if first_provider == "none" and summary_result.provider != "none":
                    first_provider = summary_result.provider
                    first_model = summary_result.model
            except Exception as exc:
                logger.error(
                    "Orchestrator summary step failed: %s — graceful degradation",
                    exc,
                )

        # Build progress info
        # Determine current_step based on state
        if error_steps and not completed:
            current_step = "done"  # All failed but we're "done"
        elif remaining:
            current_step = remaining[0]
        else:
            current_step = "done"

        progress = ProgressInfo(
            current_step=current_step,
            completed_steps=completed,
            remaining_steps=remaining,
            total_steps=len(self._steps),
            error_steps=error_steps,
        )

        # Build annotation
        annotation_kwargs: Dict[str, Any] = {
            "session_id": session_id,
            "progress": progress,
            "domain": domain,
            "provider": first_provider,
            "model": first_model,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "analysis_source": "orchestrator",
        }

        # Map results to annotation fields
        for step_name, field_name in self._STEP_RESULT_FIELDS.items():
            annotation_kwargs[field_name] = results.get(step_name)

        if include_summary:
            annotation_kwargs["summary"] = summary_result

        return AnalysisAnnotation(**annotation_kwargs)

"""LLM-powered dictionary analysis and phrase suggestions.

Ported from LexiCore AI v3 frontend (``index.html``) with bug fixes:

- Prompts moved from frontend strings to backend constants (no more
  shipping prompt text in the JS bundle).
- Stratified sampling is reused across endpoints via
  :func:`app.services.dict_utils.stratified_sample`.
- LLM output is validated with Pydantic models via
  :func:`app.services.llm_utils.safe_parse_model` — no more ad-hoc
  ``JSON.parse`` + regex fallback in the frontend.
- Uses our :class:`app.services.llm.LLMProvider` abstraction
  (Beeline / YandexGPT / GigaChat / Ollama) with the standard fallback
  chain.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models import DictionaryCondition, DictionaryNode
from app.services.dict_utils import _gather_conditions, stratified_sample
from app.services.llm import (
    LLMProvider,
    _get_fallback_order,
    _resolve_system_prompt,
    get_provider,
)
from app.services.llm_utils import (
    extract_json_array,
    safe_parse_model,
)
from app.services.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Prompts (ported from LexiCore AI v3 frontend, adapted for backend)
#
# NOTE: Prompts are mirrored in backend/app/prompts/dictionary.yaml
# (managed by prompt_manager). Inline constants below are kept as
# backward-compat fallback — see _resolve_system_prompt().
# ═══════════════════════════════════════════════════════════


ANALYSIS_SYSTEM_PROMPT = """\
Ты — аналитик колл-центра. Перед тобой список фраз из поискового словаря
SmartLogger. Этот словарь используется для автоматической разметки звонков
клиентов и сотрудников.

Задача:
1. Кратко опиши (2–3 предложения), что именно этот словарь ищет в звонках —
   общую тему, интент, продуктовую область.
2. Приведи 3–5 примеров фраз из списка (буквально, копируя из исходного
   текста), которые иллюстрируют тему словаря.
3. Дай 2–4 рекомендации по улучшению словаря: какие фразы стоит добавить,
   какие пересекаются, какие сужают поиск слишком сильно.

Ответь в формате JSON:
{
  "summary": "Краткое описание словаря",
  "examples": ["пример 1", "пример 2", "пример 3"],
  "recommendations": ["рекомендация 1", "рекомендация 2"]
}
Ответь ТОЛЬКО валидным JSON, без markdown-обёрток."""


SUGGEST_SYSTEM_PROMPT = """\
Ты — аналитик колл-центра. Перед тобой список фраз из поискового словаря
SmartLogger. Твоя задача — предложить дополнительные фразы, которые стоит
добавить в словарь для расширения покрытия темы.

Требования к предложениям:
- Фразы должны быть на русском языке.
- Каждая фраза — короткая (1–4 слова).
- Каждая фраза сопровождается каналом (ANY | CLIENT | OPERATOR) и
  WordDistance (обычно 2; 0 — для точных совпадений без промежуточных слов).
- Не повторяй фразы, уже присутствующие в словаре.

Ответь в формате JSON-массива:
[
  {"phrase": "новая фраза", "channel": "CLIENT", "distance": 2},
  {"phrase": "ещё фраза", "channel": "ANY", "distance": 2}
]
Ответь ТОЛЬКО валидным JSON-массивом, без markdown-обёрток."""


# ═══════════════════════════════════════════════════════════
# Result models
# ═══════════════════════════════════════════════════════════


class DictionarySuggestion(BaseModel):
    """A single phrase suggestion from the LLM."""

    phrase: str
    channel: str = "ANY"  # ANY | OPERATOR | CLIENT
    distance: int = 2


class DictionaryAnalysisResult(BaseModel):
    """Result of LLM dictionary analysis."""

    summary: str = ""
    examples: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    raw_response: str = ""


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _collect_phrases(node: DictionaryNode) -> List[str]:
    """Collect all phrase texts from a DictionaryNode tree."""
    conditions: List[DictionaryCondition] = _gather_conditions(node)
    return [c.text for c in conditions if c.text]


async def _call_llm_with_fallback(
    user_prompt: str,
    system_prompt: str,
    provider_id: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4000,
) -> Optional[str]:
    """Call LLM with the standard fallback chain.

    Returns the raw response string, or ``None`` if all providers fail.
    """
    primary = provider_id or "coding"
    order = _get_fallback_order(primary)

    last_error: Optional[Exception] = None
    for pid in order:
        provider: Optional[LLMProvider] = get_provider(pid)
        if provider is None:
            continue
        try:
            raw = await provider.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
            )
            if raw:
                return raw
            logger.warning("Provider %s returned empty response", pid)
        except (ConnectionError, TimeoutError) as exc:
            last_error = exc
            logger.warning(
                "Provider %s failed during dictionary AI: %s — trying next",
                pid, exc,
            )
            continue
        except Exception as exc:
            last_error = exc
            logger.error(
                "Provider %s unexpected error during dictionary AI: %s",
                pid, exc,
            )
            continue

    if last_error is not None:
        logger.error(
            "All LLM providers failed for dictionary AI: %s", last_error,
        )
    return None


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════


async def analyze_dictionary(
    node: DictionaryNode,
    provider_id: Optional[str] = None,
) -> DictionaryAnalysisResult:
    """Anse dictionary via LLM.

    Returns summary, examples, and recommendations. Uses stratified
    sampling when phrases exceed 200 (LexiCore parity).

    Args:
        node: Dictionary node to analyse.
        provider_id: Primary LLM provider id (default: 'coding' — coding-medium
            model optimised for structured output, Task 4 2026-07-15).

    Returns:
        :class:`DictionaryAnalysisResult` with summary, examples,
        recommendations, and the raw LLM response. On total LLM failure
        returns an empty result with ``raw_response=""``.
    """
    phrases = _collect_phrases(node)
    if not phrases:
        return DictionaryAnalysisResult(
            summary="Словарь не содержит поисковых фраз.",
            examples=[],
            recommendations=[],
            raw_response="",
        )

    sampled, was_sampled = stratified_sample(phrases)
    user_prompt = (
        f"Словарь содержит {len(phrases)} фраз"
        + (f" (в анализ включено {len(sampled)} — стратифицированная выборка)"
           if was_sampled else "")
        + ".\n\nСписок фраз:\n"
        + "\n".join(f"- {p}" for p in sampled)
    )

    raw = await _call_llm_with_fallback(
        user_prompt=user_prompt,
        system_prompt=_resolve_system_prompt("dict_analysis", ANALYSIS_SYSTEM_PROMPT),
        provider_id=provider_id,
    )
    if raw is None:
        return DictionaryAnalysisResult(
            summary="LLM недоступен: все провайдеры не ответили.",
            examples=[],
            recommendations=[],
            raw_response="",
        )

    result = safe_parse_model(
        raw,
        DictionaryAnalysisResult,
        default=DictionaryAnalysisResult(
            summary="",
            examples=[],
            recommendations=[],
            raw_response=raw,
        ),
    )
    # Preserve raw_response for debugging even when validation succeeded.
    if not result.raw_response:
        result = result.model_copy(update={"raw_response": raw})
    return result


async def suggest_phrases(
    node: DictionaryNode,
    provider_id: Optional[str] = None,
    count: int = 25,
) -> List[DictionarySuggestion]:
    """Generate phrase suggestions via LLM.

    Returns a Pydantic-validated list. Uses stratified sampling with
    hard_cap=150 (LexiCore parity).

    Args:
        node: Dictionary node to suggest phrases for.
        provider_id: Primary LLM provider id (default: 'coding' — coding-medium
            model optimised for structured output, Task 4 2026-07-15).
        count: Desired number of suggestions.

    Returns:
        List of :class:`DictionarySuggestion`. Empty on total LLM failure
        or when the LLM output cannot be parsed.
    """
    phrases = _collect_phrases(node)
    if not phrases:
        return []

    sampled, _ = stratified_sample(phrases, hard_cap=150)
    user_prompt = (
        f"Существующие фразы словаря ({len(sampled)} показано):\n"
        + "\n".join(f"- {p}" for p in sampled)
        + f"\n\nПредложи {count} новых фраз, расширяющих покрытие темы."
    )

    raw = await _call_llm_with_fallback(
        user_prompt=user_prompt,
        system_prompt=_resolve_system_prompt("dict_suggest", SUGGEST_SYSTEM_PROMPT),
        provider_id=provider_id,
    )
    if raw is None:
        return []

    items = extract_json_array(raw)
    suggestions: List[DictionarySuggestion] = []
    existing = {p.strip().lower() for p in phrases}
    for item in items:
        try:
            suggestion = DictionarySuggestion.model_validate(item)
        except Exception as exc:
            logger.debug("Skipping invalid suggestion %r: %s", item, exc)
            continue
        if suggestion.phrase.strip().lower() in existing:
            continue
        suggestions.append(suggestion)
    return suggestions

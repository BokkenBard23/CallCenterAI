"""Tests for new LLM providers (Qwen, BeelineFast) and per-provider semaphores.

Covers:
  - BeelineFastProvider / Qwen35Provider / Qwen36Provider / Qwen36FastProvider instantiation & defaults
  - Per-provider asyncio.Semaphore lazy creation inside an event loop
  - Shared GLM-family semaphore between BeelineProvider and BeelineFastProvider
  - Parallel execution respects semaphore limits (concurrency capped)
  - Circuit breaker isolation per provider id
  - get_all_providers registers all 8 providers
  - Task → model preference routing hint
"""

from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.services import llm as llm_mod
from app.services.llm import (
    BeelineAIProvider,
    BeelineProvider,
    BeelineFastProvider,
    Qwen35Provider,
    Qwen36Provider,
    Qwen36FastProvider,
    QwenProvider,
    _get_glm_semaphore,
    _TASK_MODEL_PREFERENCE,
    _resolve_preferred_provider,
    _get_circuit_breaker,
    _circuit_breakers,
    get_all_providers,
    get_provider,
    LLMProvider,
)


# ═══════════════════════════════════════════════════════════
# 1. Provider instantiation & defaults
# ═══════════════════════════════════════════════════════════


class TestProviderInstantiation:
    """New providers instantiate with correct defaults."""

    def test_beeline_provider_defaults(self) -> None:
        p = BeelineProvider(api_key="key")
        assert p.get_name() == "beeline"
        assert p.get_default_model() == "glm-xlarge"
        assert "glm-xlarge" in p.get_models()

    def test_beeline_fast_provider_defaults(self) -> None:
        p = BeelineFastProvider(api_key="key")
        assert p.get_name() == "beeline_fast"
        assert p.get_default_model() == "glm-xlarge-fast"

    def test_qwen35_provider_defaults(self) -> None:
        p = Qwen35Provider(api_key="key")
        assert p.get_name() == "qwen35"
        assert p.get_default_model() == "qwen-medium"

    def test_qwen36_provider_defaults(self) -> None:
        p = Qwen36Provider(api_key="key")
        assert p.get_name() == "qwen36"
        assert p.get_default_model() == "qwen-medium-dense"

    def test_qwen36_fast_provider_defaults(self) -> None:
        p = Qwen36FastProvider(api_key="key")
        assert p.get_name() == "qwen36_fast"
        assert p.get_default_model() == "qwen-medium-dense-fast"

    def test_qwen_provider_is_beeline_ai_subclass(self) -> None:
        """QwenProvider reuses BeelineAIProvider HTTP logic."""
        assert issubclass(QwenProvider, BeelineAIProvider)
        assert issubclass(BeelineProvider, BeelineAIProvider)
        assert issubclass(BeelineFastProvider, BeelineAIProvider)

    def test_custom_model_override(self) -> None:
        p = Qwen36Provider(api_key="key", default_model="custom-qwen")
        assert p.get_default_model() == "custom-qwen"


# ═══════════════════════════════════════════════════════════
# 2. Semaphore behaviour
# ═══════════════════════════════════════════════════════════


class TestSemaphoreBehaviour:
    """Per-provider asyncio.Semaphore lazy creation and limits."""

    @pytest.mark.asyncio
    async def test_semaphore_created_lazily(self) -> None:
        """Semaphore is None until _get_semaphore is called inside a loop."""
        p = Qwen35Provider(api_key="key")
        assert p._semaphore is None
        sem = p._get_semaphore()
        assert sem is not None
        assert p._semaphore is sem  # cached

    @pytest.mark.asyncio
    async def test_glm_semaphore_is_shared_singleton(self) -> None:
        """BeelineProvider and BeelineFastProvider share ONE GLM semaphore."""
        global _glm_semaphore_backup
        # Reset the module-level singleton for a clean test
        original = llm_mod._glm_semaphore
        try:
            llm_mod._glm_semaphore = None
            beeline = BeelineProvider(api_key="key")
            fast = BeelineFastProvider(api_key="key")
            sem1 = beeline._get_semaphore()
            sem2 = fast._get_semaphore()
            assert sem1 is sem2, "GLM providers must share a single semaphore"
        finally:
            llm_mod._glm_semaphore = original

    @pytest.mark.asyncio
    async def test_qwen_semaphores_are_independent(self) -> None:
        """Qwen35 and Qwen36 have their own semaphores (not shared)."""
        q35 = Qwen35Provider(api_key="key")
        q36 = Qwen36Provider(api_key="key")
        assert q35._get_semaphore() is not q36._get_semaphore()

    @pytest.mark.asyncio
    async def test_parallel_calls_respect_semaphore_limit(self) -> None:
        """3 concurrent Qwen36 calls with semaphore=1 run at most 1 at a time."""
        # Provider with max_concurrent=1 to make the cap observable
        provider = QwenProvider(api_key="key", default_model="qwen-medium-preview", max_concurrent=1, provider_id="test_qwen")

        concurrent = 0
        max_concurrent_seen = 0
        lock = asyncio.Lock()

        async def _track_generate(self, *args, **kwargs):
            nonlocal concurrent, max_concurrent_seen
            async with lock:
                concurrent += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1
            return "ok"

        with patch.object(BeelineAIProvider, "_do_generate", _track_generate):
            tasks = [provider.generate("prompt") for _ in range(5)]
            await asyncio.gather(*tasks)

        assert max_concurrent_seen == 1, f"expected max 1 concurrent, got {max_concurrent_seen}"

    @pytest.mark.asyncio
    async def test_semaphore_allows_up_to_limit(self) -> None:
        """With max_concurrent=3, up to 3 calls run concurrently."""
        provider = QwenProvider(api_key="key", default_model="qwen-medium-preview", max_concurrent=3, provider_id="test_qwen3")

        concurrent = 0
        max_concurrent_seen = 0
        lock = asyncio.Lock()

        async def _track_generate(self, *args, **kwargs):
            nonlocal concurrent, max_concurrent_seen
            async with lock:
                concurrent += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1
            return "ok"

        with patch.object(BeelineAIProvider, "_do_generate", _track_generate):
            tasks = [provider.generate("prompt") for _ in range(6)]
            await asyncio.gather(*tasks)

        assert max_concurrent_seen == 3, f"expected max 3 concurrent, got {max_concurrent_seen}"


# ═══════════════════════════════════════════════════════════
# 3. Registry & factory
# ═══════════════════════════════════════════════════════════


class TestProviderRegistry:
    """get_provider / get_all_providers register new providers."""

    def setup_method(self) -> None:
        llm_mod._PROVIDERS.clear()
        _circuit_breakers.clear()

    def test_all_seven_providers_registered(self) -> None:
        providers = get_all_providers()
        expected = {
            "qwen36", "qwen36_fast", "beeline", "beeline_fast",
            "qwen35", "ollama", "yandexgpt", "gigachat",
        }
        assert set(providers.keys()) == expected

    def test_get_provider_beeline_fast(self) -> None:
        p = get_provider("beeline_fast")
        assert p is not None
        assert p.get_name() == "beeline_fast"

    def test_get_provider_qwen35(self) -> None:
        p = get_provider("qwen35")
        assert p is not None
        assert p.get_default_model() == "qwen-medium"

    def test_get_provider_qwen36(self) -> None:
        p = get_provider("qwen36")
        assert p is not None
        assert p.get_default_model() == "qwen-medium-dense"

    def test_get_provider_qwen36_fast(self) -> None:
        p = get_provider("qwen36_fast")
        assert p is not None
        assert p.get_name() == "qwen36_fast"
        assert p.get_default_model() == "qwen-medium-dense-fast"

    def test_get_provider_unknown_returns_none(self) -> None:
        assert get_provider("nonexistent") is None

    def test_provider_cached(self) -> None:
        """get_provider returns the same instance on repeated calls."""
        p1 = get_provider("qwen36")
        p2 = get_provider("qwen36")
        assert p1 is p2


# ═══════════════════════════════════════════════════════════
# 4. Circuit breaker isolation
# ═══════════════════════════════════════════════════════════


class TestCircuitBreakerIsolation:
    """Each provider id has an independent circuit breaker."""

    def setup_method(self) -> None:
        _circuit_breakers.clear()

    def test_each_provider_has_own_circuit_breaker(self) -> None:
        for pid in ["beeline", "beeline_fast", "qwen35", "qwen36", "qwen36_fast"]:
            cb = _get_circuit_breaker(pid)
            assert cb._provider_name == pid

    def test_opening_one_does_not_affect_others(self) -> None:
        cb_beeline = _get_circuit_breaker("beeline")
        for _ in range(5):
            cb_beeline.record_failure()
        assert cb_beeline.state == "open"

        cb_qwen = _get_circuit_breaker("qwen36")
        assert cb_qwen.state == "closed"
        assert cb_qwen.can_execute() is True


# ═══════════════════════════════════════════════════════════
# 5. Task → model preference routing
# ═══════════════════════════════════════════════════════════


class TestTaskModelPreference:
    """Soft task → provider routing hint."""

    def test_preference_table_covers_all_steps(self) -> None:
        for step in ["sentiment", "conflict", "profanity", "topic", "summary", "quality"]:
            assert step in _TASK_MODEL_PREFERENCE
            assert len(_TASK_MODEL_PREFERENCE[step]) > 0

    def test_sentiment_prefers_fast(self) -> None:
        """Short classifications prefer qwen36_fast (qwen-medium-dense-fast)."""
        assert _TASK_MODEL_PREFERENCE["sentiment"][0] == "qwen36_fast"

    def test_summary_prefers_qwen36(self) -> None:
        """Long generations prefer qwen36 (qwen-medium-dense, PRIMARY)."""
        assert _TASK_MODEL_PREFERENCE["summary"][0] == "qwen36"

    def test_resolve_preferred_provider_returns_first_available(self) -> None:
        _circuit_breakers.clear()
        result = _resolve_preferred_provider("sentiment")
        assert result == "qwen36_fast"

    def test_resolve_skips_open_circuit_breakers(self) -> None:
        """If qwen36_fast CB is open, fall back to next preference."""
        _circuit_breakers.clear()
        cb = _get_circuit_breaker("qwen36_fast")
        for _ in range(5):
            cb.record_failure()
        assert cb.state == "open"
        result = _resolve_preferred_provider("sentiment")
        # Next in preference list is qwen36
        assert result == "qwen36"

    def test_resolve_returns_none_if_all_open(self) -> None:
        _circuit_breakers.clear()
        for pid in _TASK_MODEL_PREFERENCE["sentiment"]:
            cb = _get_circuit_breaker(pid)
            for _ in range(5):
                cb.record_failure()
        result = _resolve_preferred_provider("sentiment")
        assert result is None


# ═══════════════════════════════════════════════════════════
# 6. Config
# ═══════════════════════════════════════════════════════════


class TestProviderConfig:
    """New config fields have correct defaults."""

    def test_default_models(self) -> None:
        s = Settings()
        assert s.beeline_default_model == "glm-xlarge"
        assert s.beeline_fast_model == "glm-xlarge-fast"
        assert s.qwen35_model == "qwen-medium"
        assert s.qwen36_model == "qwen-medium-dense"
        assert s.qwen36_fast_model == "qwen-medium-dense-fast"

    def test_concurrency_limits(self) -> None:
        s = Settings()
        assert s.glm_max_concurrent == 2
        assert s.qwen35_max_concurrent == 3
        assert s.qwen36_max_concurrent == 6

    def test_total_parallel_budget_is_17(self) -> None:
        s = Settings()
        # 2 (GLM, shared) + 3 (Qwen3.5) + 6 (qwen-medium-dense) + 6 (qwen-medium-dense-fast) = 17
        # NOTE: qwen36 and qwen36_fast have INDEPENDENT 6-slot semaphores (per Beeline AI /me/limits).
        total = s.glm_max_concurrent + s.qwen35_max_concurrent + s.qwen36_max_concurrent + s.qwen36_max_concurrent
        assert total == 17

    def test_orchestrator_parallel_default_true(self) -> None:
        s = Settings()
        assert s.llm_orchestrator_parallel is True

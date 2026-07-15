"""Tests for graceful degradation: circuit breakers, fallback chains, source indicators.

Covers:
  - CircuitBreaker state transitions (closed → open → half-open → closed)
  - CircuitBreaker failure threshold and reset timeout
  - CircuitBreaker stats
  - LLM provider fallback chain (primary → next → degraded)
  - All-providers-down → LLMResult(provider="none")
  - "Not configured" errors don't count against circuit breaker
  - SearchResult.search_source field
  - Config fields (llm_circuit_breaker_failures, etc.)
  - get_circuit_breaker_stats()
  - Analysis router status with degraded LLM result
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.models import (
    AnalysisResponse,
    LLMResult,
    SearchResult,
    DictMatch,
    TextSegment,
)
from app.services.llm import (
    CircuitBreaker,
    _get_circuit_breaker,
    _get_fallback_order,
    _circuit_breakers,
    get_circuit_breaker_stats,
    analyze_dialogue,
    get_provider,
)


# ═══════════════════════════════════════════════════════════
# CircuitBreaker unit tests
# ═══════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Test CircuitBreaker state machine."""

    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0, provider_name="test")
        assert cb.state == "closed"
        assert cb.can_execute() is True

    def test_record_success_keeps_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0, provider_name="test")
        cb.record_success()
        assert cb.state == "closed"
        assert cb.can_execute() is True

    def test_closed_to_open_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0, provider_name="test")
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    def test_failure_count_resets_on_success(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0, provider_name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_success()
        assert cb.state == "closed"
        # Failure count should be reset, so we need 3 more failures
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"

    def test_open_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1, provider_name="test")
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

        # Wait for reset timeout
        time.sleep(0.15)
        assert cb.state == "half-open"
        assert cb.can_execute() is True

    def test_half_open_to_closed_on_success(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1, provider_name="test")
        cb.record_failure()
        assert cb.state == "open"

        time.sleep(0.15)
        assert cb.state == "half-open"

        cb.record_success()
        assert cb.state == "closed"
        assert cb.can_execute() is True

    def test_half_open_to_open_on_failure(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1, provider_name="test")
        cb.record_failure()
        assert cb.state == "open"

        time.sleep(0.15)
        assert cb.state == "half-open"

        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    def test_open_blocks_execution(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60.0, provider_name="test")
        cb.record_failure()
        assert cb.can_execute() is False

    def test_custom_failure_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=5, reset_timeout=60.0, provider_name="test")
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"

    def test_get_stats(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0, provider_name="test_provider")
        stats = cb.get_stats()
        assert stats["provider"] == "test_provider"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 3
        assert stats["reset_timeout"] == 60.0
        assert stats["last_failure_time"] is None

        cb.record_failure()
        stats = cb.get_stats()
        assert stats["failure_count"] == 1
        assert stats["last_failure_time"] is not None

    def test_state_property_auto_transitions_to_half_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1, provider_name="test")
        cb.record_failure()
        assert cb.state == "open"

        # Before timeout — still open
        assert cb.can_execute() is False

        # After timeout — auto-transitions to half-open
        time.sleep(0.15)
        assert cb.state == "half-open"
        assert cb.can_execute() is True

    def test_multiple_success_resets_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0, provider_name="test")
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb._failure_count == 0
        assert cb.state == "closed"


# ═══════════════════════════════════════════════════════════
# Circuit breaker registry tests
# ═══════════════════════════════════════════════════════════


class TestCircuitBreakerRegistry:
    """Test per-provider circuit breaker registry."""

    def setup_method(self) -> None:
        """Clear circuit breaker registry before each test."""
        _circuit_breakers.clear()

    def test_get_circuit_breaker_creates_new(self) -> None:
        cb = _get_circuit_breaker("ollama")
        assert isinstance(cb, CircuitBreaker)
        assert cb._provider_name == "ollama"

    def test_get_circuit_breaker_returns_existing(self) -> None:
        cb1 = _get_circuit_breaker("ollama")
        cb2 = _get_circuit_breaker("ollama")
        assert cb1 is cb2

    def test_get_circuit_breaker_different_providers(self) -> None:
        cb1 = _get_circuit_breaker("ollama")
        cb2 = _get_circuit_breaker("beeline")
        assert cb1 is not cb2
        assert cb1._provider_name == "ollama"
        assert cb2._provider_name == "beeline"

    def test_get_circuit_breaker_stats(self) -> None:
        _get_circuit_breaker("ollama")
        _get_circuit_breaker("beeline")
        stats = get_circuit_breaker_stats()
        assert "ollama" in stats
        assert "beeline" in stats
        assert stats["ollama"]["provider"] == "ollama"
        assert stats["beeline"]["provider"] == "beeline"

    def test_circuit_breaker_uses_settings(self) -> None:
        with patch("app.services.llm.settings") as mock_settings:
            mock_settings.llm_circuit_breaker_failures = 5
            mock_settings.llm_circuit_breaker_reset_seconds = 120.0
            cb = _get_circuit_breaker("test_provider")
            assert cb._failure_threshold == 5
            assert cb._reset_timeout == 120.0


# ═══════════════════════════════════════════════════════════
# Fallback order tests
# ═══════════════════════════════════════════════════════════


class TestFallbackOrder:
    """Test provider fallback order."""

    _ALL = {
        "qwen36", "qwen36_fast", "coding", "beeline", "beeline_fast",
        "qwen35", "ollama", "yandexgpt", "gigachat",
    }

    def test_ollama_primary(self) -> None:
        order = _get_fallback_order("ollama")
        assert order[0] == "ollama"
        assert len(order) == 9
        assert set(order) == self._ALL

    def test_beeline_primary(self) -> None:
        order = _get_fallback_order("beeline")
        assert order[0] == "beeline"
        assert len(order) == 9

    def test_qwen36_primary(self) -> None:
        order = _get_fallback_order("qwen36")
        assert order[0] == "qwen36"
        assert len(order) == 9

    def test_qwen36_fast_primary(self) -> None:
        order = _get_fallback_order("qwen36_fast")
        assert order[0] == "qwen36_fast"
        assert len(order) == 9

    def test_coding_primary(self) -> None:
        order = _get_fallback_order("coding")
        assert order[0] == "coding"
        assert len(order) == 9

    def test_beeline_fast_primary(self) -> None:
        order = _get_fallback_order("beeline_fast")
        assert order[0] == "beeline_fast"
        assert len(order) == 9

    def test_unknown_primary(self) -> None:
        order = _get_fallback_order("unknown")
        # Unknown provider → full canonical order (qwen36 first since 2026-07-14)
        assert order[0] == "qwen36"
        assert set(order) == self._ALL

    def test_all_providers_included(self) -> None:
        for primary in [
            "qwen36", "qwen36_fast", "coding", "beeline", "beeline_fast",
            "qwen35", "ollama", "yandexgpt", "gigachat",
        ]:
            order = _get_fallback_order(primary)
            assert len(order) == 9
            assert order[0] == primary
            assert len(set(order)) == 9  # No duplicates

    def test_guardrails_providers_last(self) -> None:
        """YandexGPT and GigaChat (Guardrails, unreliable) are last in the chain."""
        order = _get_fallback_order("beeline")
        assert order[-1] == "gigachat"
        assert order[-2] == "yandexgpt"


# ═══════════════════════════════════════════════════════════
# analyze_dialogue fallback chain tests
# ═══════════════════════════════════════════════════════════


class TestAnalyzeDialogueFallback:
    """Test analyze_dialogue with provider fallback chain."""

    def setup_method(self) -> None:
        """Clear circuit breaker registry before each test."""
        _circuit_breakers.clear()

    @pytest.mark.asyncio
    async def test_primary_provider_succeeds(self) -> None:
        """When primary provider succeeds, return result with that provider."""
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = '{"summary": "test", "topic": "test topic", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_provider.get_default_model = MagicMock(return_value="test-model")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert result.provider == "ollama"
        assert result.summary == "test"

    @pytest.mark.asyncio
    async def test_fallback_to_next_provider(self) -> None:
        """When primary provider fails, fall back to next available provider."""
        mock_ollama = AsyncMock()
        mock_ollama.generate.side_effect = ConnectionError("Ollama unavailable")

        mock_beeline = AsyncMock()
        mock_beeline.generate.return_value = '{"summary": "beeline result", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_beeline.get_default_model = MagicMock(return_value="glm-xlarge")

        def mock_get_provider(pid: str):
            if pid == "ollama":
                return mock_ollama
            if pid == "beeline":
                return mock_beeline
            return None

        with patch("app.services.llm.get_provider", side_effect=mock_get_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert result.provider == "beeline"
        assert result.summary == "beeline result"

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_degraded(self) -> None:
        """When all providers fail, return degraded LLMResult with provider='none'."""
        mock_provider = AsyncMock()
        mock_provider.generate.side_effect = ConnectionError("Service unavailable")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert result.provider == "none"
        assert result.summary == ""
        assert result.client_sentiment == "neutral"
        assert result.resolution == "unresolved"

    @pytest.mark.asyncio
    async def test_circuit_breaker_skips_open_provider(self) -> None:
        """When a provider's circuit breaker is open, it is skipped."""
        # Open the circuit breaker for ollama
        cb = _get_circuit_breaker("ollama")
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"

        mock_beeline = AsyncMock()
        mock_beeline.generate.return_value = '{"summary": "beeline fallback", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_beeline.get_default_model = MagicMock(return_value="glm-xlarge")

        def mock_get_provider(pid: str):
            if pid == "beeline":
                return mock_beeline
            return None

        with patch("app.services.llm.get_provider", side_effect=mock_get_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert result.provider == "beeline"

    @pytest.mark.asyncio
    async def test_not_configured_error_does_not_count_against_circuit_breaker(self) -> None:
        """'Not configured' errors should not count as circuit breaker failures."""
        mock_provider = AsyncMock()
        mock_provider.generate.side_effect = ConnectionError("YandexGPT not configured: missing api_key")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            result = await analyze_dialogue("test dialogue", provider_id="yandexgpt")

        # Circuit breaker should NOT have recorded the failure
        cb = _get_circuit_breaker("yandexgpt")
        assert cb._failure_count == 0
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_transient_error_counts_against_circuit_breaker(self) -> None:
        """Transient errors should count as circuit breaker failures."""
        mock_provider = AsyncMock()
        mock_provider.generate.side_effect = ConnectionError("Ollama unavailable after 2 attempts: timeout")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        cb = _get_circuit_breaker("ollama")
        assert cb._failure_count > 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_success_resets_state(self) -> None:
        """After a successful request, circuit breaker should be reset."""
        cb = _get_circuit_breaker("ollama")
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = '{"summary": "success", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_provider.get_default_model = MagicMock(return_value="test-model")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert cb.state == "closed"
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_provider_none_is_skipped(self) -> None:
        """When get_provider returns None, it is skipped without error."""
        mock_beeline = AsyncMock()
        mock_beeline.generate.return_value = '{"summary": "beeline", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_beeline.get_default_model = MagicMock(return_value="glm-xlarge")

        def mock_get_provider(pid: str):
            # Return None for all except beeline
            if pid == "beeline":
                return mock_beeline
            return None

        with patch("app.services.llm.get_provider", side_effect=mock_get_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert result.provider == "beeline"

    @pytest.mark.asyncio
    async def test_timeout_error_triggers_fallback(self) -> None:
        """TimeoutError should trigger fallback to next provider."""
        mock_ollama = AsyncMock()
        mock_ollama.generate.side_effect = TimeoutError("Request timed out")

        mock_beeline = AsyncMock()
        mock_beeline.generate.return_value = '{"summary": "beeline fallback", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_beeline.get_default_model = MagicMock(return_value="glm-xlarge")

        def mock_get_provider(pid: str):
            if pid == "ollama":
                return mock_ollama
            if pid == "beeline":
                return mock_beeline
            return None

        with patch("app.services.llm.get_provider", side_effect=mock_get_provider):
            result = await analyze_dialogue("test dialogue", provider_id="ollama")

        assert result.provider == "beeline"


# ═══════════════════════════════════════════════════════════
# SearchResult.search_source tests
# ═══════════════════════════════════════════════════════════


class TestSearchResultSource:
    """Test SearchResult.search_source field."""

    def test_search_result_has_search_source_field(self) -> None:
        result = SearchResult(
            segments=[],
            total_matches=0,
            matches=[],
            matches_by_level={},
            search_source="morph",
        )
        assert result.search_source == "morph"

    def test_search_source_default_is_none(self) -> None:
        result = SearchResult(
            segments=[],
            total_matches=0,
            matches=[],
            matches_by_level={},
        )
        assert result.search_source is None

    def test_search_source_semantic(self) -> None:
        result = SearchResult(
            segments=[],
            total_matches=0,
            matches=[],
            matches_by_level={},
            search_source="semantic",
        )
        assert result.search_source == "semantic"

    def test_search_source_hybrid(self) -> None:
        result = SearchResult(
            segments=[],
            total_matches=0,
            matches=[],
            matches_by_level={},
            search_source="hybrid",
        )
        assert result.search_source == "hybrid"

    def test_search_result_serialization_includes_source(self) -> None:
        result = SearchResult(
            segments=[],
            total_matches=0,
            matches=[],
            matches_by_level={},
            search_source="morph",
        )
        data = result.model_dump()
        assert "search_source" in data
        assert data["search_source"] == "morph"

    def test_search_result_backward_compatible(self) -> None:
        """Existing SearchResult without search_source should still work."""
        result = SearchResult(
            segments=[],
            total_matches=5,
            matches=[],
            matches_by_level={"1": 3, "2": 2},
        )
        assert result.total_matches == 5
        assert result.search_source is None

    @pytest.mark.asyncio
    async def test_run_hierarchical_search_sets_morph_source(self) -> None:
        """run_hierarchical_search should set search_source='morph'."""
        from app.models import DialogueTurn, ParsedDialog, DictionaryNode, DictionaryCondition

        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте"),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день"),
            ],
            total_turns=2,
        )

        dict_node = DictionaryNode(
            id="test-dict",
            name="Тестовый словарь",
            conditions=[
                DictionaryCondition(text="здравствуйте", word_distance=2),
            ],
        )

        from app.services.search import run_hierarchical_search
        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[dict_node],
        )
        assert result.search_source == "morph"


# ═══════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════


class TestConfig:
    """Test new configuration fields."""

    def test_default_circuit_breaker_failures(self) -> None:
        settings = Settings()
        assert settings.llm_circuit_breaker_failures == 3

    def test_default_circuit_breaker_reset_seconds(self) -> None:
        settings = Settings()
        assert settings.llm_circuit_breaker_reset_seconds == 60.0

    def test_default_search_fallback_enabled(self) -> None:
        settings = Settings()
        assert settings.search_fallback_enabled is True

    def test_config_override_via_env(self) -> None:
        """Config values can be overridden via environment variables."""
        import os
        original = os.environ.get("LLM_CIRCUIT_BREAKER_FAILURES")
        try:
            os.environ["LLM_CIRCUIT_BREAKER_FAILURES"] = "7"
            settings = Settings()
            assert settings.llm_circuit_breaker_failures == 7
        finally:
            if original is None:
                os.environ.pop("LLM_CIRCUIT_BREAKER_FAILURES", None)
            else:
                os.environ["LLM_CIRCUIT_BREAKER_FAILURES"] = original


# ═══════════════════════════════════════════════════════════
# Analysis response status tests
# ═══════════════════════════════════════════════════════════


class TestAnalysisResponseStatus:
    """Test AnalysisResponse status with degraded LLM results."""

    def test_completed_when_llm_succeeds(self) -> None:
        response = AnalysisResponse(
            analysis_id="test",
            session_id="test-session",
            status="completed",
            search_result=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
                search_source="morph",
            ),
            llm_result=LLMResult(
                summary="Test summary",
                provider="ollama",
                model="test-model",
            ),
        )
        assert response.status == "completed"
        assert response.llm_result.provider == "ollama"

    def test_partial_when_llm_degraded(self) -> None:
        response = AnalysisResponse(
            analysis_id="test",
            session_id="test-session",
            status="partial",
            search_result=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
                search_source="morph",
            ),
            llm_result=LLMResult(
                provider="none",
                client_sentiment="neutral",
                resolution="unresolved",
            ),
            warning="LLM unavailable: all providers failed",
        )
        assert response.status == "partial"
        assert response.llm_result.provider == "none"
        assert response.warning is not None

    def test_completed_when_no_llm_requested(self) -> None:
        response = AnalysisResponse(
            analysis_id="test",
            session_id="test-session",
            status="completed",
            search_result=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
                search_source="morph",
            ),
        )
        assert response.status == "completed"
        assert response.llm_result is None

    def test_search_source_in_response(self) -> None:
        response = AnalysisResponse(
            analysis_id="test",
            session_id="test-session",
            status="completed",
            search_result=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
                search_source="morph",
            ),
        )
        assert response.search_result.search_source == "morph"


# ═══════════════════════════════════════════════════════════
# Integration: circuit breaker + fallback together
# ═══════════════════════════════════════════════════════════


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with fallback chain."""

    def setup_method(self) -> None:
        _circuit_breakers.clear()

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_repeated_failures(self) -> None:
        """After N failures, circuit breaker opens and subsequent requests skip it."""
        mock_provider = AsyncMock()
        mock_provider.generate.side_effect = ConnectionError("Service unavailable")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            # First call: should try all providers
            result1 = await analyze_dialogue("test", provider_id="ollama")
            assert result1.provider == "none"

        # Circuit breaker for each provider should have failures recorded
        for pid in ["beeline", "beeline_fast", "qwen36", "qwen35", "ollama", "yandexgpt", "gigachat"]:
            cb = _get_circuit_breaker(pid)
            assert cb._failure_count > 0

    @pytest.mark.asyncio
    async def test_fallback_preserves_circuit_breaker_state(self) -> None:
        """Circuit breaker state persists across multiple analyze_dialogue calls."""
        # Open the circuit breaker for ollama manually
        cb = _get_circuit_breaker("ollama")
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"

        # Now a request to ollama should skip it
        mock_beeline = AsyncMock()
        mock_beeline.generate.return_value = '{"summary": "beeline", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_beeline.get_default_model = MagicMock(return_value="glm-xlarge")

        def mock_get_provider(pid: str):
            if pid == "beeline":
                return mock_beeline
            return None

        with patch("app.services.llm.get_provider", side_effect=mock_get_provider):
            result = await analyze_dialogue("test", provider_id="ollama")

        # Should have fallen back to beeline
        assert result.provider == "beeline"

    @pytest.mark.asyncio
    async def test_half_open_allows_probe_then_closes(self) -> None:
        """Half-open state allows one probe request; success closes circuit."""
        cb = _get_circuit_breaker("ollama")
        cb._state = "half-open"

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = '{"summary": "recovered", "topic": "test", "client_sentiment": "neutral", "resolution": "unresolved", "key_points": [], "result": "", "restructured_dialogue": ""}'
        mock_provider.get_default_model = MagicMock(return_value="test-model")

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            result = await analyze_dialogue("test", provider_id="ollama")

        assert result.provider == "ollama"
        assert cb.state == "closed"

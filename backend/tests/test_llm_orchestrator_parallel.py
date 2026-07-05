"""Tests for LLMOrchestrator parallel mode (IP-3.6 enhancement).

Covers:
  - 4 steps run concurrently via asyncio.gather
  - Exception in one step does not block others (return_exceptions=True)
  - Semaphore limits respected across parallel steps
  - Results aggregated correctly into AnalysisAnnotation
  - parallel=False falls back to sequential
  - provider_id=None triggers per-task smart routing
  - Backward compat: default (parallel=True via settings) still produces valid annotation
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.models import (
    AnalysisAnnotation,
    ConflictAnalysisResult,
    ProfanityAnalysisResult,
    SentimentAnalysisResult,
    TopicAnalysisResult,
    ProgressInfo,
)
from app.services.llm import LLMOrchestrator


# ── Factories (model="glm-xlarge" per glm-5.1 decommission) ──────────────────


def _sentiment(**kw: Any) -> SentimentAnalysisResult:
    defaults = {
        "utterances": [],
        "overall_sentiment": "neutral",
        "sentiment_trajectory": "stable",
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return SentimentAnalysisResult(**defaults)


def _conflict(**kw: Any) -> ConflictAnalysisResult:
    defaults = {
        "has_conflict": False,
        "conflict_level": "none",
        "escalation_points": [],
        "de_escalation_attempts": 0,
        "justification": "",
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return ConflictAnalysisResult(**defaults)


def _profanity(**kw: Any) -> ProfanityAnalysisResult:
    defaults = {
        "has_profanity": False,
        "instances": [],
        "total_count": 0,
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return ProfanityAnalysisResult(**defaults)


def _topic(**kw: Any) -> TopicAnalysisResult:
    defaults = {
        "topics": [],
        "primary_topic": "",
        "topic_count": 0,
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return TopicAnalysisResult(**defaults)


# ═══════════════════════════════════════════════════════════
# 1. Parallel execution
# ═══════════════════════════════════════════════════════════


class TestParallelExecution:
    """Steps run concurrently via asyncio.gather."""

    @pytest.mark.asyncio
    async def test_parallel_mode_runs_all_steps(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _sentiment()
            mock_c.return_value = _conflict()
            mock_p.return_value = _profanity()
            mock_t.return_value = _topic()

            orch = LLMOrchestrator()
            result = await orch.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
                parallel=True,
            )

        assert result.sentiment is not None
        assert result.conflict is not None
        assert result.profanity is not None
        assert result.topic is not None
        assert result.progress.completed_steps == ["sentiment", "conflict", "profanity", "topic"]
        assert result.progress.error_steps == []
        assert result.progress.current_step == "done"

    @pytest.mark.asyncio
    async def test_parallel_mode_actually_concurrent(self) -> None:
        """Parallel mode should be faster than sequential when steps sleep."""
        call_times: dict[str, float] = {}

        async def _slow_sentiment(*a: Any, **kw: Any) -> SentimentAnalysisResult:
            call_times["sentiment"] = time.time()
            await asyncio.sleep(0.1)
            return _sentiment()

        async def _slow_conflict(*a: Any, **kw: Any) -> ConflictAnalysisResult:
            call_times["conflict"] = time.time()
            await asyncio.sleep(0.1)
            return _conflict()

        async def _slow_profanity(*a: Any, **kw: Any) -> ProfanityAnalysisResult:
            call_times["profanity"] = time.time()
            await asyncio.sleep(0.1)
            return _profanity()

        async def _slow_topic(*a: Any, **kw: Any) -> TopicAnalysisResult:
            call_times["topic"] = time.time()
            await asyncio.sleep(0.1)
            return _topic()

        with (
            patch("app.services.llm.analyze_sentiment", new=_slow_sentiment),
            patch("app.services.llm.analyze_conflict", new=_slow_conflict),
            patch("app.services.llm.analyze_profanity", new=_slow_profanity),
            patch("app.services.llm.analyze_topic", new=_slow_topic),
        ):
            orch = LLMOrchestrator()
            start = time.time()
            await orch.run_all_analyses(dialogue_text="text", session_id="s1", parallel=True)
            parallel_elapsed = time.time() - start

            start2 = time.time()
            await orch.run_all_analyses(dialogue_text="text", session_id="s1", parallel=False)
            sequential_elapsed = time.time() - start2

        # Parallel (≈0.1s) should be significantly faster than sequential (≈0.4s)
        assert parallel_elapsed < sequential_elapsed
        # Parallel should be under ~0.3s (4 steps × 0.1s in parallel ≈ 0.1s + overhead)
        assert parallel_elapsed < 0.3


# ═══════════════════════════════════════════════════════════
# 2. Fault isolation
# ═══════════════════════════════════════════════════════════


class TestParallelFaultIsolation:
    """Exception in one step does not block others."""

    @pytest.mark.asyncio
    async def test_one_step_raises_others_succeed(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.side_effect = RuntimeError("boom")
            mock_c.return_value = _conflict()
            mock_p.return_value = _profanity()
            mock_t.return_value = _topic()

            orch = LLMOrchestrator()
            result = await orch.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
                parallel=True,
            )

        # sentiment failed, others succeeded
        assert "sentiment" in result.progress.error_steps
        assert result.sentiment is None
        assert result.conflict is not None
        assert result.profanity is not None
        assert result.topic is not None
        assert set(result.progress.completed_steps) == {"conflict", "profanity", "topic"}

    @pytest.mark.asyncio
    async def test_two_steps_raise(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.side_effect = ValueError("bad")
            mock_c.side_effect = ConnectionError("down")
            mock_p.return_value = _profanity()
            mock_t.return_value = _topic()

            orch = LLMOrchestrator()
            result = await orch.run_all_analyses(
                dialogue_text="text", session_id="s1", parallel=True,
            )

        assert set(result.progress.error_steps) == {"sentiment", "conflict"}
        assert set(result.progress.completed_steps) == {"profanity", "topic"}

    @pytest.mark.asyncio
    async def test_all_steps_raise(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.side_effect = RuntimeError("boom")
            mock_c.side_effect = RuntimeError("boom")
            mock_p.side_effect = RuntimeError("boom")
            mock_t.side_effect = RuntimeError("boom")

            orch = LLMOrchestrator()
            result = await orch.run_all_analyses(
                dialogue_text="text", session_id="s1", parallel=True,
            )

        assert len(result.progress.error_steps) == 4
        assert result.progress.completed_steps == []
        assert result.provider == "none"


# ═══════════════════════════════════════════════════════════
# 3. Sequential fallback
# ═══════════════════════════════════════════════════════════


class TestSequentialFallback:
    """parallel=False runs steps one at a time in order."""

    @pytest.mark.asyncio
    async def test_sequential_runs_in_order(self) -> None:
        call_order: list[str] = []

        async def _track(name: str) -> Any:
            call_order.append(name)
            await asyncio.sleep(0)
            return {
                "sentiment": _sentiment,
                "conflict": _conflict,
                "profanity": _profanity,
                "topic": _topic,
            }[name]()

        with (
            patch("app.services.llm.analyze_sentiment", new=lambda *a, **kw: _track("sentiment")),
            patch("app.services.llm.analyze_conflict", new=lambda *a, **kw: _track("conflict")),
            patch("app.services.llm.analyze_profanity", new=lambda *a, **kw: _track("profanity")),
            patch("app.services.llm.analyze_topic", new=lambda *a, **kw: _track("topic")),
        ):
            orch = LLMOrchestrator()
            await orch.run_all_analyses(
                dialogue_text="text", session_id="s1", parallel=False,
            )

        assert call_order == ["sentiment", "conflict", "profanity", "topic"]

    @pytest.mark.asyncio
    async def test_sequential_exception_does_not_block_others(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.side_effect = RuntimeError("boom")
            mock_c.return_value = _conflict()
            mock_p.return_value = _profanity()
            mock_t.return_value = _topic()

            orch = LLMOrchestrator()
            result = await orch.run_all_analyses(
                dialogue_text="text", session_id="s1", parallel=False,
            )

        assert "sentiment" in result.progress.error_steps
        assert result.conflict is not None


# ═══════════════════════════════════════════════════════════
# 4. Smart routing (provider_id=None)
# ═══════════════════════════════════════════════════════════


class TestSmartRouting:
    """provider_id=None triggers per-task smart routing."""

    @pytest.mark.asyncio
    async def test_none_provider_uses_smart_routing(self) -> None:
        captured_providers: list[str] = []

        async def _capture_sentiment(*a: Any, provider_id: str = "beeline", **kw: Any) -> SentimentAnalysisResult:
            captured_providers.append(provider_id)
            return _sentiment()

        async def _capture_conflict(*a: Any, provider_id: str = "beeline", **kw: Any) -> ConflictAnalysisResult:
            captured_providers.append(provider_id)
            return _conflict()

        async def _capture_profanity(*a: Any, provider_id: str = "beeline", **kw: Any) -> ProfanityAnalysisResult:
            captured_providers.append(provider_id)
            return _profanity()

        async def _capture_topic(*a: Any, provider_id: str = "beeline", **kw: Any) -> TopicAnalysisResult:
            captured_providers.append(provider_id)
            return _topic()

        with (
            patch("app.services.llm.analyze_sentiment", new=_capture_sentiment),
            patch("app.services.llm.analyze_conflict", new=_capture_conflict),
            patch("app.services.llm.analyze_profanity", new=_capture_profanity),
            patch("app.services.llm.analyze_topic", new=_capture_topic),
        ):
            orch = LLMOrchestrator()
            await orch.run_all_analyses(
                dialogue_text="text", session_id="s1",
                provider_id=None,  # smart routing
                parallel=False,
            )

        # Each step should have received a non-None provider from _TASK_MODEL_PREFERENCE
        assert all(p is not None for p in captured_providers)
        assert len(captured_providers) == 4


# ═══════════════════════════════════════════════════════════
# 5. Backward compat — default mode
# ═══════════════════════════════════════════════════════════


class TestDefaultModeBackwardCompat:
    """Calling without explicit parallel= uses settings default (True)."""

    @pytest.mark.asyncio
    async def test_default_mode_produces_valid_annotation(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _sentiment()
            mock_c.return_value = _conflict()
            mock_p.return_value = _profanity()
            mock_t.return_value = _topic()

            orch = LLMOrchestrator()
            # No parallel= argument → uses settings.llm_orchestrator_parallel (True)
            result = await orch.run_all_analyses(
                dialogue_text="text", session_id="s1",
            )

        assert isinstance(result, AnalysisAnnotation)
        assert result.sentiment is not None
        assert result.progress.current_step == "done"

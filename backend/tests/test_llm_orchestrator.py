"""Comprehensive tests for LLMOrchestrator (IP-3.6) and AnalysisAnnotation (IP-3.7).

Covers:
  - ProgressInfo model validation
  - AnalysisAnnotation model validation
  - LLMOrchestrator happy path (all steps succeed)
  - Partial failure (1 step degrades gracefully)
  - All steps fail (total degradation)
  - Progress tracking (current_step, completed, remaining, errors)
  - Custom step order
  - Unknown step name handling
  - include_summary flag
  - /api/analysis/full endpoint
  - Individual endpoints still work independently
  - Config: llm_orchestrator_steps, llm_orchestrator_enabled
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.models import (
    AnalysisAnnotation,
    ConflictAnalysisResult,
    EscalationPoint,
    LLMResult,
    ProgressInfo,
    ProfanityAnalysisResult,
    ProfanityInstance,
    SentimentAnalysisResult,
    TopicAnalysisResult,
    DetectedTopic,
    UtteranceSentiment,
)
from app.services.llm import LLMOrchestrator


# ═══════════════════════════════════════════════════════════
# Helpers — valid analysis result factories
# ═══════════════════════════════════════════════════════════


def _make_sentiment_result(**overrides: Any) -> SentimentAnalysisResult:
    defaults = {
        "utterances": [
            UtteranceSentiment(
                turn_index=0, speaker="Клиент",
                sentiment="negative", confidence=0.9,
                text_snippet="Не работает",
            ),
        ],
        "overall_sentiment": "negative",
        "sentiment_trajectory": "stable",
        "provider": "beeline",
        "model": "glm-5.1",
    }
    defaults.update(overrides)
    return SentimentAnalysisResult(**defaults)


def _make_conflict_result(**overrides: Any) -> ConflictAnalysisResult:
    defaults = {
        "has_conflict": False,
        "conflict_level": "none",
        "escalation_points": [],
        "de_escalation_attempts": 0,
        "justification": "Спокойный диалог",
        "provider": "beeline",
        "model": "glm-5.1",
    }
    defaults.update(overrides)
    return ConflictAnalysisResult(**defaults)


def _make_profanity_result(**overrides: Any) -> ProfanityAnalysisResult:
    defaults = {
        "has_profanity": False,
        "instances": [],
        "total_count": 0,
        "provider": "beeline",
        "model": "glm-5.1",
    }
    defaults.update(overrides)
    return ProfanityAnalysisResult(**defaults)


def _make_topic_result(**overrides: Any) -> TopicAnalysisResult:
    defaults = {
        "topics": [
            DetectedTopic(
                name="Интернет",
                confidence=0.9,
                key_phrases=["скорость"],
                turn_indices=[0],
            ),
        ],
        "primary_topic": "Интернет",
        "topic_count": 1,
        "provider": "beeline",
        "model": "glm-5.1",
    }
    defaults.update(overrides)
    return TopicAnalysisResult(**defaults)


def _make_llm_result(**overrides: Any) -> LLMResult:
    defaults = {
        "summary": "Клиент обращается по поводу интернета",
        "topic": "Интернет",
        "result": "resolved",
        "key_points": ["Не работает интернет"],
        "client_sentiment": "negative",
        "resolution": "resolved",
        "provider": "beeline",
        "model": "glm-5.1",
    }
    defaults.update(overrides)
    return LLMResult(**defaults)


# Degraded (fallback) results — provider="none"
def _degraded_sentiment() -> SentimentAnalysisResult:
    return _make_sentiment_result(
        utterances=[], overall_sentiment="neutral",
        sentiment_trajectory="stable", provider="none", model="",
    )


def _degraded_conflict() -> ConflictAnalysisResult:
    return _make_conflict_result(
        provider="none", model="",
    )


def _degraded_profanity() -> ProfanityAnalysisResult:
    return _make_profanity_result(
        provider="none", model="",
    )


def _degraded_topic() -> TopicAnalysisResult:
    return _make_topic_result(
        topics=[], primary_topic="", topic_count=0,
        provider="none", model="",
    )


# ═══════════════════════════════════════════════════════════
# 1. ProgressInfo model tests
# ═══════════════════════════════════════════════════════════


class TestProgressInfoModel:
    """ProgressInfo Pydantic model validation."""

    def test_defaults(self) -> None:
        info = ProgressInfo()
        assert info.current_step == "pending"
        assert info.completed_steps == []
        assert info.remaining_steps == []
        assert info.total_steps == 0
        assert info.error_steps == []

    def test_full_progress(self) -> None:
        info = ProgressInfo(
            current_step="done",
            completed_steps=["sentiment", "conflict", "profanity", "topic"],
            remaining_steps=[],
            total_steps=4,
            error_steps=[],
        )
        assert info.current_step == "done"
        assert len(info.completed_steps) == 4
        assert info.total_steps == 4
        assert info.error_steps == []

    def test_partial_failure_progress(self) -> None:
        info = ProgressInfo(
            current_step="done",
            completed_steps=["sentiment", "topic"],
            remaining_steps=[],
            total_steps=4,
            error_steps=["conflict", "profanity"],
        )
        assert len(info.completed_steps) == 2
        assert len(info.error_steps) == 2

    def test_serializable_to_json(self) -> None:
        """ProgressInfo must be serialisable for future SSE support."""
        info = ProgressInfo(
            current_step="conflict",
            completed_steps=["sentiment"],
            remaining_steps=["profanity", "topic"],
            total_steps=4,
            error_steps=[],
        )
        data = info.model_dump()
        serialized = json.dumps(data)
        assert "sentiment" in serialized
        assert "conflict" in serialized
        # Round-trip
        restored = ProgressInfo.model_validate(json.loads(serialized))
        assert restored.current_step == "conflict"
        assert restored.completed_steps == ["sentiment"]

    def test_in_progress_state(self) -> None:
        info = ProgressInfo(
            current_step="profanity",
            completed_steps=["sentiment", "conflict"],
            remaining_steps=["topic"],
            total_steps=4,
            error_steps=[],
        )
        assert info.current_step == "profanity"
        assert len(info.completed_steps) == 2
        assert info.remaining_steps == ["topic"]


# ═══════════════════════════════════════════════════════════
# 2. AnalysisAnnotation model tests
# ═══════════════════════════════════════════════════════════


class TestAnalysisAnnotationModel:
    """AnalysisAnnotation Pydantic model validation."""

    def test_minimal_annotation(self) -> None:
        ann = AnalysisAnnotation(
            session_id="test-session",
            progress=ProgressInfo(current_step="done", total_steps=4),
        )
        assert ann.session_id == "test-session"
        assert ann.sentiment is None
        assert ann.conflict is None
        assert ann.profanity is None
        assert ann.topic is None
        assert ann.summary is None
        assert ann.provider == "none"
        assert ann.analysis_source == "orchestrator"

    def test_full_annotation(self) -> None:
        ann = AnalysisAnnotation(
            session_id="test-session",
            sentiment=_make_sentiment_result(),
            conflict=_make_conflict_result(),
            profanity=_make_profanity_result(),
            topic=_make_topic_result(),
            summary=_make_llm_result(),
            progress=ProgressInfo(
                current_step="done",
                completed_steps=["sentiment", "conflict", "profanity", "topic"],
                total_steps=4,
            ),
            provider="beeline",
            model="glm-5.1",
            completed_at="2026-06-22T12:00:00+00:00",
        )
        assert ann.sentiment is not None
        assert ann.sentiment.overall_sentiment == "negative"
        assert ann.conflict is not None
        assert ann.conflict.has_conflict is False
        assert ann.profanity is not None
        assert ann.topic is not None
        assert ann.topic.primary_topic == "Интернет"
        assert ann.summary is not None
        assert ann.summary.topic == "Интернет"
        assert ann.provider == "beeline"

    def test_annotation_with_partial_results(self) -> None:
        """Annotation with only some results (graceful degradation)."""
        ann = AnalysisAnnotation(
            session_id="test-session",
            sentiment=_make_sentiment_result(),
            conflict=None,  # Failed
            profanity=_make_profanity_result(),
            topic=None,  # Failed
            progress=ProgressInfo(
                current_step="done",
                completed_steps=["sentiment", "profanity"],
                total_steps=4,
                error_steps=["conflict", "topic"],
            ),
            provider="beeline",
        )
        assert ann.sentiment is not None
        assert ann.conflict is None
        assert ann.profanity is not None
        assert ann.topic is None
        assert len(ann.progress.error_steps) == 2

    def test_annotation_serializable(self) -> None:
        """AnalysisAnnotation must be serialisable."""
        ann = AnalysisAnnotation(
            session_id="test-session",
            sentiment=_make_sentiment_result(),
            progress=ProgressInfo(current_step="done", total_steps=4),
            provider="beeline",
            model="glm-5.1",
            completed_at="2026-06-22T12:00:00+00:00",
        )
        data = ann.model_dump()
        serialized = json.dumps(data, default=str)
        assert "sentiment" in serialized
        # Round-trip
        restored = AnalysisAnnotation.model_validate(json.loads(serialized))
        assert restored.session_id == "test-session"
        assert restored.sentiment is not None

    def test_analysis_source_values(self) -> None:
        ann = AnalysisAnnotation(
            session_id="s1",
            progress=ProgressInfo(total_steps=0),
            analysis_source="individual",
        )
        assert ann.analysis_source == "individual"

    def test_default_analysis_source(self) -> None:
        ann = AnalysisAnnotation(
            session_id="s1",
            progress=ProgressInfo(total_steps=0),
        )
        assert ann.analysis_source == "orchestrator"


# ═══════════════════════════════════════════════════════════
# 3. LLMOrchestrator — happy path
# ═══════════════════════════════════════════════════════════


class TestLLMOrchestratorHappyPath:
    """All 4 steps succeed."""

    @pytest.mark.asyncio
    async def test_all_steps_succeed(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_sentiment,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_conflict,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_profanity,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_topic,
        ):
            mock_sentiment.return_value = _make_sentiment_result()
            mock_conflict.return_value = _make_conflict_result()
            mock_profanity.return_value = _make_profanity_result()
            mock_topic.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="Клиент: Не работает интернет",
                session_id="test-session",
                provider_id="beeline",
            )

            assert isinstance(result, AnalysisAnnotation)
            assert result.session_id == "test-session"
            assert result.sentiment is not None
            assert result.sentiment.overall_sentiment == "negative"
            assert result.conflict is not None
            assert result.conflict.has_conflict is False
            assert result.profanity is not None
            assert result.topic is not None
            assert result.topic.primary_topic == "Интернет"
            assert result.summary is None  # include_summary=False by default
            assert result.provider == "beeline"
            assert result.model == "glm-5.1"
            assert result.analysis_source == "orchestrator"

            # Progress
            assert result.progress.current_step == "done"
            assert result.progress.completed_steps == ["sentiment", "conflict", "profanity", "topic"]
            assert result.progress.remaining_steps == []
            assert result.progress.total_steps == 4
            assert result.progress.error_steps == []

            # Completed_at is a valid ISO timestamp
            assert result.completed_at != ""
            datetime.fromisoformat(result.completed_at)

    @pytest.mark.asyncio
    async def test_steps_called_in_order(self) -> None:
        """Verify steps are called in the configured order."""
        call_order: list[str] = []

        async def _track_sentiment(*args: Any, **kwargs: Any) -> SentimentAnalysisResult:
            call_order.append("sentiment")
            return _make_sentiment_result()

        async def _track_conflict(*args: Any, **kwargs: Any) -> ConflictAnalysisResult:
            call_order.append("conflict")
            return _make_conflict_result()

        async def _track_profanity(*args: Any, **kwargs: Any) -> ProfanityAnalysisResult:
            call_order.append("profanity")
            return _make_profanity_result()

        async def _track_topic(*args: Any, **kwargs: Any) -> TopicAnalysisResult:
            call_order.append("topic")
            return _make_topic_result()

        with (
            patch("app.services.llm.analyze_sentiment", new=_track_sentiment),
            patch("app.services.llm.analyze_conflict", new=_track_conflict),
            patch("app.services.llm.analyze_profanity", new=_track_profanity),
            patch("app.services.llm.analyze_topic", new=_track_topic),
        ):
            orchestrator = LLMOrchestrator()
            await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

        assert call_order == ["sentiment", "conflict", "profanity", "topic"]

    @pytest.mark.asyncio
    async def test_include_summary_true(self) -> None:
        """include_summary=True also runs analyze_dialogue."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
            patch("app.services.llm.analyze_dialogue", new_callable=AsyncMock) as mock_sum,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()
            mock_sum.return_value = _make_llm_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
                include_summary=True,
            )

            assert result.summary is not None
            assert result.summary.topic == "Интернет"
            mock_sum.assert_called_once()

    @pytest.mark.asyncio
    async def test_include_summary_false(self) -> None:
        """include_summary=False does NOT run analyze_dialogue."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
            patch("app.services.llm.analyze_dialogue", new_callable=AsyncMock) as mock_sum,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
                include_summary=False,
            )

            assert result.summary is None
            mock_sum.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 4. LLMOrchestrator — graceful degradation
#
# The existing analysis functions (analyze_sentiment, etc.) never raise
# exceptions — they return default instances with provider="none" when
# all LLM providers fail. So "failure" is detected by checking the
# provider field. The orchestrator's try/except is a safety net.
# ═══════════════════════════════════════════════════════════


class TestLLMOrchestratorGracefulDegradation:
    """Partial and total failure scenarios.

    Since analysis functions return degraded results (provider="none")
    rather than raising, we mock them to return degraded results to
    simulate LLM failures.
    """

    @pytest.mark.asyncio
    async def test_one_step_degrades(self) -> None:
        """One step returns degraded result — step recorded as error."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _make_sentiment_result()
            # conflict returns degraded (provider="none")
            mock_c.return_value = _degraded_conflict()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            # All results are present (not None) because the functions
            # returned degraded defaults, but conflict has provider="none"
            assert result.sentiment is not None
            assert result.sentiment.provider == "beeline"
            assert result.conflict is not None
            assert result.conflict.provider == "none"
            assert result.profanity is not None
            assert result.topic is not None

    @pytest.mark.asyncio
    async def test_two_steps_degrade(self) -> None:
        """Multiple steps return degraded results."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _degraded_sentiment()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _degraded_profanity()
            mock_t.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            assert result.sentiment is not None
            assert result.sentiment.provider == "none"
            assert result.conflict is not None
            assert result.conflict.provider == "beeline"
            assert result.profanity is not None
            assert result.profanity.provider == "none"
            assert result.topic is not None
            assert result.topic.provider == "beeline"

    @pytest.mark.asyncio
    async def test_all_steps_degrade(self) -> None:
        """All steps return degraded results — provider='none'."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _degraded_sentiment()
            mock_c.return_value = _degraded_conflict()
            mock_p.return_value = _degraded_profanity()
            mock_t.return_value = _degraded_topic()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            assert result.sentiment is not None
            assert result.sentiment.provider == "none"
            assert result.conflict is not None
            assert result.conflict.provider == "none"
            assert result.profanity is not None
            assert result.profanity.provider == "none"
            assert result.topic is not None
            assert result.topic.provider == "none"
            assert result.progress.current_step == "done"
            assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_unexpected_exception_safety_net(self) -> None:
        """If an analysis function unexpectedly raises, orchestrator catches it."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.side_effect = RuntimeError("Unexpected error")
            mock_c.return_value = _make_conflict_result()
            mock_p.side_effect = ValueError("Bad value")
            mock_t.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            # conflict and topic should still have succeeded
            assert result.conflict is not None
            assert result.topic is not None
            # sentiment and profanity raised — recorded in error_steps
            assert "sentiment" in result.progress.error_steps
            assert "profanity" in result.progress.error_steps
            assert "conflict" in result.progress.completed_steps
            assert "topic" in result.progress.completed_steps

    @pytest.mark.asyncio
    async def test_summary_failure_does_not_affect_main_results(self) -> None:
        """Summary failure is independent from the 4 main analyses."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
            patch("app.services.llm.analyze_dialogue", new_callable=AsyncMock) as mock_sum,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()
            mock_sum.side_effect = ConnectionError("unavailable")

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
                include_summary=True,
            )

            # Main results are still present
            assert result.sentiment is not None
            assert result.conflict is not None
            assert result.profanity is not None
            assert result.topic is not None
            # Summary failed
            assert result.summary is None


# ═══════════════════════════════════════════════════════════
# 5. LLMOrchestrator — progress tracking
# ═══════════════════════════════════════════════════════════


class TestLLMOrchestratorProgressTracking:
    """Detailed progress info validation."""

    @pytest.mark.asyncio
    async def test_progress_all_succeed(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            p = result.progress
            assert p.current_step == "done"
            assert p.completed_steps == ["sentiment", "conflict", "profanity", "topic"]
            assert p.remaining_steps == []
            assert p.total_steps == 4
            assert p.error_steps == []

    @pytest.mark.asyncio
    async def test_progress_with_exceptions(self) -> None:
        """Steps that raise exceptions are recorded in error_steps."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.side_effect = ConnectionError("fail")
            mock_p.side_effect = ConnectionError("fail")
            mock_t.return_value = _make_topic_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            p = result.progress
            assert p.current_step == "done"
            assert p.completed_steps == ["sentiment", "topic"]
            assert p.error_steps == ["conflict", "profanity"]
            assert p.total_steps == 4
            assert p.remaining_steps == []


# ═══════════════════════════════════════════════════════════
# 6. LLMOrchestrator — custom step order
# ═══════════════════════════════════════════════════════════


class TestLLMOrchestratorCustomSteps:
    """Custom step configuration."""

    @pytest.mark.asyncio
    async def test_custom_step_order(self) -> None:
        """Orchestrator respects custom step order."""
        call_order: list[str] = []

        async def _track(name: str) -> Any:
            call_order.append(name)
            if name == "sentiment":
                return _make_sentiment_result()
            if name == "conflict":
                return _make_conflict_result()
            if name == "profanity":
                return _make_profanity_result()
            if name == "topic":
                return _make_topic_result()
            return None

        with (
            patch("app.services.llm.analyze_sentiment", new=lambda *a, **kw: _track("sentiment")),
            patch("app.services.llm.analyze_conflict", new=lambda *a, **kw: _track("conflict")),
            patch("app.services.llm.analyze_profanity", new=lambda *a, **kw: _track("profanity")),
            patch("app.services.llm.analyze_topic", new=lambda *a, **kw: _track("topic")),
        ):
            orchestrator = LLMOrchestrator(steps=["topic", "sentiment"])
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

        assert call_order == ["topic", "sentiment"]
        assert result.progress.completed_steps == ["topic", "sentiment"]
        assert result.progress.total_steps == 2

    @pytest.mark.asyncio
    async def test_single_step(self) -> None:
        """Orchestrator can run only one step."""
        with patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s:
            mock_s.return_value = _make_sentiment_result()

            orchestrator = LLMOrchestrator(steps=["sentiment"])
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            assert result.sentiment is not None
            assert result.conflict is None
            assert result.progress.total_steps == 1
            assert result.progress.completed_steps == ["sentiment"]

    @pytest.mark.asyncio
    async def test_empty_steps(self) -> None:
        """Orchestrator with empty steps returns empty annotation."""
        orchestrator = LLMOrchestrator(steps=[])
        result = await orchestrator.run_all_analyses(
            dialogue_text="text",
            session_id="s1",
        )

        assert result.sentiment is None
        assert result.progress.total_steps == 0
        assert result.progress.completed_steps == []
        assert result.progress.current_step == "done"


class TestLLMOrchestratorUnknownStep:
    """Unknown step names are handled gracefully."""

    @pytest.mark.asyncio
    async def test_unknown_step_recorded_as_error(self) -> None:
        """Unknown step name is skipped and recorded in error_steps."""
        with patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s:
            mock_s.return_value = _make_sentiment_result()

            orchestrator = LLMOrchestrator(steps=["sentiment", "unknown_step"])
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            assert result.sentiment is not None
            assert "unknown_step" in result.progress.error_steps
            assert result.progress.completed_steps == ["sentiment"]


# ═══════════════════════════════════════════════════════════
# 7. LLMOrchestrator — provider tracking
# ═══════════════════════════════════════════════════════════


class TestLLMOrchestratorProviderTracking:
    """Provider and model metadata from first successful step."""

    @pytest.mark.asyncio
    async def test_first_successful_provider_captured(self) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _make_sentiment_result(provider="ollama", model="llama3.2")
            mock_c.return_value = _make_conflict_result(provider="beeline", model="glm-5.1")
            mock_p.return_value = _make_profanity_result(provider="beeline", model="glm-5.1")
            mock_t.return_value = _make_topic_result(provider="beeline", model="glm-5.1")

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            # First successful provider
            assert result.provider == "ollama"
            assert result.model == "llama3.2"

    @pytest.mark.asyncio
    async def test_no_successful_provider(self) -> None:
        """All steps degraded → provider='none'."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _degraded_sentiment()
            mock_c.return_value = _degraded_conflict()
            mock_p.return_value = _degraded_profanity()
            mock_t.return_value = _degraded_topic()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
            )

            assert result.provider == "none"
            assert result.model == ""

    @pytest.mark.asyncio
    async def test_provider_from_summary_when_steps_degraded(self) -> None:
        """If all steps degraded but summary succeeded, use its provider."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
            patch("app.services.llm.analyze_dialogue", new_callable=AsyncMock) as mock_sum,
        ):
            # All analysis steps return degraded defaults (provider="none")
            mock_s.return_value = _degraded_sentiment()
            mock_c.return_value = _degraded_conflict()
            mock_p.return_value = _degraded_profanity()
            mock_t.return_value = _degraded_topic()
            # Summary succeeds
            mock_sum.return_value = _make_llm_result()

            orchestrator = LLMOrchestrator()
            result = await orchestrator.run_all_analyses(
                dialogue_text="text",
                session_id="s1",
                include_summary=True,
            )

            assert result.provider == "beeline"
            assert result.summary is not None


# ═══════════════════════════════════════════════════════════
# 8. /api/analysis/full endpoint tests
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def client():
    """Create a TestClient with the FastAPI app."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def session_with_dialogue(client):
    """Create a session with an uploaded dialogue for endpoint tests."""
    from app.utils.session import session_store
    from app.models import ParsedDialog, DialogueTurn

    session = session_store.create()
    session.dialog = ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте, у меня проблема с интернетом"),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день, сейчас проверим"),
            DialogueTurn(turn_index=2, speaker="Клиент", text="Уже третий день не работает!"),
            DialogueTurn(turn_index=3, speaker="Сотрудник", text="Понимаю ваше раздражение, давайте разберёмся"),
        ],
        total_turns=4,
        client_turns=2,
        employee_turns=2,
    )
    session_store.update(session)
    return session.id


class TestFullAnalysisEndpoint:
    """POST /api/analysis/full endpoint tests."""

    def test_full_analysis_happy_path(
        self, client, session_with_dialogue,
    ) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
            patch("app.services.llm.analyze_dialogue", new_callable=AsyncMock) as mock_sum,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()
            mock_sum.return_value = _make_llm_result()

            response = client.post(
                "/api/analysis/full",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "beeline",
                    "include_summary": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_with_dialogue
            assert data["sentiment"] is not None
            assert data["sentiment"]["overall_sentiment"] == "negative"
            assert data["conflict"] is not None
            assert data["profanity"] is not None
            assert data["topic"] is not None
            assert data["summary"] is not None
            assert data["progress"]["current_step"] == "done"
            assert len(data["progress"]["completed_steps"]) == 4
            assert data["progress"]["total_steps"] == 4
            assert data["analysis_source"] == "orchestrator"

    def test_full_analysis_without_summary(
        self, client, session_with_dialogue,
    ) -> None:
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()

            response = client.post(
                "/api/analysis/full",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "beeline",
                    "include_summary": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["summary"] is None
            assert data["sentiment"] is not None

    def test_full_analysis_default_include_summary(
        self, client, session_with_dialogue,
    ) -> None:
        """Default include_summary is True."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
            patch("app.services.llm.analyze_dialogue", new_callable=AsyncMock) as mock_sum,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.return_value = _make_conflict_result()
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()
            mock_sum.return_value = _make_llm_result()

            response = client.post(
                "/api/analysis/full",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "beeline",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["summary"] is not None
            mock_sum.assert_called_once()

    def test_full_analysis_session_not_found(self, client) -> None:
        response = client.post(
            "/api/analysis/full",
            json={
                "session_id": "nonexistent",
                "provider_id": "beeline",
            },
        )
        assert response.status_code == 404

    def test_full_analysis_no_dialogue(self, client) -> None:
        from app.utils.session import session_store
        session = session_store.create()
        response = client.post(
            "/api/analysis/full",
            json={
                "session_id": session.id,
                "provider_id": "beeline",
            },
        )
        assert response.status_code == 400

    def test_full_analysis_partial_failure(
        self, client, session_with_dialogue,
    ) -> None:
        """One step raises — endpoint still returns 200 with partial result."""
        with (
            patch("app.services.llm.analyze_sentiment", new_callable=AsyncMock) as mock_s,
            patch("app.services.llm.analyze_conflict", new_callable=AsyncMock) as mock_c,
            patch("app.services.llm.analyze_profanity", new_callable=AsyncMock) as mock_p,
            patch("app.services.llm.analyze_topic", new_callable=AsyncMock) as mock_t,
        ):
            mock_s.return_value = _make_sentiment_result()
            mock_c.side_effect = ConnectionError("unavailable")
            mock_p.return_value = _make_profanity_result()
            mock_t.return_value = _make_topic_result()

            response = client.post(
                "/api/analysis/full",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "beeline",
                    "include_summary": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            # conflict step failed (exception) — it's in error_steps
            assert "conflict" in data["progress"]["error_steps"]
            assert data["sentiment"] is not None


# ═══════════════════════════════════════════════════════════
# 9. Individual endpoints still work independently
# ═══════════════════════════════════════════════════════════


class TestIndividualEndpointsStillWork:
    """Existing /sentiment, /conflict, /profanity, /topic still work."""

    def test_sentiment_endpoint_still_works(
        self, client, session_with_dialogue,
    ) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "utterances": [
                        {
                            "turn_index": 0,
                            "speaker": "Клиент",
                            "sentiment": "negative",
                            "confidence": 0.9,
                            "text_snippet": "test",
                        },
                    ],
                    "overall_sentiment": "negative",
                    "sentiment_trajectory": "stable",
                }),
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            response = client.post(
                "/api/analysis/sentiment",
                json={"session_id": session_with_dialogue, "provider_id": "ollama"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["overall_sentiment"] == "negative"

    def test_conflict_endpoint_still_works(
        self, client, session_with_dialogue,
    ) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "has_conflict": False,
                    "conflict_level": "none",
                    "escalation_points": [],
                    "de_escalation_attempts": 0,
                    "justification": "No conflict",
                }),
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            response = client.post(
                "/api/analysis/conflict",
                json={"session_id": session_with_dialogue, "provider_id": "ollama"},
            )
            assert response.status_code == 200
            assert response.json()["has_conflict"] is False


# ═══════════════════════════════════════════════════════════
# 10. Config tests
# ═══════════════════════════════════════════════════════════


class TestOrchestratorConfig:
    """Config settings for LLMOrchestrator."""

    def test_default_steps(self) -> None:
        from app.config import settings
        assert settings.llm_orchestrator_steps == ["sentiment", "conflict", "profanity", "topic"]

    def test_default_enabled(self) -> None:
        from app.config import settings
        assert settings.llm_orchestrator_enabled is True

    def test_orchestrator_uses_config_steps(self) -> None:
        """LLMOrchestrator defaults to config steps."""
        from app.config import settings
        orchestrator = LLMOrchestrator()
        assert orchestrator.steps == settings.llm_orchestrator_steps

    def test_orchestrator_custom_steps_override(self) -> None:
        """Custom steps parameter overrides config."""
        orchestrator = LLMOrchestrator(steps=["topic", "sentiment"])
        assert orchestrator.steps == ["topic", "sentiment"]

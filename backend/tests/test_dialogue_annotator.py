"""Tests for the layered DialogueAnnotator.

Covers:
  - empty dialogue (no turns)
  - single layer add (sentiment / profanity / conflict / topic / quality)
  - multi-layer composition
  - length-mismatch tolerance (fewer utterances than turns)
  - out-of-range turn indices are skipped
  - missing layers default to None in build()
  - build() produces a valid AnalysisAnnotation
  - progress info reflects added layers
  - quality is accessible via .quality property (not in annotation)
  - turn_annotations exposes per-turn dicts
"""

from __future__ import annotations

from typing import Any, List

import pytest

from app.models import (
    AnalysisAnnotation,
    CategoryScore,
    ClassifiedError,
    ConflictAnalysisResult,
    DetectedTopic,
    EscalationPoint,
    ProfanityAnalysisResult,
    ProfanityInstance,
    ProgressInfo,
    QualityCategory,
    QualityLevel,
    QualityScoreResult,
    SentimentAnalysisResult,
    TopicAnalysisResult,
    UtteranceSentiment,
)
from app.services.dialogue_annotator import DialogueAnnotator


# ═══════════════════════════════════════════════════════════
# Helpers — factories
# ═══════════════════════════════════════════════════════════


def _turns(n: int) -> List[Any]:
    """Build n simple turn-like objects with turn_index attribute."""
    class _T:
        def __init__(self, i: int) -> None:
            self.turn_index = i
            self.speaker = "Клиент" if i % 2 == 0 else "Сотрудник"
            self.text = f"replica {i}"
    return [_T(i) for i in range(n)]


def _sentiment_result(utterances: List[UtteranceSentiment], **kw: Any) -> SentimentAnalysisResult:
    defaults = {
        "overall_sentiment": "neutral",
        "sentiment_trajectory": "stable",
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return SentimentAnalysisResult(utterances=utterances, **defaults)


def _profanity_result(instances: List[ProfanityInstance], **kw: Any) -> ProfanityAnalysisResult:
    defaults = {"has_profanity": bool(instances), "provider": "beeline", "model": "glm-xlarge"}
    defaults.update(kw)
    return ProfanityAnalysisResult(instances=instances, total_count=len(instances), **defaults)


def _conflict_result(escalation_points: List[EscalationPoint], **kw: Any) -> ConflictAnalysisResult:
    defaults = {
        "has_conflict": bool(escalation_points),
        "conflict_level": "low" if escalation_points else "none",
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return ConflictAnalysisResult(escalation_points=escalation_points, **defaults)


def _topic_result(topics: List[DetectedTopic], **kw: Any) -> TopicAnalysisResult:
    defaults = {
        "primary_topic": topics[0].name if topics else "",
        "topic_count": len(topics),
        "provider": "beeline",
        "model": "glm-xlarge",
    }
    defaults.update(kw)
    return TopicAnalysisResult(topics=topics, **defaults)


def _quality_result() -> QualityScoreResult:
    categories = [
        CategoryScore(category=cat, level=QualityLevel.medium, score=0.66, justification="")
        for cat in QualityCategory
    ]
    return QualityScoreResult(session_id="s1", categories=categories, provider="beeline", model="glm-xlarge")


# ═══════════════════════════════════════════════════════════
# 1. Empty / single-layer
# ═══════════════════════════════════════════════════════════


class TestEmpty:
    def test_empty_dialogue_builds_valid_annotation(self) -> None:
        a = DialogueAnnotator([])
        ann = a.build()
        assert isinstance(ann, AnalysisAnnotation)
        assert ann.session_id == ""
        assert ann.sentiment is None
        assert ann.conflict is None
        assert ann.profanity is None
        assert ann.topic is None
        assert ann.analysis_source == "annotator"
        assert ann.progress.total_steps == 0

    def test_empty_added_layers(self) -> None:
        a = DialogueAnnotator([])
        assert a.added_layers == []
        assert a.failed_layers == []


class TestSingleLayerSentiment:
    def test_sentiment_added(self) -> None:
        turns = _turns(3)
        result = _sentiment_result([
            UtteranceSentiment(turn_index=0, speaker="Клиент", sentiment="negative"),
            UtteranceSentiment(turn_index=1, speaker="Сотрудник", sentiment="positive"),
            UtteranceSentiment(turn_index=2, speaker="Клиент", sentiment="neutral"),
        ])
        a = DialogueAnnotator(turns)
        a.add_sentiment(result)
        assert "sentiment" in a.added_layers
        ann = a.build()
        assert ann.sentiment is result

    def test_sentiment_per_turn_annotations(self) -> None:
        turns = _turns(3)
        result = _sentiment_result([
            UtteranceSentiment(turn_index=0, speaker="Клиент", sentiment="negative"),
            UtteranceSentiment(turn_index=2, speaker="Клиент", sentiment="positive"),
        ])
        a = DialogueAnnotator(turns)
        a.add_sentiment(result)
        ta = a.turn_annotations
        assert ta[0]["sentiment"] == "negative"
        assert ta[1]["sentiment"] is None  # not provided
        assert ta[2]["sentiment"] == "positive"

    def test_sentiment_returns_self_for_chaining(self) -> None:
        a = DialogueAnnotator(_turns(2))
        ret = a.add_sentiment(_sentiment_result([]))
        assert ret is a


class TestSingleLayerProfanity:
    def test_profanity_flags_turns(self) -> None:
        turns = _turns(4)
        result = _profanity_result([
            ProfanityInstance(turn_index=1, speaker="Клиент", category="insult", severity="medium"),
            ProfanityInstance(turn_index=3, speaker="Клиент", category="obscenity", severity="high"),
        ])
        a = DialogueAnnotator(turns)
        a.add_profanity(result)
        ta = a.turn_annotations
        assert ta[0]["profanity"] is False
        assert ta[1]["profanity"] is True
        assert ta[2]["profanity"] is False
        assert ta[3]["profanity"] is True
        ann = a.build()
        assert ann.profanity is result

    def test_profanity_no_instances(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_profanity(_profanity_result([]))
        ta = a.turn_annotations
        assert all(t["profanity"] is False for t in ta)


class TestSingleLayerConflict:
    def test_conflict_marks_escalation_turns(self) -> None:
        turns = _turns(3)
        result = _conflict_result([
            EscalationPoint(turn_index=1, speaker="Клиент", trigger="rude tone", level="medium"),
        ])
        a = DialogueAnnotator(turns)
        a.add_conflict(result)
        ta = a.turn_annotations
        assert ta[0]["conflict_escalation"] is False
        assert ta[1]["conflict_escalation"] is True
        assert ta[2]["conflict_escalation"] is False
        ann = a.build()
        assert ann.conflict is result


class TestSingleLayerTopic:
    def test_topic_tags_turns(self) -> None:
        turns = _turns(4)
        result = _topic_result([
            DetectedTopic(name="Интернет", confidence=0.9, key_phrases=["скорость"], turn_indices=[0, 1]),
            DetectedTopic(name="Биллинг", confidence=0.8, key_phrases=["счёт"], turn_indices=[2, 3]),
        ])
        a = DialogueAnnotator(turns)
        a.add_topic(result)
        ta = a.turn_annotations
        assert ta[0]["topics"] == ["Интернет"]
        assert ta[1]["topics"] == ["Интернет"]
        assert ta[2]["topics"] == ["Биллинг"]
        assert ta[3]["topics"] == ["Биллинг"]
        ann = a.build()
        assert ann.topic is result

    def test_topic_multiple_tags_per_turn(self) -> None:
        turns = _turns(2)
        result = _topic_result([
            DetectedTopic(name="A", confidence=0.9, turn_indices=[0]),
            DetectedTopic(name="B", confidence=0.8, turn_indices=[0, 1]),
        ])
        a = DialogueAnnotator(turns)
        a.add_topic(result)
        ta = a.turn_annotations
        assert ta[0]["topics"] == ["A", "B"]
        assert ta[1]["topics"] == ["B"]


class TestSingleLayerQuality:
    def test_quality_accessible_via_property(self) -> None:
        a = DialogueAnnotator(_turns(2))
        q = _quality_result()
        a.add_quality(q)
        assert a.quality is q
        assert "quality" in a.added_layers

    def test_quality_not_in_annotation(self) -> None:
        """build() does NOT inject quality (AnalysisAnnotation has no field)."""
        a = DialogueAnnotator(_turns(2))
        a.add_quality(_quality_result())
        ann = a.build()
        # No `quality` attribute on AnalysisAnnotation — model extra="ignore"
        assert not hasattr(ann, "quality") or getattr(ann, "quality", None) is None


# ═══════════════════════════════════════════════════════════
# 2. Multi-layer composition
# ═══════════════════════════════════════════════════════════


class TestMultiLayer:
    def test_all_layers_compose(self) -> None:
        turns = _turns(4)
        a = DialogueAnnotator(turns)
        a.add_sentiment(_sentiment_result([
            UtteranceSentiment(turn_index=0, speaker="Клиент", sentiment="negative"),
        ]))
        a.add_profanity(_profanity_result([
            ProfanityInstance(turn_index=1, speaker="Клиент", category="insult", severity="low"),
        ]))
        a.add_conflict(_conflict_result([
            EscalationPoint(turn_index=2, speaker="Клиент", trigger="shouting", level="high"),
        ]))
        a.add_topic(_topic_result([
            DetectedTopic(name="X", confidence=0.9, turn_indices=[3]),
        ]))
        a.add_quality(_quality_result())

        ann = a.build(session_id="s1", provider="beeline", model="glm-xlarge", domain="telecom")

        assert ann.session_id == "s1"
        assert ann.sentiment is not None
        assert ann.conflict is not None
        assert ann.profanity is not None
        assert ann.topic is not None
        assert a.quality is not None
        assert ann.provider == "beeline"
        assert ann.model == "glm-xlarge"
        assert ann.domain == "telecom"
        assert ann.analysis_source == "annotator"

    def test_partial_layers_missing_default_to_none(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_sentiment(_sentiment_result([]))
        ann = a.build()
        assert ann.sentiment is not None
        assert ann.conflict is None
        assert ann.profanity is None
        assert ann.topic is None

    def test_progress_reflects_added_layers(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_sentiment(_sentiment_result([]))
        a.add_topic(_topic_result([]))
        ann = a.build()
        assert set(ann.progress.completed_steps) == {"sentiment", "topic"}
        assert ann.progress.total_steps == 2
        assert ann.progress.error_steps == []
        assert ann.progress.current_step == "done"


# ═══════════════════════════════════════════════════════════
# 3. Length-mismatch tolerance
# ═══════════════════════════════════════════════════════════


class TestLengthMismatch:
    def test_sentiment_fewer_utterances_than_turns(self) -> None:
        """LLM returned 2 utterances for a 4-turn dialogue — missing turns
        keep sentiment=None."""
        turns = _turns(4)
        a = DialogueAnnotator(turns)
        a.add_sentiment(_sentiment_result([
            UtteranceSentiment(turn_index=0, speaker="Клиент", sentiment="negative"),
            UtteranceSentiment(turn_index=1, speaker="Сотрудник", sentiment="positive"),
        ]))
        ta = a.turn_annotations
        assert ta[0]["sentiment"] == "negative"
        assert ta[1]["sentiment"] == "positive"
        assert ta[2]["sentiment"] is None  # missing
        assert ta[3]["sentiment"] is None  # missing

    def test_sentiment_more_utterances_than_turns(self) -> None:
        """LLM returned utterances for turns that don't exist — skipped."""
        turns = _turns(2)
        a = DialogueAnnotator(turns)
        a.add_sentiment(_sentiment_result([
            UtteranceSentiment(turn_index=0, speaker="Клиент", sentiment="negative"),
            UtteranceSentiment(turn_index=1, speaker="Сотрудник", sentiment="positive"),
            UtteranceSentiment(turn_index=5, speaker="Клиент", sentiment="positive"),  # out of range
        ]))
        ta = a.turn_annotations
        assert len(ta) == 2  # extra utterance didn't grow the turn list
        assert ta[0]["sentiment"] == "negative"

    def test_profanity_out_of_range_index_skipped(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_profanity(_profanity_result([
            ProfanityInstance(turn_index=10, speaker="X", category="insult", severity="low"),
        ]))
        ta = a.turn_annotations
        assert all(t["profanity"] is False for t in ta)

    def test_conflict_out_of_range_index_skipped(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_conflict(_conflict_result([
            EscalationPoint(turn_index=99, speaker="X", trigger="t", level="high"),
        ]))
        ta = a.turn_annotations
        assert all(t["conflict_escalation"] is False for t in ta)

    def test_topic_out_of_range_index_skipped(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_topic(_topic_result([
            DetectedTopic(name="X", confidence=0.9, turn_indices=[0, 99]),
        ]))
        ta = a.turn_annotations
        assert ta[0]["topics"] == ["X"]
        assert ta[1]["topics"] == []  # 99 was out of range


# ═══════════════════════════════════════════════════════════
# 4. build() — annotation validity
# ═══════════════════════════════════════════════════════════


class TestBuild:
    def test_returns_analysis_annotation(self) -> None:
        a = DialogueAnnotator(_turns(2))
        ann = a.build()
        assert isinstance(ann, AnalysisAnnotation)

    def test_default_metadata(self) -> None:
        a = DialogueAnnotator(_turns(2))
        ann = a.build()
        assert ann.provider == "none"
        assert ann.model == ""
        assert ann.domain == "general"
        assert ann.analysis_source == "annotator"

    def test_progress_info_type(self) -> None:
        a = DialogueAnnotator(_turns(2))
        a.add_sentiment(_sentiment_result([]))
        ann = a.build()
        assert isinstance(ann.progress, ProgressInfo)
        assert ann.progress.current_step == "done"

    def test_turn_annotations_are_copies(self) -> None:
        """turn_annotations returns independent dicts (no mutation leak)."""
        a = DialogueAnnotator(_turns(2))
        a.add_sentiment(_sentiment_result([
            UtteranceSentiment(turn_index=0, speaker="X", sentiment="positive"),
        ]))
        ta = a.turn_annotations
        ta[0]["sentiment"] = "MUTATED"
        # Internal state is unaffected
        assert a.turn_annotations[0]["sentiment"] == "positive"

    def test_idempotent_layer_add(self) -> None:
        """Adding the same layer twice doesn't duplicate it in added_layers."""
        a = DialogueAnnotator(_turns(2))
        a.add_sentiment(_sentiment_result([]))
        a.add_sentiment(_sentiment_result([]))
        assert a.added_layers.count("sentiment") == 1

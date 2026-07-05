"""Layered dialogue annotation pattern.

Ported from Callytics ``Annotator`` (``text/utils.py``). Applies multiple
analysis layers to a dialogue (turn-by-turn), tolerating length mismatches.
Each layer is independent — failure of one doesn't block others.

Layers
------
* ``sentiment``  — per-turn sentiment + overall + trajectory
* ``profanity``  — per-turn profanity flag + instances list
* ``conflict``   — per-turn escalation flag + overall level
* ``topic``      — per-turn topic tags + overall primary topic
* ``quality``    — overall quality score (not per-turn)

The final :class:`AnalysisAnnotation` is built from whatever layers were
added; missing layers default to ``None`` (graceful degradation).

Per-turn layer data is stored in an internal ``_turns`` list of dicts
(one dict per turn) for inspection via :attr:`turns_with_annotations`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.models import (
    AnalysisAnnotation,
    ConflictAnalysisResult,
    ProgressInfo,
    ProfanityAnalysisResult,
    QualityScoreResult,
    SentimentAnalysisResult,
    TopicAnalysisResult,
)

logger = logging.getLogger(__name__)


class DialogueAnnotator:
    """Applies layered annotations to a dialogue.

    Each layer is optional and independent. Length-mismatch tolerant:
    if a layer returns fewer per-turn items than the dialogue has turns,
    missing items get defaults; if more, the surplus is truncated.

    Example::

        annotator = DialogueAnnotator(turns)
        annotator.add_sentiment(sentiment_result)
        annotator.add_profanity(profanity_result)
        annotator.add_conflict(conflict_result)
        annotator.add_topic(topic_result)
        annotator.add_quality(quality_result)
        annotation = annotator.build()
    """

    def __init__(self, turns: List[Any]) -> None:
        """Initialize the annotator.

        Args:
            turns: List of dialogue turn objects. Each must expose a
                ``turn_index`` attribute (int) — typically
                :class:`app.models.DialogueTurn`. An empty list is
                allowed and produces an empty annotation.
        """
        self.turns: List[Any] = list(turns)

        # Per-turn annotation slots, indexed by turn_index.
        self._turn_annotations: List[Dict[str, Any]] = [
            {
                "turn_index": i,
                "sentiment": None,
                "profanity": False,
                "conflict_escalation": False,
                "topics": [],
            }
            for i in range(len(self.turns))
        ]

        # Overall layer results (None = layer not added).
        self._sentiment: Optional[SentimentAnalysisResult] = None
        self._profanity: Optional[ProfanityAnalysisResult] = None
        self._conflict: Optional[ConflictAnalysisResult] = None
        self._topic: Optional[TopicAnalysisResult] = None
        self._quality: Optional[QualityScoreResult] = None

        # Track which layers were added (for progress info).
        self._added_layers: List[str] = []
        self._failed_layers: List[str] = []

    # ── Layer adders (chainable) ──────────────────────────────

    def add_sentiment(
        self, result: SentimentAnalysisResult,
    ) -> "DialogueAnnotator":
        """Add the sentiment layer.

        Maps per-utterance results to turns by ``turn_index``. If the LLM
        returned fewer utterances than turns, missing turns keep
        ``sentiment=None``; extra utterances are ignored.
        """
        self._sentiment = result
        self._mark_added("sentiment")
        if not result.utterances:
            return self
        for utterance in result.utterances:
            idx = utterance.turn_index
            if 0 <= idx < len(self._turn_annotations):
                self._turn_annotations[idx]["sentiment"] = utterance.sentiment
            else:
                logger.debug(
                    "DialogueAnnotator.add_sentiment: turn_index %d out of "
                    "range (turns=%d) — skipping",
                    idx, len(self._turn_annotations),
                )
        return self

    def add_profanity(
        self, result: ProfanityAnalysisResult,
    ) -> "DialogueAnnotator":
        """Add the profanity layer.

        Marks turns that contain profanity (``profanity=True``) based
        on the ``turn_index`` of each :class:`ProfanityInstance`.
        """
        self._profanity = result
        self._mark_added("profanity")
        for instance in result.instances:
            idx = instance.turn_index
            if 0 <= idx < len(self._turn_annotations):
                self._turn_annotations[idx]["profanity"] = True
            else:
                logger.debug(
                    "DialogueAnnotator.add_profanity: turn_index %d out of "
                    "range — skipping", idx,
                )
        return self

    def add_conflict(
        self, result: ConflictAnalysisResult,
    ) -> "DialogueAnnotator":
        """Add the conflict layer.

        Marks turns listed in ``escalation_points`` with
        ``conflict_escalation=True``.
        """
        self._conflict = result
        self._mark_added("conflict")
        for point in result.escalation_points:
            idx = point.turn_index
            if 0 <= idx < len(self._turn_annotations):
                self._turn_annotations[idx]["conflict_escalation"] = True
            else:
                logger.debug(
                    "DialogueAnnotator.add_conflict: turn_index %d out of "
                    "range — skipping", idx,
                )
        return self

    def add_topic(
        self, result: TopicAnalysisResult,
    ) -> "DialogueAnnotator":
        """Add the topic layer.

        Tags turns with topic names based on each topic's
        ``turn_indices``.
        """
        self._topic = result
        self._mark_added("topic")
        for topic in result.topics:
            for idx in topic.turn_indices:
                if 0 <= idx < len(self._turn_annotations):
                    self._turn_annotations[idx]["topics"].append(topic.name)
                else:
                    logger.debug(
                        "DialogueAnnotator.add_topic: turn_index %d out of "
                        "range — skipping", idx,
                    )
        return self

    def add_quality(
        self, result: QualityScoreResult,
    ) -> "DialogueAnnotator":
        """Add the quality layer (overall, not per-turn).

        Quality scoring is dialogue-level, so it doesn't populate
        per-turn annotations. The result is stored and accessible via
        :attr:`quality`. :meth:`build` does NOT inject quality into the
        returned :class:`AnalysisAnnotation` because that model has no
        ``quality`` field — callers that need it should read
        :attr:`quality` directly.
        """
        self._quality = result
        self._mark_added("quality")
        return self

    # ── Build ─────────────────────────────────────────────────

    def build(
        self,
        session_id: str = "",
        provider: str = "none",
        model: str = "",
        domain: str = "general",
    ) -> AnalysisAnnotation:
        """Build the unified :class:`AnalysisAnnotation`.

        Missing layers are left as ``None`` (graceful degradation). The
        progress info reflects which layers were added successfully.

        Args:
            session_id: Session identifier to embed in the annotation.
            provider: First-successful provider name (caller-supplied).
            model: LLM model identifier (caller-supplied).
            domain: Domain context (general/insurance/...).

        Returns:
            :class:`AnalysisAnnotation` with sentiment / conflict /
            profanity / topic fields populated for added layers and
            ``None`` for the rest.
        """
        added = list(self._added_layers)
        failed = list(self._failed_layers)

        if failed and not added:
            current_step = "done"
        elif failed:
            # Some layers failed but others succeeded — still "done".
            current_step = "done"
        else:
            current_step = "done"

        progress = ProgressInfo(
            current_step=current_step,
            completed_steps=added,
            remaining_steps=[],
            total_steps=len(added) + len(failed),
            error_steps=failed,
        )

        return AnalysisAnnotation(
            session_id=session_id,
            sentiment=self._sentiment,
            conflict=self._conflict,
            profanity=self._profanity,
            topic=self._topic,
            summary=None,
            progress=progress,
            domain=domain,
            provider=provider,
            model=model,
            completed_at="",
            analysis_source="annotator",
        )

    # ── Accessors ─────────────────────────────────────────────

    @property
    def quality(self) -> Optional[QualityScoreResult]:
        """Overall quality result, or ``None`` if not added."""
        return self._quality

    @property
    def turn_annotations(self) -> List[Dict[str, Any]]:
        """Per-turn annotation dicts (read-only view).

        Each dict has keys: ``turn_index``, ``sentiment``,
        ``profanity``, ``conflict_escalation``, ``topics``.
        """
        return [dict(t) for t in self._turn_annotations]

    @property
    def added_layers(self) -> List[str]:
        """Layers that were added successfully (ordered)."""
        return list(self._added_layers)

    @property
    def failed_layers(self) -> List[str]:
        """Layers that failed (always empty unless extended)."""
        return list(self._failed_layers)

    # ── Internal ──────────────────────────────────────────────

    def _mark_added(self, layer: str) -> None:
        """Record a layer as added (idempotent — no duplicates)."""
        if layer not in self._added_layers:
            self._added_layers.append(layer)


__all__ = ["DialogueAnnotator"]

"""Tests for _fallback_match (bag-of-words fallback matching).

Covers acceptance criteria for UI-2.5 Parser Rewrite — Batch D:
  - _fallback_match returns List[Tuple[int, str, dict]] (turn_idx, speaker, detail_dict)
  - detail_dict contains matched_text, matched_start, matched_end
  - BOW matching: free word order within the window
  - Greedy one-to-one: each window word matches at most one phrase word
  - Channel constraint filtering (CLIENT/OPERATOR/ANY)
  - WordDistance: intermediate words allowed between phrase words
  - Empty phrase, no match, single match per turn, multiple turns

The _fallback_match is triggered when morph_matcher / smartlogger are unavailable.
It uses simple bag-of-words with exact string comparison (no morphology).
Word order is FREE (per SmartLogger spec [4]).

NOTE: _fallback_match does NOT honour is_exact — it always uses BOW.
The is_exact flag is only used by the morph_matcher path (match_phrase_morphological_detailed).
"""

from __future__ import annotations

import sys
import os

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models import DictionaryCondition, DictionaryNode, PhraseGroup, \
    ParsedDialog, DialogueTurn
from app.services.search import (
    _fallback_match,
    evaluate_phrase_logic_tree,
    run_hierarchical_search,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _make_condition(
    text: str,
    word_distance: int = 2,
    channel: str = "ANY",
    is_exact: bool = False,
    without_list: list[str] | None = None,
) -> DictionaryCondition:
    """Helper to create a DictionaryCondition."""
    return DictionaryCondition(
        text=text,
        word_distance=word_distance,
        word_count=len(text.split()),
        channel_constraint=channel,
        is_exact=is_exact,
        without_list=without_list or [],
    )


def _make_turns(*pairs: tuple[str, str]) -> list[dict]:
    """Helper: list of (speaker, text) → [{'speaker': ..., 'text': ...}]."""
    return [{"speaker": speaker, "text": text} for speaker, text in pairs]


def _make_channel_map(turns: list[dict]) -> dict[int, str]:
    """Helper: turn index → speaker mapping."""
    return {i: t["speaker"] for i, t in enumerate(turns)}


# ═══════════════════════════════════════════════════════════════════════
# 1. Return signature: List[Tuple[int, str, dict]]
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackReturnSignature:
    """Verify _fallback_match returns List[Tuple[int, str, dict]] with detail keys."""

    def test_returns_list_of_tuples(self) -> None:
        """Result is a list of (int, str, dict) tuples."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert isinstance(result, list)
        assert len(result) == 1
        turn_idx, speaker, detail = result[0]
        assert isinstance(turn_idx, int)
        assert isinstance(speaker, str)
        assert isinstance(detail, dict)

    def test_detail_has_matched_text(self) -> None:
        """detail_dict contains 'matched_text' key."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        assert "matched_text" in detail
        assert "отказ" in detail["matched_text"]

    def test_detail_has_matched_start(self) -> None:
        """detail_dict contains 'matched_start' (int >= 0 for a real match)."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        assert "matched_start" in detail
        assert isinstance(detail["matched_start"], int)
        assert detail["matched_start"] >= 0

    def test_detail_has_matched_end(self) -> None:
        """detail_dict contains 'matched_end' (int >= 0 for a real match)."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        assert "matched_end" in detail
        assert isinstance(detail["matched_end"], int)
        assert detail["matched_end"] >= 0

    def test_matched_offsets_correct(self) -> None:
        """matched_start/matched_end point to the actual matched substring."""
        condition = _make_condition("отказ", is_exact=False)
        turn_text = "я отказ от услуги"
        turns = _make_turns(("Клиент", turn_text))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        start = detail["matched_start"]
        end = detail["matched_end"]
        assert turn_text[start:end] == detail["matched_text"]
        assert "отказ" in turn_text[start:end]


# ═══════════════════════════════════════════════════════════════════════
# 2. BOW match — free word order (core BOW behaviour)
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackBowReordering:
    """BOW matching: phrase words can appear in ANY ORDER in the window."""

    def test_reversed_order_bow_matches(self) -> None:
        """BOW: 'не хочу' matches 'хочу не' (reversed order)."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "я хочу не подключать"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        assert "хочу" in detail["matched_text"]
        assert "не" in detail["matched_text"]

    def test_scrambled_order_bow_matches(self) -> None:
        """BOW: 'отказ от диагностики' matches 'диагностики от отказ'."""
        condition = _make_condition("отказ от диагностики", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "диагностики от отказ"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_bow_succeeds_where_sequential_fails(self) -> None:
        """Explicit: phrase 'отказываюсь платить' matches 'платить отказываюсь' via BOW."""
        condition = _make_condition("отказываюсь платить", is_exact=False, word_distance=3)
        turns = _make_turns(("Клиент", "платить отказываюсь"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_word_reorder_russian(self) -> None:
        """BOW: 'не устраивает меня' matches 'меня не устраивает' (reordered)."""
        condition = _make_condition("не устраивает меня", is_exact=False, word_distance=3)
        turns = _make_turns(("Клиент", "меня не устраивает"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_word_reorder_threat(self) -> None:
        """BOW: 'риск расторжения' matches 'расторжения риск' (reordered)."""
        condition = _make_condition("риск расторжения", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "расторжения риск договора"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════
# 3. Exact string match (no morphology)
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackExactStringMatch:
    """_fallback_match uses exact string comparison (no morphology / no same_lemma).

    'подключил' does NOT match 'подключивать' because there is no lemmatization.
    Only exact lowercase string equality is used.
    """

    def test_exact_form_matches(self) -> None:
        """Exact form: 'отказ' matches 'отказ'."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_morphological_variant_not_matched(self) -> None:
        """'подключил' does NOT match phrase 'подключивать' (no lemmatization in fallback)."""
        condition = _make_condition("подключивать", is_exact=False)
        turns = _make_turns(("Клиент", "я подключил услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0, "Fallback uses exact string match — no morphology"

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive (both lowercased)."""
        condition = _make_condition("Отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я ОТКАЗ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════
# 4. Greedy one-to-one matching
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackBowGreedyOneToOne:
    """Greedy one-to-one: each window word can only match ONE phrase word."""

    def test_same_word_twice_needs_two_instances(self) -> None:
        """Phrase 'не не' requires TWO instances of 'не' in the window."""
        condition = _make_condition("не не", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "я не хочу"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0, "Should not match: only one 'не' for two 'не' in phrase"

    def test_same_word_twice_with_two_instances(self) -> None:
        """Phrase 'не не' matches when TWO instances of 'не' exist in window."""
        condition = _make_condition("не не", is_exact=False, word_distance=4)
        turns = _make_turns(("Клиент", "я не хочу не подключать"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1, "Should match: two 'не' instances available"

    def test_partial_match_fails(self) -> None:
        """Phrase with 3 words, only 2 present → no result."""
        condition = _make_condition("отказ от диагностики", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════
# 5. Channel constraint filtering
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackChannelConstraint:
    """Channel constraint filters by speaker role."""

    def test_client_constraint_matches_client(self) -> None:
        """channel_constraint=CLIENT: matches when speaker is 'Клиент'."""
        condition = _make_condition("отказ", is_exact=False, channel="CLIENT")
        turns = _make_turns(("Клиент", "я отказ"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_client_constraint_skips_operator(self) -> None:
        """channel_constraint=CLIENT: skips when speaker is 'Сотрудник'."""
        condition = _make_condition("отказ", is_exact=False, channel="CLIENT")
        turns = _make_turns(("Сотрудник", "я отказ"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0

    def test_operator_constraint_matches_operator(self) -> None:
        """channel_constraint=OPERATOR: matches when speaker is 'Сотрудник'."""
        condition = _make_condition("отказ", is_exact=False, channel="OPERATOR")
        turns = _make_turns(("Сотрудник", "я отказ"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_operator_constraint_skips_client(self) -> None:
        """channel_constraint=OPERATOR: skips when speaker is 'Клиент'."""
        condition = _make_condition("отказ", is_exact=False, channel="OPERATOR")
        turns = _make_turns(("Клиент", "я отказ"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0

    def test_any_constraint_matches_both(self) -> None:
        """channel_constraint=ANY: matches any speaker."""
        condition = _make_condition("отказ", is_exact=False, channel="ANY")
        turns = _make_turns(
            ("Клиент", "отказ"),
            ("Сотрудник", "отказ"),
        )
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 2

    def test_channel_filter_skips_non_matching_turns(self) -> None:
        """CLIENT constraint: only CLIENT turns are searched."""
        condition = _make_condition("отказ", is_exact=False, channel="CLIENT")
        turns = _make_turns(
            ("Сотрудник", "отказ"),
            ("Клиент", "отказ"),
        )
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        assert result[0][0] == 1  # turn index 1 (Клиент)


# ═══════════════════════════════════════════════════════════════════════
# 6. WordDistance — intermediate words allowed
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackWordDistance:
    """word_distance allows extra words between phrase words in the window."""

    def test_word_distance_allows_gap(self) -> None:
        """phrase 'не хочу' with word_distance=2 matches 'не очень хочу'."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "не очень хочу"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_word_distance_zero_same_order(self) -> None:
        """word_distance=0: window = exactly phrase words (same order)."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=0)
        turns = _make_turns(("Клиент", "не хочу"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_word_distance_zero_reversed_bow(self) -> None:
        """word_distance=0: reversed 'хочу не' still matches via BOW (free order)."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=0)
        turns = _make_turns(("Клиент", "хочу не"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1, "BOW with distance=0: window is exactly the phrase words"

    def test_word_distance_too_small_no_match(self) -> None:
        """word_distance=0: 'не очень хочу' doesn't match (window too small)."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=0)
        turns = _make_turns(("Клиент", "не очень хочу"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0, "window_size=2, turn has 3 words, gap too large"

    def test_phrase_with_gap(self) -> None:
        """BOW: 'не буду платить' matches 'не буду я платить' (gap with 'я')."""
        condition = _make_condition("не буду платить", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "не буду я платить"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════
# 7. Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackEdgeCases:
    """Edge cases for _fallback_match."""

    def test_empty_phrase_no_match(self) -> None:
        """Empty phrase → no matches."""
        condition = _make_condition("", is_exact=False)
        turns = _make_turns(("Клиент", "привет"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0

    def test_single_word_phrase(self) -> None:
        """Single-word phrase matches correctly."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ от услуги"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_no_matching_turn(self) -> None:
        """No turn contains the phrase words → empty result."""
        condition = _make_condition("расторжение", is_exact=False)
        turns = _make_turns(("Клиент", "привет как дела"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0

    def test_one_match_per_turn(self) -> None:
        """BOW: only one match per turn (break after first match)."""
        condition = _make_condition("не", is_exact=False)
        turns = _make_turns(("Клиент", "не хочу не буду не знаю"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1, "Only one match per turn expected"

    def test_multiple_turns_each_match_once(self) -> None:
        """BOW: multiple turns each produce one match."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(
            ("Клиент", "я отказ"),
            ("Сотрудник", "какой отказ"),
        )
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 2

    def test_turn_too_short_skipped(self) -> None:
        """Turn with fewer words than phrase → skipped."""
        condition = _make_condition("не хочу подключивать", is_exact=False, word_distance=0)
        turns = _make_turns(("Клиент", "не хочу"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0

    def test_empty_turns_list(self) -> None:
        """Empty turns list → empty result."""
        condition = _make_condition("отказ", is_exact=False)
        channel_map: dict[int, str] = {}

        result = _fallback_match(condition, [], channel_map)

        assert len(result) == 0

    def test_same_word_repeated_in_phrase_sufficient(self) -> None:
        """Phrase 'не хочу не буду' with two 'не' in turn → match."""
        condition = _make_condition("не хочу не буду", is_exact=False, word_distance=3)
        turns = _make_turns(("Клиент", "я не хочу я не буду"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1

    def test_same_word_repeated_insufficient(self) -> None:
        """Phrase with 2x 'не' doesn't match turn with 1x 'не'."""
        condition = _make_condition("не не", is_exact=False, word_distance=2)
        turns = _make_turns(("Клиент", "я не хочу"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════
# 8. matched_text / matched_start / matched_end correctness
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackMatchDetailCorrectness:
    """Verify matched_text, matched_start, matched_end are geometrically correct."""

    def test_single_word_offsets(self) -> None:
        """Single word 'отказ' at position 2 in 'я отказ от услуги'."""
        condition = _make_condition("отказ", is_exact=False)
        turn_text = "я отказ от услуги"
        turns = _make_turns(("Клиент", turn_text))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        assert detail["matched_text"] == "отказ"
        assert turn_text[detail["matched_start"]:detail["matched_end"]] == "отказ"

    def test_multi_word_phrase_span(self) -> None:
        """Two-word phrase span covers from first to last matched word."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=2)
        turn_text = "я не очень хочу подключать"
        turns = _make_turns(("Клиент", turn_text))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        # matched_text spans from 'не' to 'хочу' inclusive
        assert "не" in detail["matched_text"]
        assert "хочу" in detail["matched_text"]
        assert turn_text[detail["matched_start"]:detail["matched_end"]] == detail["matched_text"]

    def test_reversed_order_span_correct(self) -> None:
        """Reversed order 'хочу не' → span covers 'хочу' to 'не'."""
        condition = _make_condition("не хочу", is_exact=False, word_distance=2)
        turn_text = "хочу не"
        turns = _make_turns(("Клиент", turn_text))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, _sp, detail = result[0]
        assert turn_text[detail["matched_start"]:detail["matched_end"]] == detail["matched_text"]

    def test_speaker_returned_correctly(self) -> None:
        """The speaker string in the tuple matches channel_map."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(("Клиент", "я отказ"))
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        _idx, speaker, _detail = result[0]
        assert speaker == "Клиент"

    def test_turn_index_returned_correctly(self) -> None:
        """The turn index in the tuple is correct for multi-turn dialogues."""
        condition = _make_condition("отказ", is_exact=False)
        turns = _make_turns(
            ("Клиент", "привет"),
            ("Сотрудник", "здравствуйте"),
            ("Клиент", "я отказ"),
        )
        channel_map = _make_channel_map(turns)

        result = _fallback_match(condition, turns, channel_map)

        assert len(result) == 1
        turn_idx, _sp, _detail = result[0]
        assert turn_idx == 2


# ═══════════════════════════════════════════════════════════════════════
# 9. phrase_logic_tree GATE (N15) — logic-tree-driven cascade GATE
# ═══════════════════════════════════════════════════════════════════════


def _make_dialog(turns: list[tuple[str, str]]) -> ParsedDialog:
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=i, text=text, speaker=speaker)
            for i, (speaker, text) in enumerate(turns)
        ],
    )


class TestPhraseLogicTreeGate:
    """UI-2.6 N15: the GATE for child nodes now uses the phrase_logic_tree
    (ALL AND-children must match, ANY OR-child must match), instead of the
    legacy "any positive match opens the gate" semantics.
    """

    @pytest.mark.asyncio
    async def test_and_gate_requires_both_phrases_to_open(self) -> None:
        """Node with A И B: child searched only if BOTH A and B matched.

        With the legacy "any match" semantics, matching just A would open
        the GATE. With the new logic-tree GATE, AND requires both.
        """
        dialog = _make_dialog([
            ("Клиент", "alpha"),  # only A matches
            ("Клиент", "child_search_marker"),
        ])

        child = DictionaryNode(
            id="child", name="Child",
            conditions=[_make_condition("child_search_marker", channel="CLIENT")],
            children=[],
        )
        # Parent has phrase_groups encoding A И B (operator=AND on B)
        parent = DictionaryNode(
            id="parent", name="Parent",
            conditions=[
                _make_condition("alpha", channel="CLIENT"),
                _make_condition("beta", channel="CLIENT"),
            ],
            phrase_groups=[
                PhraseGroup(words=["alpha"]),
                PhraseGroup(words=["beta"], operator="AND"),
            ],
            children=[child],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[parent], cascade=False,
        )

        # Only A matched → AND gate NOT satisfied → child NOT searched
        child_matches = [m for m in result.matches if m.quarter == "Child"]
        assert len(child_matches) == 0, (
            "AND gate must require BOTH phrases — child should not be searched"
        )

    @pytest.mark.asyncio
    async def test_and_gate_opens_when_both_phrases_matched(self) -> None:
        """Node with A И B: when both A and B matched somewhere, child is searched."""
        dialog = _make_dialog([
            ("Клиент", "alpha beta"),  # both match here
            ("Клиент", "child_marker"),
        ])

        child = DictionaryNode(
            id="child", name="Child",
            conditions=[_make_condition("child_marker", channel="CLIENT")],
            children=[],
        )
        parent = DictionaryNode(
            id="parent", name="Parent",
            conditions=[
                _make_condition("alpha", channel="CLIENT"),
                _make_condition("beta", channel="CLIENT"),
            ],
            phrase_groups=[
                PhraseGroup(words=["alpha"]),
                PhraseGroup(words=["beta"], operator="AND"),
            ],
            children=[child],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[parent], cascade=False,
        )

        child_matches = [m for m in result.matches if m.quarter == "Child"]
        assert len(child_matches) == 1, (
            "AND gate satisfied (both matched) → child should be searched"
        )

    @pytest.mark.asyncio
    async def test_or_gate_opens_with_either_phrase(self) -> None:
        """Node with A ИЛИ B: matching just A is enough to open the gate."""
        dialog = _make_dialog([
            ("Клиент", "alpha"),  # only A
            ("Клиент", "child_marker"),
        ])

        child = DictionaryNode(
            id="child", name="Child",
            conditions=[_make_condition("child_marker", channel="CLIENT")],
            children=[],
        )
        parent = DictionaryNode(
            id="parent", name="Parent",
            conditions=[
                _make_condition("alpha", channel="CLIENT"),
                _make_condition("beta", channel="CLIENT"),
            ],
            phrase_groups=[
                PhraseGroup(words=["alpha"]),
                PhraseGroup(words=["beta"], operator="OR"),
            ],
            children=[child],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[parent], cascade=False,
        )

        child_matches = [m for m in result.matches if m.quarter == "Child"]
        assert len(child_matches) == 1, (
            "OR gate opens with EITHER phrase — A alone is enough"
        )

    @pytest.mark.asyncio
    async def test_or_gate_does_not_open_when_neither_matched(self) -> None:
        """Node with A ИЛИ B: if neither A nor B matched, child is NOT searched."""
        dialog = _make_dialog([
            ("Клиент", "gamma"),  # neither A nor B
            ("Клиент", "child_marker"),
        ])

        child = DictionaryNode(
            id="child", name="Child",
            conditions=[_make_condition("child_marker", channel="CLIENT")],
            children=[],
        )
        parent = DictionaryNode(
            id="parent", name="Parent",
            conditions=[
                _make_condition("alpha", channel="CLIENT"),
                _make_condition("beta", channel="CLIENT"),
            ],
            phrase_groups=[
                PhraseGroup(words=["alpha"]),
                PhraseGroup(words=["beta"], operator="OR"),
            ],
            children=[child],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[parent], cascade=False,
        )

        child_matches = [m for m in result.matches if m.quarter == "Child"]
        assert len(child_matches) == 0, (
            "OR gate stays closed when no operand matched"
        )


# ═══════════════════════════════════════════════════════════════════════
# 10. evaluate_phrase_logic_tree — direct unit-level contract
# ═══════════════════════════════════════════════════════════════════════


class TestEvaluatePhraseLogicTreeContract:
    """Direct tests for evaluate_phrase_logic_tree (no run_hierarchical_search)."""

    def test_empty_phrase_groups_returns_true(self) -> None:
        assert evaluate_phrase_logic_tree([], set()) is True

    def test_single_phrase(self) -> None:
        groups = [PhraseGroup(words=["a"])]
        assert evaluate_phrase_logic_tree(groups, {"a"}) is True
        assert evaluate_phrase_logic_tree(groups, set()) is False

    def test_and_combination(self) -> None:
        groups = [
            PhraseGroup(words=["a"]),
            PhraseGroup(words=["b"], operator="AND"),
        ]
        assert evaluate_phrase_logic_tree(groups, {"a", "b"}) is True
        assert evaluate_phrase_logic_tree(groups, {"a"}) is False

    def test_or_combination(self) -> None:
        groups = [
            PhraseGroup(words=["a"]),
            PhraseGroup(words=["b"], operator="OR"),
        ]
        assert evaluate_phrase_logic_tree(groups, {"a"}) is True
        assert evaluate_phrase_logic_tree(groups, {"b"}) is True
        assert evaluate_phrase_logic_tree(groups, set()) is False

    def test_not_combination(self) -> None:
        groups = [PhraseGroup(words=["x"], is_negated=True)]
        assert evaluate_phrase_logic_tree(groups, set()) is True
        assert evaluate_phrase_logic_tree(groups, {"x"}) is False

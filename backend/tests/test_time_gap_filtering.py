"""Tests for the time-gap filter (`_apply_time_gap_filter`).

Ground truth semantics (confirmed against the SmartLogger test dictionary
at `data/input/ins/sample_limitations.xml`):

  - `SearchSpecifier` is a filter MODE, not a silence-gap detector:
      * `OnlyInGaps`  = INCLUDE — keep only matches inside the window.
      * `ExcludeGaps` = EXCLUDE — drop matches inside the window.
  - The window is defined by `<Limit>`:
      * `StartEnd + LimitType=First|Last` anchors the window at the start/end
        of the dialogue (or channel's first/last turn).
      * `ValueType=Seconds` — time window [anchor, anchor ± N].
      * `ValueType=Words`   — time window bounded by the N-th channel word.
      * `ValueType=Phrases` — first/last N channel turns (turn-index based).
      * `Channel=CLIENT|OPERATOR` scopes word/phrase/turn counting to that
        speaker; `Channel=ANY` counts all speakers in dialogue order.
      * `Parent + SearchDirection=Before|After + EventSelector=First|Last|Each`
        anchors the window on parent matches.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import ExtraLimitation, ExtraLimitationLimit
from app.services.search import (
    _apply_time_gap_filter,
    _has_timestamps,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _turn(
    speaker: str,
    text: str,
    start: float,
    end: float,
) -> dict:
    """Build a smartlogger-format turn dict with timing."""
    return {
        "speaker": speaker,
        "text": text,
        "start_offset": start,
        "end_offset": end,
    }


def _match(turn_idx: int, speaker: str = "Клиент") -> tuple:
    """Build a (turn_idx, speaker, detail) match tuple."""
    return (turn_idx, speaker, {"matched_text": "x", "matched_start": -1, "matched_end": -1})


def _el(
    event_type: str = "",
    search_specifier: str = "",
    limits=None,
) -> ExtraLimitation:
    return ExtraLimitation(
        event_type=event_type,
        search_specifier=search_specifier,
        limits=limits or [],
    )


def _limit(
    value: int = 0,
    *,
    value_type: str = "Seconds",
    channel: str = "ANY",
    enabled: bool = True,
    limit_type=None,
    event_selector=None,
    search_direction=None,
) -> ExtraLimitationLimit:
    return ExtraLimitationLimit(
        value=value,
        value_type=value_type,
        channel=channel,
        enabled=enabled,
        limit_type=limit_type,
        event_selector=event_selector,
        search_direction=search_direction,
    )


# Dialogue fixture: 5 turns spanning 0..60 seconds.
#   t0  Клиент     [0,   5]   "привет всем"                  (2 words)
#   t1  Сотрудник  [5,   10]   "здравствуйте"                 (1 word)
#   t2  Клиент     [25,  30]   "хочу расторгнуть договор"     (3 words)
#   t3  Сотрудник  [30,  35]   "давайте обсудим"              (2 words)
#   t4  Клиент     [55,  60]   "отказываюсь"                  (1 word)
# Total words (ANY): 9.  CLIENT words: 6.  OPERATOR phrases: 2 (t1, t3).
DIALOG_TURNS = [
    _turn("Клиент", "привет всем", 0.0, 5.0),
    _turn("Сотрудник", "здравствуйте", 5.0, 10.0),
    _turn("Клиент", "хочу расторгнуть договор", 25.0, 30.0),
    _turn("Сотрудник", "давайте обсудим", 30.0, 35.0),
    _turn("Клиент", "отказываюсь", 55.0, 60.0),
]


# ═══════════════════════════════════════════════════════════════════════
# 1. EventType=StartEnd + ValueType=Seconds
# ═══════════════════════════════════════════════════════════════════════


class TestStartEndSeconds:
    def test_exclude_first_10_seconds_any(self) -> None:
        """ExcludeGaps, First, 10s, ANY → drop matches in [0..10]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=10, value_type="Seconds", channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t0 [0,5] and t1 [5,10] intersect [0,10] → excluded.
        assert [m[0] for m in result] == [2, 3, 4]

    def test_only_in_first_10_seconds_any(self) -> None:
        """OnlyInGaps, First, 10s, ANY → keep matches intersecting [0..10]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=10, value_type="Seconds", channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [0, 1]

    def test_only_in_last_15_seconds_any(self) -> None:
        """OnlyInGaps, Last, 15s, ANY → keep matches intersecting [45..60]."""
        matches = [_match(0), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=15, value_type="Seconds", channel="ANY", limit_type="Last")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Only t4 [55,60] intersects [45,60].
        assert [m[0] for m in result] == [4]

    def test_only_in_first_seconds_client(self) -> None:
        """Channel=CLIENT, First, 10s → window [0, 10] (first client turn start=0)."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=10, value_type="Seconds", channel="CLIENT", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t0 [0,5] intersects [0,10] → kept. t2/t4 outside.
        assert [m[0] for m in result] == [0]


# ═══════════════════════════════════════════════════════════════════════
# 2. EventType=StartEnd + ValueType=Words
# ═══════════════════════════════════════════════════════════════════════


class TestStartEndWords:
    def test_exclude_first_10_words_any(self) -> None:
        """ExcludeGaps, First, 10 words, ANY → drop all (only 9 words total)."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=10, value_type="Words", channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # All 9 words fall inside the first-10-words window → all excluded.
        assert result == []

    def test_only_in_first_3_words_any(self) -> None:
        """OnlyInGaps, First, 3 words, ANY → window [0, end_of_3rd_word=10]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=3, value_type="Words", channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Words: t0 has 2 ("привет всем"), t1 has 1 ("здравствуйте") → 3rd word ends at t1.end=10.
        # Window = [0, 10]. t0 [0,5] and t1 [5,10] intersect → kept.
        assert [m[0] for m in result] == [0, 1]

    def test_only_in_last_2_words_any(self) -> None:
        """OnlyInGaps, Last, 2 words, ANY → window [start_of_8th_word=30, 60]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=2, value_type="Words", channel="ANY", limit_type="Last")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Words in order: t0(2), t1(1), t2(3), t3(2), t4(1). Total=9.
        # Last 2 words start at word #8 = 2nd word of t3 (start of t3=30).
        # Window = [30, 60]. Turns intersecting: t2 [25,30] (touches 30),
        # t3 [30,35], t4 [55,60].
        assert [m[0] for m in result] == [2, 3, 4]

    def test_only_in_first_2_words_client(self) -> None:
        """Channel=CLIENT, First, 2 words → window [0, end_of_2nd_client_word].

        CLIENT turns: t0 "привет всем" (2 words). 2nd client word ends at t0.end=5.
        Window = [0, 5]. t0 [0,5] and t1 [5,10] both intersect (touch at 5).
        """
        matches = [_match(0), _match(1), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=2, value_type="Words", channel="CLIENT", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [0, 1]


# ═══════════════════════════════════════════════════════════════════════
# 3. EventType=StartEnd + ValueType=Phrases
# ═══════════════════════════════════════════════════════════════════════


class TestStartEndPhrases:
    def test_exclude_first_10_phrases_operator(self) -> None:
        """ExcludeGaps, First, 10 phrases, OPERATOR → drop operator turns.

        OPERATOR turns: t1, t3 (2 turns total, both within first 10).
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=10, value_type="Phrases", channel="OPERATOR", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [0, 2, 4]

    def test_only_in_first_2_phrases_any(self) -> None:
        """OnlyInGaps, First, 2 phrases, ANY → keep turns [0,1]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=2, value_type="Phrases", channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [0, 1]

    def test_only_in_last_2_phrases_any(self) -> None:
        """OnlyInGaps, Last, 2 phrases, ANY → keep turns [3,4]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=2, value_type="Phrases", channel="ANY", limit_type="Last")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [3, 4]


# ═══════════════════════════════════════════════════════════════════════
# 4. EventType=Parent
# ═══════════════════════════════════════════════════════════════════════


class TestParent:
    def test_only_in_before_each_5s(self) -> None:
        """OnlyInGaps, Parent, Before, Each, 5s → keep matches intersecting
        union of windows [20,25] and [50,55]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=5, value_type="Seconds", channel="ANY",
                          event_selector="Each", search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[25.0, 55.0]
        )
        # t2 [25,30] intersects [20,25]; t4 [55,60] intersects [50,55].
        assert [m[0] for m in result] == [2, 4]

    def test_only_in_after_first_5s(self) -> None:
        """OnlyInGaps, Parent, After, First, 5s → window [25, 30] for first parent."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=5, value_type="Seconds", channel="ANY",
                          event_selector="First", search_direction="After")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[25.0, 55.0]
        )
        # Window [25, 30]: t2 [25,30] and t3 [30,35] both intersect (touch at 30).
        assert [m[0] for m in result] == [2, 3]

    def test_exclude_before_each_5s(self) -> None:
        """ExcludeGaps, Parent, Before, Each, 5s → drop matches intersecting
        union of [20,25] and [50,55]."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=5, value_type="Seconds", channel="ANY",
                          event_selector="Each", search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[25.0, 55.0]
        )
        # Drop t2 (intersects [20,25]) and t4 (intersects [50,55]).
        assert [m[0] for m in result] == [0, 1, 3]

    def test_only_in_before_last_5s(self) -> None:
        """EventSelector=Last → only last parent match anchors the window."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=5, value_type="Seconds", channel="ANY",
                          event_selector="Last", search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[25.0, 55.0]
        )
        # Only last parent (55) → window [50, 55]. t4 [55,60] intersects → kept.
        assert [m[0] for m in result] == [4]

    def test_parent_filter_skipped_when_no_parent_match_times(self) -> None:
        """parent_match_times=None → Parent filter is a no-op."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="Parent",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=5, search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=None
        )
        assert result == matches


# ═══════════════════════════════════════════════════════════════════════
# 5. Defensive no-ops
# ═══════════════════════════════════════════════════════════════════════


class TestNoOpCases:
    def test_turns_without_offsets_skip_filter(self) -> None:
        """When no turn has start_offset, filter returns matches unchanged."""
        turns_no_ts = [
            {"speaker": "Клиент", "text": "a", "start_offset": None, "end_offset": None},
            {"speaker": "Сотрудник", "text": "b", "start_offset": None, "end_offset": None},
        ]
        matches = [_match(0), _match(1)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=10, channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, turns_no_ts, [el])
        assert result == matches

    def test_has_timestamps_detects_any_turn_with_offset(self) -> None:
        assert _has_timestamps(DIALOG_TURNS) is True
        assert _has_timestamps([{"speaker": "x", "start_offset": None}]) is False
        assert _has_timestamps([]) is False

    def test_empty_list_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [])
        assert result == matches

    def test_extra_limitation_with_no_limits_skipped(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(event_type="StartEnd", search_specifier="OnlyInGaps", limits=[])
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_disabled_limit_skipped(self) -> None:
        """limit.enabled=False → that Limit is skipped."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=10, channel="ANY", limit_type="First", enabled=False)],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_unknown_event_type_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(
            event_type="WeirdFutureEventType",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=10, channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_empty_event_type_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(
            event_type="",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=10, channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_unknown_search_specifier_returns_matches_unchanged(self) -> None:
        """Only OnlyInGaps / ExcludeGaps are recognized filter modes."""
        matches = [_match(0), _match(2)]
        el = _el(
            event_type="StartEnd",
            search_specifier="SomethingElse",
            limits=[_limit(value=10, channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_unknown_value_type_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=10, value_type="Milliseconds", channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_empty_matches_returns_empty(self) -> None:
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=10, channel="ANY", limit_type="First")],
        )
        result = _apply_time_gap_filter([], DIALOG_TURNS, [el])
        assert result == []


# ═══════════════════════════════════════════════════════════════════════
# 6. Multiple ExtraLimitations combine as AND
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleExtraLimitations:
    def test_two_extra_limitations_apply_sequentially(self) -> None:
        """First: only-in first 30s → t0,t1,t2,t3.
        Second: only-in last 30s → of remaining, keep those with end>=30 → t2,t3.
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        els = [
            _el(
                event_type="StartEnd", search_specifier="OnlyInGaps",
                limits=[_limit(value=30, channel="ANY", limit_type="First")],
            ),
            _el(
                event_type="StartEnd", search_specifier="OnlyInGaps",
                limits=[_limit(value=30, channel="ANY", limit_type="Last")],
            ),
        ]
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, els)
        # First 30s window [0,30]: t0,t1,t2,t3 intersect (t3 [30,35] intersects at 30).
        # Of those, last 30s window [30,60]: t2 [25,30] intersects at 30; t3 [30,35] intersects.
        assert [m[0] for m in result] == [2, 3]

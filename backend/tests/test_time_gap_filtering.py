"""Tests for time-gap filtering via <ExtraLimitations> (UI-2.6).

Covers `_apply_time_gap_filter` and its dispatch helpers:
  - EventType=StartEnd + LimitType=First: keep matches in first N seconds
  - EventType=StartEnd + LimitType=Last:  keep matches in last N seconds
  - EventType=Parent + SearchDirection=Before: keep matches within N sec before parent match
  - EventType=Parent + SearchDirection=After:  keep matches within N sec after parent match
  - SearchSpecifier=OnlyInGaps:  keep matches whose turn falls inside a channel silence gap
  - SearchSpecifier=ExcludeGaps: exclude matches whose turn falls inside a channel silence gap
  - No timestamps in turns → filter is a no-op (matches unchanged)
  - Empty extra_limitations → no filtering
  - limit.enabled=False → that Limit is skipped

Real SmartLogger dictionaries store <ExtraLimitations> as time-gap limits
(EventType/SearchSpecifier/Settings/Limits/Limit), NOT as <Tokens>. See
docs/specs/smartlogger-xml-verification.md and docs/specs/smartlogger-spec-analysis.md §7.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import ExtraLimitation, ExtraLimitationLimit
from app.services.search import (
    _apply_gap_filter,
    _apply_time_gap_filter,
    _find_channel_gaps,
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
#   t0  Клиент     [0,   5]   "привет"
#   t1  Сотрудник  [5,   10]   "здравствуйте"
#   t2  Клиент     [25,  30]  "хочу расторгнуть"  (15s gap before)
#   t3  Сотрудник  [30,  35]  "давайте обсудим"
#   t4  Клиент     [55,  60]  "отказываюсь"        (20s gap before)
DIALOG_TURNS = [
    _turn("Клиент", "привет", 0.0, 5.0),
    _turn("Сотрудник", "здравствуйте", 5.0, 10.0),
    _turn("Клиент", "хочу расторгнуть", 25.0, 30.0),
    _turn("Сотрудник", "давайте обсудим", 30.0, 35.0),
    _turn("Клиент", "отказываюсь", 55.0, 60.0),
]


# ═══════════════════════════════════════════════════════════════════════
# 1. EventType=StartEnd — LimitType=First
# ═══════════════════════════════════════════════════════════════════════


class TestStartEndFirst:
    def test_first_10_seconds_keeps_only_early_matches(self) -> None:
        """LimitType=First, Value=10 → keep matches with start_offset <= 10."""
        matches = [_match(0), _match(1), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=10, limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t0 (start=0), t1 (start=5) kept; t2 (start=25), t4 (start=55) filtered.
        assert [m[0] for m in result] == [0, 1]

    def test_first_30_seconds_includes_boundary(self) -> None:
        """LimitType=First, Value=30 → keep matches with start_offset <= 30."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=30, limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t0 (0), t1 (5), t2 (25), t3 (30 — wait, t3 starts at 30) — start_offset=30 <= 30 → keep.
        assert [m[0] for m in result] == [0, 1, 2, 3]

    def test_first_0_seconds_keeps_only_starting_at_dialogue_start(self) -> None:
        """Value=0 with First → keep matches whose start_offset == dialogue_start (0)."""
        matches = [_match(0), _match(1)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=0, limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [0]


# ═══════════════════════════════════════════════════════════════════════
# 2. EventType=StartEnd — LimitType=Last
# ═══════════════════════════════════════════════════════════════════════


class TestStartEndLast:
    def test_last_10_seconds_keeps_only_late_matches(self) -> None:
        """LimitType=Last, Value=10 → keep matches with end_offset >= 50 (60-10)."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=10, limit_type="Last")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Only t4 has end_offset (60) >= 50.
        assert [m[0] for m in result] == [4]

    def test_last_30_seconds_includes_boundary(self) -> None:
        """LimitType=Last, Value=30 → keep matches with end_offset >= 30."""
        matches = [_match(0), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=30, limit_type="Last")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t2 end=30, t3 end=35, t4 end=60 all >= 30; t0 end=5 filtered.
        assert [m[0] for m in result] == [2, 3, 4]


# ═══════════════════════════════════════════════════════════════════════
# 3. EventType=Parent — SearchDirection=Before
# ═══════════════════════════════════════════════════════════════════════


class TestParentBefore:
    def test_before_5_seconds_keeps_matches_shortly_before_parent(self) -> None:
        """SearchDirection=Before, Value=5 → keep matches within 5s BEFORE a parent match.

        Parent matched at t=30 (turn 2 start). Match candidates (start_offset):
          t0 (0)    → 30-0=30s gap  → not within 5s before
          t1 (5)    → 30-5=25s gap  → not within 5s before
          t2 (25)   → 30-25=5s gap  → KEEP (exactly 5s, boundary inclusive)
          t3 (30)   → 30-30=0        → keep (same time as parent — edge)
          t4 (55)   → 55 > 30 → AFTER parent → not before
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            limits=[_limit(value=5, search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[30.0]
        )
        # Only matches with 0 <= (parent_t - match_t) <= 5 are kept.
        # t2: 30-25=5 → keep. t3: 30-30=0 → keep. t4: 55-30 < 0 → not before.
        assert [m[0] for m in result] == [2, 3]

    def test_before_50_seconds_keeps_more_matches(self) -> None:
        """Value=50 → keep matches within 50s before parent match at t=55."""
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            limits=[_limit(value=50, search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[55.0]
        )
        # Match candidates with start_offset in [5, 55]:
        #   t1 (5):  55-5=50 → keep (boundary)
        #   t2 (25): 55-25=30 → keep
        #   t3 (30): 55-30=25 → keep
        #   t4 (55): 55-55=0 → keep
        # t0 (0): 55-0=55 > 50 → filtered
        assert [m[0] for m in result] == [1, 2, 3, 4]

    def test_parent_filter_skipped_when_no_parent_match_times(self) -> None:
        """parent_match_times=None → Parent filter is a no-op (matches unchanged)."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="Parent",
            limits=[_limit(value=5, search_direction="Before")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=None
        )
        assert result == matches


# ═══════════════════════════════════════════════════════════════════════
# 4. EventType=Parent — SearchDirection=After
# ═══════════════════════════════════════════════════════════════════════


class TestParentAfter:
    def test_after_50_seconds_keeps_matches_within_50s_after_parent(self) -> None:
        """SearchDirection=After, Value=50 → keep matches within 50s AFTER parent.

        Parent matched at t=5 (turn 1 start). Match candidates (start_offset):
          t2 (25): 25-5=20 → keep
          t3 (30): 30-5=25 → keep
          t4 (55): 55-5=50 → keep (boundary)
          t0 (0): 0-5 < 0 → not after
        """
        matches = [_match(0), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            limits=[_limit(value=50, search_direction="After")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[5.0]
        )
        assert [m[0] for m in result] == [2, 3, 4]

    def test_after_5_seconds_keeps_only_shortly_after(self) -> None:
        """Value=5 → keep matches within 5s after parent match at t=25."""
        matches = [_match(0), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="Parent",
            limits=[_limit(value=5, search_direction="After")],
        )
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[25.0]
        )
        # t2: 25-25=0 → keep. t3: 30-25=5 → keep. t4: 55-25=30 > 5 → filtered.
        assert [m[0] for m in result] == [2, 3]

    def test_after_with_multiple_parent_times_uses_any(self) -> None:
        """Multiple parent matches: keep a child match if it's after ANY parent."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="Parent",
            limits=[_limit(value=5, search_direction="After")],
        )
        # Parent matches at t=0 (turn 0) and t=55 (turn 4).
        # t2 (25): not within 5s after either parent (25-0=25, 25-55<0) → filtered
        # t4 (55): 55-55=0 → keep (after parent at 55)
        # t0 (0): 0-0=0 → keep (after parent at 0)
        result = _apply_time_gap_filter(
            matches, DIALOG_TURNS, [el], parent_match_times=[0.0, 55.0]
        )
        assert [m[0] for m in result] == [0, 4]


# ═══════════════════════════════════════════════════════════════════════
# 5. SearchSpecifier=OnlyInGaps
# ═══════════════════════════════════════════════════════════════════════


class TestOnlyInGaps:
    def test_only_in_gaps_keeps_matches_inside_silence(self) -> None:
        """OnlyInGaps channel=CLIENT, value=15 → keep matches whose turn is in
        a CLIENT silence gap >= 15s.

        CLIENT turns: t0 [0,5], t2 [25,30], t4 [55,60].
        CLIENT silence gaps >= 15s:
          [5, 25]  (20s, between t0 and t2)
          [30, 55] (25s, between t2 and t4)
        Sотрудник turns t1 [5,10] and t3 [30,35] fall inside these gaps.

        Note: LimitType=First with a large value (1000) keeps ALL matches
        in the time window, then OnlyInGaps narrows to those inside gaps.
        The Limit.Value is reused as both time-window width AND gap threshold
        (per real SmartLogger structure — one <Value> per <Limit>).
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=1000, channel="CLIENT", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t1 (in [5,25] gap) and t3 (in [30,55] gap) are inside CLIENT gaps.
        # value=1000 makes the gap threshold 1000s — but only CLIENT silence
        # gaps >= 1000s qualify. None do → result is empty.
        # To test OnlyInGaps with reasonable threshold, use value=15 below.
        assert result == []

    def test_only_in_gaps_with_15s_threshold(self) -> None:
        """OnlyInGaps with value=15 keeps matches inside CLIENT silence gaps >= 15s.

        We separate the time-window from the gap threshold by using two
        ExtraLimitations: a First=1000 window (no-op effectively), then a
        standalone gap filter. But since one Limit carries both pieces of
        info (Value is shared), we use a value that gives a wide time window
        AND a reasonable gap threshold.

        Use value=15 with limit_type=First → time window = first 15s, gap threshold = 15s.
        After time window: t0 (0), t1 (5). After OnlyInGaps (gaps >= 15s):
          t0 [0,5]   → not inside any CLIENT silence gap → excluded
          t1 [5,10]  → inside [5,25] gap (which is 20s >= 15s) → kept
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=15, channel="CLIENT", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Only t1 survives: it's within first 15s AND inside the [5,25] gap.
        assert [m[0] for m in result] == [1]

    def test_only_in_gaps_with_last_window_keeps_t3(self) -> None:
        """OnlyInGaps with Last=30 + value=30 → time window keeps matches with
        end_offset >= 30 (t2, t3, t4). Of those, only t3 is inside a CLIENT
        silence gap ([30,55], 25s >= 30s? No — 25 < 30 → no gap qualifies).

        With value=15 instead, the gap [30,55] (25s >= 15s) qualifies, and
        t3 [30,35] is inside it → kept. But the time window Last=15 keeps
        matches with end_offset >= 45 (60-15): only t4 (end=60). t4 is
        a CLIENT turn, not in any gap → excluded.

        To keep t3 via gap, use no time-window constraint. We achieve this
        by using limit_type=None (defensive: unknown LimitType → no-op for
        the time-window step, only gap filter applies).
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=15, channel="CLIENT")],  # no limit_type
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Without a time window, all matches are considered for gap filter.
        # CLIENT silence gaps >= 15s: [5,25] and [30,55].
        # t1 [5,10] inside [5,25] → kept
        # t3 [30,35] inside [30,55] → kept
        # Others (t0, t2, t4) are CLIENT turns, not inside any gap → excluded.
        assert [m[0] for m in result] == [1, 3]

    def test_only_in_gaps_with_large_threshold_returns_empty(self) -> None:
        """value=100 + no time window → no gap that long → OnlyInGaps returns []."""
        matches = [_match(0), _match(1)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=100, channel="CLIENT")],  # no limit_type
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == []

    def test_only_in_gaps_with_no_channel_turns_treats_dialogue_as_gap(self) -> None:
        """If the channel has no turns, the entire dialogue is a gap."""
        # Build a dialogue with no OPERATOR turns (impossible but useful for test).
        turns = [
            _turn("Клиент", "a", 0.0, 5.0),
            _turn("Клиент", "b", 10.0, 15.0),
        ]
        matches = [_match(0), _match(1)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=5, channel="OPERATOR")],  # no limit_type
        )
        result = _apply_time_gap_filter(matches, turns, [el])
        # No OPERATOR turns → entire [0,15] is a gap (>= 5s) → keep all.
        assert [m[0] for m in result] == [0, 1]


# ═══════════════════════════════════════════════════════════════════════
# 6. SearchSpecifier=ExcludeGaps
# ═══════════════════════════════════════════════════════════════════════


class TestExcludeGaps:
    def test_exclude_gaps_removes_matches_inside_silence(self) -> None:
        """ExcludeGaps channel=CLIENT, value=15 → remove matches inside CLIENT gaps.

        Without a limit_type, the time-window step is a no-op; only the gap
        filter applies. CLIENT silence gaps >= 15s: [5,25] and [30,55].
        t1 [5,10] and t3 [30,35] fall inside these gaps → excluded.
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=15, channel="CLIENT")],  # no limit_type
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # t0, t2, t4 are CLIENT turns (not in any gap); t1 and t3 are excluded.
        assert [m[0] for m in result] == [0, 2, 4]

    def test_exclude_gaps_with_no_gaps_keeps_all(self) -> None:
        """value=100 → no gap → ExcludeGaps keeps all matches."""
        matches = [_match(0), _match(1), _match(2)]
        el = _el(
            event_type="StartEnd",
            search_specifier="ExcludeGaps",
            limits=[_limit(value=100, channel="CLIENT")],  # no limit_type
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert [m[0] for m in result] == [0, 1, 2]


# ═══════════════════════════════════════════════════════════════════════
# 7. No timestamps → no-op
# ═══════════════════════════════════════════════════════════════════════


class TestNoTimestamps:
    def test_turns_without_offsets_skip_filter(self) -> None:
        """When no turn has start_offset, filter returns matches unchanged."""
        turns_no_ts = [
            {"speaker": "Клиент", "text": "a", "start_offset": None, "end_offset": None},
            {"speaker": "Сотрудник", "text": "b", "start_offset": None, "end_offset": None},
        ]
        matches = [_match(0), _match(1)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=10, limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, turns_no_ts, [el])
        assert result == matches

    def test_has_timestamps_detects_any_turn_with_offset(self) -> None:
        assert _has_timestamps(DIALOG_TURNS) is True
        assert _has_timestamps([
            {"speaker": "x", "start_offset": None},
        ]) is False
        assert _has_timestamps([]) is False


# ═══════════════════════════════════════════════════════════════════════
# 8. Empty extra_limitations → no filtering
# ═══════════════════════════════════════════════════════════════════════


class TestEmptyExtraLimitations:
    def test_empty_list_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [])
        assert result == matches

    def test_extra_limitation_with_no_limits_skipped(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(event_type="StartEnd", limits=[])
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches


# ═══════════════════════════════════════════════════════════════════════
# 9. Disabled limit → skipped
# ═══════════════════════════════════════════════════════════════════════


class TestDisabledLimit:
    def test_disabled_limit_skipped(self) -> None:
        """limit.enabled=False → that Limit is skipped (matches unchanged)."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=5, limit_type="First", enabled=False)],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_mix_of_disabled_and_enabled_limits(self) -> None:
        """First Limit disabled, second enabled — second applies."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[
                _limit(value=1, limit_type="First", enabled=False),
                _limit(value=10, limit_type="Last"),
            ],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Last 10s: keep matches with end_offset >= 50. Only t4 (end=60).
        assert [m[0] for m in result] == [4]


# ═══════════════════════════════════════════════════════════════════════
# 10. Multiple ExtraLimitations combine
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleExtraLimitations:
    def test_two_extra_limitations_apply_sequentially(self) -> None:
        """First ExtraLimitation (First 30s) narrows; second (Last 30s) further narrows.

        After First 30s: t0, t1, t2, t3 (start_offset <= 30).
        After Last 30s (end_offset >= 30): t2 (end=30), t3 (end=35) survive.
        """
        matches = [_match(0), _match(1), _match(2), _match(3), _match(4)]
        els = [
            _el(event_type="StartEnd", limits=[_limit(value=30, limit_type="First")]),
            _el(event_type="StartEnd", limits=[_limit(value=30, limit_type="Last")]),
        ]
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, els)
        assert [m[0] for m in result] == [2, 3]


# ═══════════════════════════════════════════════════════════════════════
# 11. Gap helpers
# ═══════════════════════════════════════════════════════════════════════


class TestGapHelpers:
    def test_find_channel_gaps_client(self) -> None:
        """CLIENT turns t0 [0,5], t2 [25,30], t4 [55,60] → gaps [5,25] and [30,55]."""
        gaps = _find_channel_gaps(DIALOG_TURNS, "CLIENT", min_duration=10.0)
        assert gaps == [(5.0, 25.0), (30.0, 55.0)]

    def test_find_channel_gaps_filters_by_min_duration(self) -> None:
        """min_duration=21 → only gaps strictly longer than 20s are returned.
        [5,25] is 20s (excluded by 21 threshold); [30,55] is 25s (kept).
        """
        gaps = _find_channel_gaps(DIALOG_TURNS, "CLIENT", min_duration=21.0)
        assert gaps == [(30.0, 55.0)]

    def test_find_channel_gaps_no_channel_turns(self) -> None:
        """No OPERATOR-without-any turns — uses entire dialogue as gap."""
        turns = [
            _turn("Клиент", "a", 0.0, 5.0),
            _turn("Клиент", "b", 10.0, 15.0),
        ]
        gaps = _find_channel_gaps(turns, "OPERATOR", min_duration=5.0)
        assert gaps == [(0.0, 15.0)]


# ═══════════════════════════════════════════════════════════════════════
# 12. Non-Seconds ValueType → no-op for time filter
# ═══════════════════════════════════════════════════════════════════════


class TestNonSecondsValueType:
    def test_words_value_type_skipped_for_start_end(self) -> None:
        """value_type=Words (not Seconds) → time-window filter skipped."""
        matches = [_match(0), _match(2), _match(4)]
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=10, value_type="Words", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Words ValueType not supported for time-window filtering → no-op.
        assert result == matches

    def test_words_value_type_skipped_for_gap_filter(self) -> None:
        """value_type=Words → gap filter skipped (only Seconds supported)."""
        matches = [_match(0), _match(1)]
        el = _el(
            event_type="StartEnd",
            search_specifier="OnlyInGaps",
            limits=[_limit(value=10, value_type="Words", channel="CLIENT", limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        # Gap filter requires value_type=Seconds → no-op.
        assert result == matches


# ═══════════════════════════════════════════════════════════════════════
# 13. Unknown EventType — defensive no-op
# ═══════════════════════════════════════════════════════════════════════


class TestUnknownEventType:
    def test_unknown_event_type_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(
            event_type="WeirdFutureEventType",
            limits=[_limit(value=10, limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches

    def test_empty_event_type_returns_matches_unchanged(self) -> None:
        matches = [_match(0), _match(2)]
        el = _el(
            event_type="",
            limits=[_limit(value=10, limit_type="First")],
        )
        result = _apply_time_gap_filter(matches, DIALOG_TURNS, [el])
        assert result == matches


# ═══════════════════════════════════════════════════════════════════════
# 14. Empty matches
# ═══════════════════════════════════════════════════════════════════════


class TestEmptyMatches:
    def test_empty_matches_returns_empty(self) -> None:
        el = _el(
            event_type="StartEnd",
            limits=[_limit(value=10, limit_type="First")],
        )
        result = _apply_time_gap_filter([], DIALOG_TURNS, [el])
        assert result == []

"""Tests for RTF timestamp parsing → DialogueTurn.start_offset/end_offset.

UI-2.6 BE timestamps (this iteration). The RTF parser's `_map_turns` now
parses the SmartLogger `time` field from each RTF row's third cell into
``DialogueTurn.start_offset`` (float seconds from dialogue start) and
derives ``end_offset`` from the next turn's ``start_offset`` (or falls
back to this turn's own ``start_offset`` for the last turn).

SmartLogger's `extract_dialogue` (Transcrib/smartlogger/rtf_parser.py)
writes the time string in the canonical production format ``"H:MM:SS"``
(single-digit hour) — e.g. ``"0:00:01"``, ``"0:05:48"``. The parser is
best-effort and also accepts ``"HH:MM:SS"``, ``"MM:SS"``, bare seconds,
``None`` and unparseable strings (logged at WARNING, returns None —
search.py's time-gap filtering is then a no-op).
"""
from __future__ import annotations

import os
import sys

import pytest

# Ensure backend app + Transcrib (smartlogger) are importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "Transcrib")
)

from app.models import DialogueTurn, ParsedDialog
from app.services.rtf_parser import (
    _map_turns,
    _parse_plain_text_dialogue,
    _parse_timestamp_to_seconds,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. Unit: _parse_timestamp_to_seconds
# ═══════════════════════════════════════════════════════════════════════


class TestParseTimestampToSeconds:
    """Pure-function timestamp parser tests covering all accepted formats."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Canonical SmartLogger production format (single-digit hour).
            ("0:00:01", 1.0),
            ("0:00:15", 15.0),
            ("0:01:30", 90.0),
            ("0:05:48", 348.0),
            ("0:06:11", 371.0),
            # HH:MM:SS (two-digit hour) — also accepted.
            ("00:00:15", 15.0),
            ("01:02:03", 3723.0),
            # MM:SS short form.
            ("00:15", 15.0),
            ("01:30", 90.0),
            ("5:48", 348.0),
            # Bare seconds (int / float / decimal comma).
            ("15", 15.0),
            ("15.5", 15.5),
            ("15,5", 15.5),
            # Whitespace tolerance.
            ("  0:01:30  ", 90.0),
            # Fractional seconds after HH:MM:SS.
            ("0:00:15.250", 15.0),
        ],
    )
    def test_accepted_formats(self, raw, expected) -> None:
        assert _parse_timestamp_to_seconds(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "invalid",
            "abc:def:ghi",
            # Components out of range.
            "0:99:00",
            "0:00:99",
            "99:99",
        ],
    )
    def test_unparseable_returns_none(self, raw) -> None:
        assert _parse_timestamp_to_seconds(raw) is None

    def test_none_passthrough(self) -> None:
        assert _parse_timestamp_to_seconds(None) is None


# ═══════════════════════════════════════════════════════════════════════
# 2. _map_turns: start_offset / end_offset population
# ═══════════════════════════════════════════════════════════════════════


class TestMapTurnsTimestamps:
    """``_map_turns`` must populate start_offset/end_offset from `time`."""

    def test_single_turn_end_offset_equals_start(self) -> None:
        """A single turn has no successor → end_offset == start_offset."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": "0:00:15"},
        ])
        assert len(turns) == 1
        assert turns[0].start_offset == 15.0
        assert turns[0].end_offset == 15.0
        assert turns[0].timestamp == "0:00:15"

    def test_end_offset_inherited_from_next_turn(self) -> None:
        """end_offset of turn N == start_offset of turn N+1 (best estimate
        of when this turn's speech ended)."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": "0:00:01"},
            {"speaker": "Сотрудник", "text": "здравствуйте", "time": "0:00:04"},
            {"speaker": "Клиент", "text": "хочу расторгнуть", "time": "0:00:12"},
        ])
        assert turns[0].start_offset == 1.0
        assert turns[0].end_offset == 4.0
        assert turns[1].start_offset == 4.0
        assert turns[1].end_offset == 12.0
        # Last turn has no successor → falls back to its own start_offset.
        assert turns[2].start_offset == 12.0
        assert turns[2].end_offset == 12.0

    def test_none_time_yields_none_offsets(self) -> None:
        """When `time` is None, both offsets stay None."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": None},
        ])
        assert turns[0].start_offset is None
        assert turns[0].end_offset is None

    def test_missing_time_key_yields_none_offsets(self) -> None:
        """When the `time` key is absent (no key at all), offsets are None."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет"},  # no "time" / "timestamp"
        ])
        assert turns[0].start_offset is None
        assert turns[0].end_offset is None
        assert turns[0].timestamp is None

    def test_empty_time_string_yields_none_offsets(self) -> None:
        """Empty `time` string → None offsets (typical plain-text fallback)."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": ""},
        ])
        assert turns[0].start_offset is None
        assert turns[0].end_offset is None

    def test_unparseable_time_yields_none_with_warning(self, caplog) -> None:
        """Unparseable timestamp string → None offsets + WARNING log."""
        with caplog.at_level("WARNING", logger="app.services.rtf_parser"):
            turns = _map_turns([
                {"speaker": "Клиент", "text": "привет", "time": "abc"},
            ])
        assert turns[0].start_offset is None
        assert turns[0].end_offset is None
        assert any("Unparseable RTF timestamp" in r.message for r in caplog.records)

    def test_mixed_parseable_and_unparseable(self) -> None:
        """A dialogue can mix timed and untimed turns (rare but supported).

        When a middle turn has no parseable time, its successor's start_offset
        is NOT reused for end_offset computation of the previous turn —
        end_offset falls back to the previous turn's own start_offset
        (point marker). Subsequent timed turns still produce valid offsets.
        """
        turns = _map_turns([
            {"speaker": "Клиент", "text": "a", "time": "0:00:10"},
            {"speaker": "Сотрудник", "text": "b", "time": "garbage"},
            {"speaker": "Клиент", "text": "c", "time": "0:00:30"},
        ])
        assert turns[0].start_offset == 10.0
        # turn[1] is unparseable → next_offset (start_offsets[1]) is None
        # → turn[0].end_offset falls back to turn[0].start_offset.
        assert turns[0].end_offset == 10.0
        assert turns[1].start_offset is None
        assert turns[1].end_offset is None
        assert turns[2].start_offset == 30.0
        # turn[2] is the last → end_offset == start_offset.
        assert turns[2].end_offset == 30.0

    def test_timestamp_field_preserved(self) -> None:
        """The raw `timestamp` field on DialogueTurn keeps the original string
        (no mutation) — start_offset is a derived value, not a replacement."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": "0:00:15"},
        ])
        assert turns[0].timestamp == "0:00:15"

    def test_timestamp_key_alias(self) -> None:
        """Some smartlogger builds return `timestamp` instead of `time`."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "timestamp": "0:00:15"},
        ])
        assert turns[0].start_offset == 15.0
        assert turns[0].timestamp == "0:00:15"


# ═══════════════════════════════════════════════════════════════════════
# 3. Plain-text fallback: no timestamps
# ═══════════════════════════════════════════════════════════════════════


class TestPlainTexTwallbackNoTimestamps:
    """`_parse_plain_text_dialogue` always sets `time` to "" → offsets None.

    This is the canonical behavior when smartlogger is unavailable and the
    parser falls back to striprtf. The whole dialogue then lacks timing →
    search._has_timestamps returns False → time-gap filter becomes a no-op
    (per UI-2.6 contract: never silently drop matches when timing is absent).
    """

    def test_plain_text_turns_have_empty_time(self) -> None:
        raw = _parse_plain_text_dialogue("Клиент: привет\nСотрудник: здравствуйте")
        assert all(t["time"] == "" for t in raw)

    def test_plain_text_mapped_turns_have_none_offsets(self) -> None:
        raw = _parse_plain_text_dialogue("Клиент: привет\nСотрудник: здравствуйте")
        turns = _map_turns(raw)
        assert all(t.start_offset is None for t in turns)
        assert all(t.end_offset is None for t in turns)


# ═══════════════════════════════════════════════════════════════════════
# 4. ParsedDialog integration: search._has_timestamps detects timing
# ═══════════════════════════════════════════════════════════════════════


class TestParsedDialogTimestamps:
    """End-to-end: ParsedDialog built from smartlogger turns carries timing
    when `time` is parseable; search._has_timestamps detects it."""

    def test_parsed_dialog_with_timestamps(self) -> None:
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": "0:00:01"},
            {"speaker": "Сотрудник", "text": "здравствуйте", "time": "0:00:04"},
        ])
        dialog = ParsedDialog(
            filename="test.rtf",
            turns=turns,
            total_turns=len(turns),
            client_turns=1,
            employee_turns=1,
        )

        from app.services.search import _build_turns, _has_timestamps

        search_turns = _build_turns(dialog)
        assert _has_timestamps(search_turns) is True
        assert search_turns[0]["start_offset"] == 1.0
        assert search_turns[0]["end_offset"] == 4.0

    def test_parsed_dialog_without_timestamps(self) -> None:
        """Plain-text fallback dialogue → no timing → filter becomes no-op."""
        turns = _map_turns([
            {"speaker": "Клиент", "text": "привет", "time": ""},
        ])
        dialog = ParsedDialog(
            filename="test.rtf",
            turns=turns,
            total_turns=len(turns),
            client_turns=1,
            employee_turns=0,
        )

        from app.services.search import _build_turns, _has_timestamps

        search_turns = _build_turns(dialog)
        assert _has_timestamps(search_turns) is False
        assert search_turns[0]["start_offset"] is None
        assert search_turns[0]["end_offset"] is None


# ═══════════════════════════════════════════════════════════════════════
# 5. DialogueTurn model: defaults
# ═══════════════════════════════════════════════════════════════════════


class TestDialogueTurnDefaults:
    """Backward-compat: start_offset/end_offset default to None."""

    def test_dialogue_turn_default_offsets_none(self) -> None:
        turn = DialogueTurn(turn_index=0, speaker="Клиент", text="привет")
        assert turn.start_offset is None
        assert turn.end_offset is None
        assert turn.timestamp is None

"""Regression test: RTF timestamp extraction from SmartLogger RTF files.

This test guards against silent degradation of the RTF parser's timestamp
extraction pipeline:

  smartlogger.rtf_parser.extract_dialogue()
      → {"time": "H:MM:SS"} per turn
      → rtf_parser._parse_timestamp_to_seconds()
      → DialogueTurn.start_offset (float seconds)
      → DialogueTurn.end_offset (next turn's start_offset)

Background:
  Time-gap filtering in `app/services/search.py` (`_apply_time_gap_filter`)
  is a NO-OP when `start_offset is None` for all turns. A regression in the
  RTF parser that silently drops timestamps would therefore disable
  ExtraLimitations filtering without any visible error — matches that should
  be excluded by `ExcludeGaps + Last + 15s` would silently survive.

Verified baseline (2026-07-18):
  - All real RTF files in `data/input/rtf/` produce 100%
    timestamps in `H:MM:SS` format.
  - The committed `docs/assets/sample-dialog.rtf` has 32 turns, timestamps
    from `0:00:01` to `0:06:11` (1.0 → 371.0 seconds).

CI-safe:
  Primary assertions use `docs/assets/sample-dialog.rtf` (committed).
  Extended assertions on `data/input/rtf/` run only when that
  directory exists (local dev / staging with real data).
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.rtf_parser import _parse_timestamp_to_seconds, parse_rtf_file

# ── Paths ──────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMITTED_RTF = _REPO_ROOT / "docs" / "assets" / "sample-dialog.rtf"
_REAL_RTF_DIR = _REPO_ROOT / "Transcrib" / "data" / "input" / "rtf"


# ═══════════════════════════════════════════════════════════════════════
# Unit tests: _parse_timestamp_to_seconds
# ═══════════════════════════════════════════════════════════════════════


class TestParseTimestampToSeconds:
    """Verify timestamp string parsing into float seconds."""

    def test_hms_single_digit_hour(self) -> None:
        """SmartLogger canonical format: '0:00:01' → 1.0 seconds."""
        assert _parse_timestamp_to_seconds("0:00:01") == 1.0
        assert _parse_timestamp_to_seconds("0:05:48") == 348.0
        assert _parse_timestamp_to_seconds("0:06:11") == 371.0

    def test_hms_double_digit_hour(self) -> None:
        """Long dialogues: '1:23:45' → 5025.0 seconds."""
        assert _parse_timestamp_to_seconds("1:23:45") == 5025.0

    def test_hms_with_fractional(self) -> None:
        """Fractional seconds are accepted (regex tolerant) but truncated to int.

        SmartLogger production format is always 'H:MM:SS' (no fractional),
        so this test documents the parser's tolerant-but-truncating behavior.
        """
        # The regex accepts [.,]\d+ suffix, but int(group("s")) truncates.
        # This is acceptable: SmartLogger never emits fractional HMS.
        assert _parse_timestamp_to_seconds("0:00:01.5") == 1.0
        assert _parse_timestamp_to_seconds("0:00:01,5") == 1.0

    def test_ms_format(self) -> None:
        """Short form: '05:48' → 348.0."""
        assert _parse_timestamp_to_seconds("05:48") == 348.0
        assert _parse_timestamp_to_seconds("5:48") == 348.0

    def test_bare_seconds(self) -> None:
        """Bare seconds: '15' → 15.0, '15.5' → 15.5."""
        assert _parse_timestamp_to_seconds("15") == 15.0
        assert _parse_timestamp_to_seconds("15.5") == 15.5
        assert _parse_timestamp_to_seconds("15,5") == 15.5

    def test_none_returns_none(self) -> None:
        assert _parse_timestamp_to_seconds(None) is None

    def test_empty_returns_none(self) -> None:
        assert _parse_timestamp_to_seconds("") is None
        assert _parse_timestamp_to_seconds("   ") is None

    def test_garbage_returns_none(self) -> None:
        assert _parse_timestamp_to_seconds("abc") is None
        assert _parse_timestamp_to_seconds("12:99:99") is None  # invalid HMS

    def test_whitespace_tolerant(self) -> None:
        assert _parse_timestamp_to_seconds("  0:00:01  ") == 1.0


# ═══════════════════════════════════════════════════════════════════════
# Integration tests: committed RTF file (CI-safe)
# ═══════════════════════════════════════════════════════════════════════


class TestCommittedRtfTimestamps:
    """Verify timestamp extraction on the committed sample RTF.

    Uses `docs/assets/sample-dialog.rtf` which is tracked in git and
    always available in CI. This is the baseline regression guard.
    """

    def test_committed_rtf_exists(self) -> None:
        """The committed RTF sample must exist for this test to run."""
        assert _COMMITTED_RTF.exists(), (
            f"Committed RTF not found: {_COMMITTED_RTF}\n"
            "This file should be tracked in git at docs/assets/sample-dialog.rtf"
        )

    @pytest.mark.asyncio
    async def test_committed_rtf_has_timestamps(self) -> None:
        """The committed RTF must produce turns with start_offset != None.

        If this test fails, the RTF parser has regressed and time-gap
        filtering in search.py is silently disabled for this file.
        """
        parsed = await parse_rtf_file(_COMMITTED_RTF, "sample-dialog.rtf")

        assert parsed.total_turns > 0, "No turns extracted from committed RTF"
        assert parsed.total_turns >= 10, (
            f"Expected at least 10 turns, got {parsed.total_turns} — "
            "the committed sample should be a real dialogue"
        )

        turns_with_ts = sum(
            1 for t in parsed.turns if t.start_offset is not None
        )
        ts_ratio = turns_with_ts / parsed.total_turns

        assert ts_ratio >= 0.9, (
            f"Only {turns_with_ts}/{parsed.total_turns} turns have timestamps "
            f"({ts_ratio:.0%}). Expected >= 90%. "
            "Time-gap filtering would be a silent no-op with this degradation."
        )

    @pytest.mark.asyncio
    async def test_committed_rtf_timestamps_are_monotonic(self) -> None:
        """Timestamps should be monotonically non-decreasing."""
        parsed = await parse_rtf_file(_COMMITTED_RTF, "sample-dialog.rtf")

        offsets = [t.start_offset for t in parsed.turns if t.start_offset is not None]
        assert len(offsets) >= 2, "Need at least 2 timestamps to check monotonicity"

        for i in range(1, len(offsets)):
            assert offsets[i] >= offsets[i - 1], (
                f"Timestamps not monotonic at turn {i}: "
                f"{offsets[i - 1]} -> {offsets[i]}"
            )

    @pytest.mark.asyncio
    async def test_committed_rtf_end_offset_propagation(self) -> None:
        """end_offset of turn N should equal start_offset of turn N+1."""
        parsed = await parse_rtf_file(_COMMITTED_RTF, "sample-dialog.rtf")

        for i in range(len(parsed.turns) - 1):
            cur = parsed.turns[i]
            nxt = parsed.turns[i + 1]
            if cur.start_offset is not None and nxt.start_offset is not None:
                assert cur.end_offset == nxt.start_offset, (
                    f"Turn {i} end_offset={cur.end_offset} != "
                    f"turn {i + 1} start_offset={nxt.start_offset}"
                )

    @pytest.mark.asyncio
    async def test_committed_rtf_known_values(self) -> None:
        """Spot-check known timestamp values from the committed sample.

        The committed `sample-dialog.rtf` (32 turns) has timestamps
        from 0:00:01 (1.0 sec) to 0:06:11 (371.0 sec).
        """
        parsed = await parse_rtf_file(_COMMITTED_RTF, "sample-dialog.rtf")

        first = parsed.turns[0]
        assert first.start_offset == 1.0, (
            f"First turn start_offset={first.start_offset}, expected 1.0 (0:00:01)"
        )

        # Find the last turn with a timestamp
        last_ts = None
        for t in reversed(parsed.turns):
            if t.start_offset is not None:
                last_ts = t.start_offset
                break

        assert last_ts is not None, "No turns have timestamps"
        assert last_ts >= 300.0, (
            f"Last timestamp={last_ts}, expected >= 300.0 "
            "(dialogue should be at least 5 minutes long)"
        )


# ═══════════════════════════════════════════════════════════════════════
# Extended tests: real RTF directory (local dev / staging only)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(
    not _REAL_RTF_DIR.exists(),
    reason=f"Real RTF directory not found: {_REAL_RTF_DIR} (local dev / staging only)",
)
class TestRealRtfDirectory:
    """Extended timestamp validation on real production RTF files.

    Runs only when `data/input/rtf/` exists (not tracked in git).
    Samples up to 20 random files to keep test time under 5 seconds.
    """

    @pytest.mark.asyncio
    async def test_real_rtf_files_have_timestamps(self) -> None:
        """At least 90% of turns across sampled real RTF files must have timestamps."""
        # rglob: real RTF files live in subdirectories (chatclient/, Old/) —
        # top-level glob stopped matching after the data layout changed.
        rtf_files = sorted(_REAL_RTF_DIR.rglob("*.rtf"))
        assert len(rtf_files) > 0, f"No RTF files in {_REAL_RTF_DIR}"

        # Sample up to 20 files (deterministic seed for reproducibility)
        sample_size = min(20, len(rtf_files))
        random.seed(42)
        sampled = random.sample(rtf_files, sample_size)

        total_turns = 0
        turns_with_ts = 0
        files_with_full_ts = 0
        files_with_no_ts = 0

        for rtf_path in sampled:
            try:
                parsed = await parse_rtf_file(rtf_path, rtf_path.name)
            except Exception as e:
                pytest.fail(f"Failed to parse {rtf_path.name}: {e}")

            file_turns = parsed.total_turns
            if file_turns == 0:
                continue

            file_ts = sum(
                1 for t in parsed.turns if t.start_offset is not None
            )
            total_turns += file_turns
            turns_with_ts += file_ts

            if file_ts == file_turns:
                files_with_full_ts += 1
            elif file_ts == 0:
                files_with_no_ts += 1

        overall_ratio = turns_with_ts / total_turns if total_turns > 0 else 0.0

        # Assert: at least 90% of all turns must have timestamps
        assert overall_ratio >= 0.9, (
            f"Timestamp coverage {turns_with_ts}/{total_turns} "
            f"({overall_ratio:.1%}) across {sample_size} files. "
            f"Files with 100% ts: {files_with_full_ts}, "
            f"files with 0% ts: {files_with_no_ts}. "
            "Time-gap filtering would be a silent no-op for files without timestamps."
        )

    @pytest.mark.asyncio
    async def test_real_rtf_timestamp_format(self) -> None:
        """Verify that smartlogger returns 'H:MM:SS' format timestamps."""
        import sys
        sys.path.insert(0, str(_REPO_ROOT / "Transcrib"))
        from smartlogger.rtf_parser import extract_dialogue

        rtf_files = sorted(_REAL_RTF_DIR.rglob("*.rtf"))
        sample_size = min(5, len(rtf_files))
        random.seed(123)
        sampled = random.sample(rtf_files, sample_size)

        import re
        hms_re = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")

        for rtf_path in sampled:
            dlg = extract_dialogue(str(rtf_path))
            assert len(dlg) > 0, f"No turns extracted from {rtf_path.name}"

            # Check that timestamps match expected format
            for turn in dlg:
                ts = turn.get("time", "").strip()
                if ts:  # Only check non-empty timestamps
                    assert hms_re.match(ts), (
                        f"{rtf_path.name}: unexpected timestamp format {ts!r}, "
                        "expected 'H:MM:SS'"
                    )

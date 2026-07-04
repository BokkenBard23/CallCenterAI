"""RTF parser service — wraps smartlogger.rtf_parser with striprtf fallback.

Parse flow:
1. Write uploaded bytes to a temporary file
2. Try smartlogger.rtf_parser.extract_dialogue() for structured extraction
3. If smartlogger fails → fallback to striprtf for plain text extraction
4. Map color codes: \\cf1 → "Клиент", \\cf2 → "Сотрудник"
5. Return ParsedDialog with list of DialogueTurn

DO NOT modify smartlogger package code (INV-6).
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

from app.models import DialogueTurn, ParsedDialog

logger = logging.getLogger(__name__)


# Module-level compiled regex for timestamp parsing (UI-2.6 BE timestamps).
# SmartLogger RTF (Transcrib/smartlogger/rtf_parser.py:extract_dialogue)
# writes the third cell of each table row as a string like "0:00:01"
# (H:MM:SS, single-digit hour). The cleanup in smartlogger's clean_rtf_text
# collapses whitespace so the canonical production format is "H:MM:SS".
#
# Accepted formats (best-effort, resilient to variations):
#   "H:MM:SS" / "HH:MM:SS"  — typical SmartLogger output
#   "MM:SS"                 — short form
#   "SSS" / "SS" / float    — bare seconds
_TIME_HMS_RE = re.compile(
    r"^\s*(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.,]\d+)?\s*$"
)
_TIME_MS_RE = re.compile(r"^\s*(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.,]\d+)?\s*$")
_TIME_SECONDS_RE = re.compile(r"^\s*(?P<sec>\d+(?:[.,]\d+)?)\s*$")


def _parse_timestamp_to_seconds(value: Optional[str]) -> Optional[float]:
    """Parse a SmartLogger RTF turn timestamp into seconds from dialogue start.

    SmartLogger's extract_dialogue returns `time` as a string from the third
    table cell of each RTF row (see Transcrib/smartlogger/rtf_parser.py).
    The empirically observed production format is ``"H:MM:SS"`` (single-digit
    hour), e.g. ``"0:00:01"``, ``"0:05:48"``.

    Accepted formats (best-effort, never raises):
      - ``"H:MM:SS"`` / ``"HH:MM:SS"`` (and with optional fractional part)
      - ``"MM:SS"``
      - bare seconds: ``"15"``, ``"15.5"``, ``"15,5"``
      - ``None`` / empty / unparseable → ``None`` (logged at WARNING)

    Args:
        value: Raw timestamp string from smartlogger turn dict (turn["time"]).

    Returns:
        Float seconds from dialogue start, or ``None`` if absent/unparseable.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    match = _TIME_HMS_RE.match(text)
    if match is not None:
        h = int(match.group("h"))
        m = int(match.group("m"))
        s = int(match.group("s"))
        if m > 59 or s > 59:
            logger.warning(
                "Unparseable RTF timestamp (invalid HMS components): %r", value
            )
            return None
        return float(h * 3600 + m * 60 + s)

    match = _TIME_MS_RE.match(text)
    if match is not None:
        m = int(match.group("m"))
        s = int(match.group("s"))
        if m > 59 or s > 59:
            logger.warning(
                "Unparseable RTF timestamp (invalid MS components): %r", value
            )
            return None
        return float(m * 60 + s)

    match = _TIME_SECONDS_RE.match(text)
    if match is not None:
        try:
            return float(match.group("sec").replace(",", "."))
        except (ValueError, TypeError):
            logger.warning(
                "Unparseable RTF timestamp (numeric conversion failed): %r", value
            )
            return None

    logger.warning("Unparseable RTF timestamp (unknown format): %r", value)
    return None


async def parse_rtf_bytes(rtf_bytes: bytes, filename: str) -> ParsedDialog:
    """Parse RTF file bytes into a ParsedDialog model.

    Writes bytes to a temp file, uses smartlogger for extraction,
    falls back to striprtf if smartlogger fails.

    Args:
        rtf_bytes: Raw RTF file content.
        filename: Original filename for metadata.

    Returns:
        ParsedDialog with extracted turns.

    Raises:
        ValueError: If the RTF cannot be parsed or contains no dialogue.
    """
    tmp_path: Optional[str] = None
    try:
        # Write bytes to temp file (smartlogger expects a filepath)
        with tempfile.NamedTemporaryFile(
            suffix=".rtf", delete=False, prefix="ccai_"
        ) as tmp:
            tmp.write(rtf_bytes)
            tmp_path = tmp.name

        return await _parse_rtf_file(Path(tmp_path), filename)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def parse_rtf_file(file_path: Path, filename: Optional[str] = None) -> ParsedDialog:
    """Parse an RTF file by path into a ParsedDialog model.

    Args:
        file_path: Path to the .rtf file.
        filename: Override filename (defaults to file_path.name).

    Returns:
        ParsedDialog with extracted turns.

    Raises:
        ValueError: If the RTF cannot be parsed or contains no dialogue.
    """
    return await _parse_rtf_file(file_path, filename or file_path.name)


async def _parse_rtf_file(file_path: Path, filename: str) -> ParsedDialog:
    """Internal: parse RTF file using smartlogger with striprtf fallback.

    Args:
        file_path: Path to the .rtf file.
        filename: Original filename for metadata.

    Returns:
        ParsedDialog with extracted turns.

    Raises:
        ValueError: If no dialogue can be extracted.
    """
    display_name = filename or file_path.name
    raw_text_length = 0

    # ── Strategy 1: smartlogger.rtf_parser (preferred) ──────────────
    raw_turns: List[dict] = []
    try:
        from smartlogger.rtf_parser import extract_dialogue

        raw_turns = extract_dialogue(str(file_path))
        logger.info(
            "smartlogger extract_dialogue returned %d turns for '%s'",
            len(raw_turns),
            display_name,
        )
    except Exception as exc:
        logger.warning(
            "smartlogger extract_dialogue failed for '%s': %s — trying striprtf fallback",
            display_name,
            exc,
        )
        raw_turns = []

    # ── Strategy 2: striprtf fallback (plain text) ──────────────────
    if not raw_turns:
        try:
            from striprtf.striprtf import rtf_to_text

            rtf_text = file_path.read_text(encoding="utf-8", errors="replace")
            raw_text_length = len(rtf_text)
            plain_text = rtf_to_text(rtf_text)
            raw_text_length = len(plain_text)

            # Parse plain text into alternating turns
            raw_turns = _parse_plain_text_dialogue(plain_text)
            logger.info(
                "striprtf fallback returned %d turns for '%s'",
                len(raw_turns),
                display_name,
            )
        except Exception as exc:
            logger.error(
                "striprtf fallback also failed for '%s': %s",
                display_name,
                exc,
            )

    # ── Validate ─────────────────────────────────────────────────────
    if not raw_turns:
        raise ValueError(
            f"Could not extract any dialogue from RTF file '{display_name}'. "
            "The file may be empty or not contain valid RTF dialogue."
        )

    # ── Map to DialogueTurn models ──────────────────────────────────
    turns = _map_turns(raw_turns)

    # Compute raw text length from smartlogger output if not set
    if raw_text_length == 0:
        raw_text_length = sum(len(t.get("text", "")) for t in raw_turns)

    client_turns = sum(1 for t in turns if t.speaker == "Клиент")
    employee_turns = sum(1 for t in turns if t.speaker == "Сотрудник")

    return ParsedDialog(
        filename=display_name,
        turns=turns,
        total_turns=len(turns),
        client_turns=client_turns,
        employee_turns=employee_turns,
    )


def _map_turns(raw_turns: List[dict]) -> List[DialogueTurn]:
    """Map smartlogger turn dicts to DialogueTurn models.

    smartlogger format: {"speaker": "Клиент"|"Сотрудник"|"Неизвестный",
                          "text": str, "time": str}

    Color code invariant (INV-4): \\cf1 = Клиент, \\cf2 = Сотрудник

    UI-2.6 BE timestamps:
        `start_offset` is parsed from the raw `time` string (smartlogger
        writes the third cell of each RTF table row as "H:MM:SS"). When the
        string is absent or unparseable, `start_offset` stays None.
        `end_offset` is derived from the NEXT turn's `start_offset` when
        available, otherwise it equals `start_offset` (point-in-time marker).
        For plain-text fallback dialogues (`_parse_plain_text_dialogue`),
        `time` is always "" → both offsets stay None — time-gap filtering
        in search.py is then a no-op (per UI-2.6 contract).
    """
    mapped: List[DialogueTurn] = []

    # Pre-parse every turn's start_offset ONCE so we can also compute
    # end_offset = next turn's start_offset in a single pass.
    start_offsets: List[Optional[float]] = [
        _parse_timestamp_to_seconds(t.get("time") or t.get("timestamp"))
        for t in raw_turns
    ]

    for i, turn in enumerate(raw_turns):
        speaker = turn.get("speaker", "Неизвестный")
        # Normalize unknown speaker
        if speaker not in ("Клиент", "Сотрудник"):
            speaker = "Неизвестный"

        start_offset = start_offsets[i]

        # end_offset = next turn's start_offset (best estimate of when this
        # turn's speech ended). The last turn has no successor → fall back
        # to its own start_offset (point marker). When start_offset is None,
        # end_offset is also None — search._has_timestamps then reports False
        # and time-gap filtering becomes a no-op for the whole dialogue.
        if start_offset is None:
            end_offset: Optional[float] = None
        elif i + 1 < len(start_offsets) and start_offsets[i + 1] is not None:
            end_offset = start_offsets[i + 1]
        else:
            end_offset = start_offset

        mapped.append(
            DialogueTurn(
                turn_index=i,
                speaker=speaker,
                text=turn.get("text", ""),
                timestamp=turn.get("time") or turn.get("timestamp"),
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
    return mapped


def _parse_plain_text_dialogue(plain_text: str) -> List[dict]:
    """Parse plain text (from striprtf fallback) into dialogue turns.

    Attempts to split text by line breaks and assign speakers
    based on alternating pattern or labeled prefixes.

    Args:
        plain_text: Decoded plain text from striprtf.

    Returns:
        List of {"speaker": str, "text": str, "time": str} dicts.
    """
    turns: List[dict] = []
    lines = plain_text.split("\n")
    current_speaker = "Сотрудник"  # Start with employee

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for labeled prefixes like "Клиент:", "Сотрудник:"
        if stripped.startswith("Клиент:") or stripped.startswith("Клиент :"):
            current_speaker = "Клиент"
            text = stripped.split(":", 1)[1].strip() if ":" in stripped else stripped
        elif stripped.startswith("Сотрудник:") or stripped.startswith("Сотрудник :"):
            current_speaker = "Сотрудник"
            text = stripped.split(":", 1)[1].strip() if ":" in stripped else stripped
        else:
            # Alternate speaker for unlabeled lines
            text = stripped
            if turns:
                # Alternate only if previous was from a different speaker
                prev_speaker = turns[-1]["speaker"]
                if prev_speaker == "Клиент":
                    current_speaker = "Сотрудник"
                else:
                    current_speaker = "Клиент"

        if text:
            turns.append({"speaker": current_speaker, "text": text, "time": ""})

    return turns

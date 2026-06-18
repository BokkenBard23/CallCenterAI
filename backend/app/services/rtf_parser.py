"""RTF parser service — wraps smartlogger.rtf_parser.

This service provides a clean interface for parsing RTF call center
dialogue files using the existing smartlogger package.

TODO (coder stage):
  - Implement parse_rtf() using smartlogger.rtf_parser.extract_dialogue
  - Handle file I/O and error mapping
  - Map smartlogger internal format to app.models.ParsedDialog
"""

from pathlib import Path
from typing import Optional

from app.models import DialogueTurn, ParsedDialog


async def parse_rtf(file_path: Path) -> ParsedDialog:
    """Parse an RTF file into a ParsedDialog model.

    Args:
        file_path: Path to the .rtf file

    Returns:
        ParsedDialog with extracted turns

    Raises:
        ValueError: If the RTF file cannot be parsed
    """
    # TODO: Implement using smartlogger.rtf_parser
    # from smartlogger.rtf_parser import rtf_bytes_to_unicode, extract_dialogue
    raise NotImplementedError("RTF parsing not yet implemented")


def map_turns(raw_turns: list[dict]) -> list[DialogueTurn]:
    """Map smartlogger turn dicts to DialogueTurn models.

    smartlogger format: {"speaker": "Клиент"|"Сотрудник", "text": str, ...}
    """
    return [
        DialogueTurn(
            turn_index=i,
            speaker=turn.get("speaker", "Unknown"),
            text=turn.get("text", ""),
            timestamp=turn.get("timestamp"),
        )
        for i, turn in enumerate(raw_turns)
    ]

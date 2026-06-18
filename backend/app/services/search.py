"""Hierarchical search engine service.

Uses smartlogger.matcher for phrase matching against dialogues.

TODO (coder stage):
  - Implement match_dialogue() using smartlogger.matcher.match_dialogue
  - Implement match_phrase_sliding_window wrapper
  - Map results to app.models.DictMatch
  - Build AnalysisResult with match statistics
"""

from typing import List

from app.models import AnalysisResult, DictCondition, DictMatch


async def match_dialogue(
    turns: list[dict],
    conditions: list[DictCondition],
    channel_map: dict[int, str] | None = None,
) -> AnalysisResult:
    """Run phrase matching against a parsed dialogue.

    Args:
        turns: Dialogue turns from smartlogger format
        conditions: Dictionary conditions to search for
        channel_map: Optional speaker-to-channel mapping

    Returns:
        AnalysisResult with all matches found
    """
    # TODO: Implement using smartlogger.matcher
    # from smartlogger.matcher import match_phrase_sliding_window, match_dialogue
    raise NotImplementedError("Search engine not yet implemented")

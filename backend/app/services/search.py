"""Hierarchical search engine service.

CRITICAL RULES (from SmartLogger XML spec [4]):
  - Word order is ALWAYS FREE (both with and without quotes)
  - Quotes fix ONLY morphology (exact word form), NOT word order
  - WordDistance controls intermediate words allowed between phrase words
  - НЕ (LEXEME) excludes the following operand from results
  - не (WORD) is a regular search word — part of the phrase
  - WITHOUT phrases from XML <ExtraLimitations> suppress matches
  - GATE model: child level searches ALL turns, but ONLY IF parent matched

KEY CHANGES from original:
  1. INV-8 REMOVED — is_exact from XML is now respected [1][2][4]
  2. WITHOUT from condition.without_list is now applied [1][3]
  3. is_negated conditions suppress (not contribute to) matches [2]
  4. match_type reflects actual algorithm used [1]
  5. span_end computed from actual matched words, not window end [1]

LEVEL ASSIGNMENT (INV-6 — preserved):
  Container nodes (no conditions) do NOT consume a level.

CASCADE / GATE (INV-7 — preserved):
  Each level searches ALL turns, but ONLY IF the previous level matched.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DictMatch,
    ParsedDialog,
    SearchResult,
    TextSegment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_hierarchical_search(
    dialog: ParsedDialog,
    dictionaries: List[DictionaryNode],
    selected_dict_names: Optional[List[str]] = None,
    cascade: bool = True,
) -> SearchResult:
    """Run hierarchical phrase matching on a parsed dialogue.

    Args:
        dialog: The parsed dialogue with turns.
        dictionaries: List of root dictionary nodes (with children).
        selected_dict_names: Optional filter — only search these dicts.
        cascade: If True, use GATE mode (each dict searches only if
            all previous dicts matched).

    Returns:
        SearchResult with segments, matches, and level statistics.
    """
    if not dialog.turns:
        return SearchResult(
            segments=[], total_matches=0, matches=[],
            matches_by_level={}, search_source="morph",
        )

    turns = _build_turns(dialog)
    channel_map = {i: t.speaker for i, t in enumerate(dialog.turns)}

    if selected_dict_names:
        name_set = set(selected_dict_names)
        dictionaries = [
            d for d in dictionaries
            if d.name in name_set or _has_matching_child(d, name_set)
        ]

    segments = _build_segments(dialog)
    all_matches: List[DictMatch] = []
    matches_by_level: Dict[str, int] = {}

    previous_dict_matched = True

    for cascade_idx, root_dict in enumerate(dictionaries, start=1):
        if cascade and not previous_dict_matched:
            break

        root_matches, level_counts = _search_recursive(
            node=root_dict,
            turns=turns,
            channel_map=channel_map,
            allowed_turn_indices=None,
            level=1,
            dict_name=root_dict.name,
            cascade_order=cascade_idx,
        )

        all_matches.extend(root_matches)
        this_dict_matched = len(root_matches) > 0
        previous_dict_matched = previous_dict_matched and this_dict_matched

        for level_key, count in level_counts.items():
            matches_by_level[level_key] = (
                matches_by_level.get(level_key, 0) + count
            )

    return SearchResult(
        segments=segments,
        total_matches=len(all_matches),
        matches=all_matches,
        matches_by_level=matches_by_level,
        search_source="morph",
    )


# ---------------------------------------------------------------------------
# Recursive search
# ---------------------------------------------------------------------------


def _search_recursive(
    node: DictionaryNode,
    turns: List[dict],
    channel_map: Dict[int, str],
    allowed_turn_indices: Optional[Set[int]],
    level: int,
    dict_name: str,
    cascade_order: int = 1,
) -> Tuple[List[DictMatch], Dict[str, int]]:
    """Recursively search a dictionary node and its children.

    INV-6: Container nodes (no conditions) pass the same level to children.
    INV-7: GATE — children search ALL turns if parent matched, else skip.

    Negated conditions (is_negated=True from logic_builder):
      If a negated condition matches, the ENTIRE node result is suppressed.
      This implements the НЕ (LEXEME) operator from SmartLogger spec [4].
    """
    all_matches: List[DictMatch] = []
    level_counts: Dict[str, int] = {}

    # Build search scope
    if allowed_turn_indices is not None:
        if not allowed_turn_indices:
            # Empty set = gate closed, skip entirely
            return [], {}
        search_turns = [t for i, t in enumerate(turns) if i in allowed_turn_indices]
        index_mapping = {}
        new_idx = 0
        for orig_idx in range(len(turns)):
            if orig_idx in allowed_turn_indices:
                index_mapping[new_idx] = orig_idx
                new_idx += 1
    else:
        search_turns = turns
        index_mapping = {i: i for i in range(len(turns))}

    if node.conditions:
        # This node has conditions — it owns this level
        matched_original_indices: Set[int] = set()
        node_matches: List[DictMatch] = []
        suppressed = False

        for condition in node.conditions:
            # Check if this is a negated condition (НЕ operator)
            is_negated = getattr(condition, 'is_exception', False)

            # Also check PhraseGroup.is_negated if available
            # (from corrected logic_builder)
            pg_negated = False
            if node.phrase_groups:
                for pg in node.phrase_groups:
                    if hasattr(pg, 'is_negated') and pg.is_negated:
                        phrase_text = " ".join(pg.words)
                        if phrase_text == condition.text:
                            pg_negated = True
                            break

            condition_is_negated = is_negated or pg_negated

            condition_matches = _match_condition(
                condition=condition,
                turns=search_turns,
                channel_map=(
                    channel_map if allowed_turn_indices is None
                    else {ni: channel_map[oi] for ni, oi in index_mapping.items()}
                ),
            )

            if condition_is_negated:
                # НЕ-condition: if found, suppress entire node
                if condition_matches:
                    suppressed = True
                    break
                # If not found — good, continue
                continue

            # Positive condition
            for new_idx, speaker, detail in condition_matches:
                orig_idx = index_mapping.get(new_idx, new_idx)
                matched_original_indices.add(orig_idx)

                node_matches.append(DictMatch(
                    phrase_text=condition.text,
                    matched_text=detail.get("matched_text", condition.text),
                    matched_start=detail.get("matched_start", -1),
                    matched_end=detail.get("matched_end", -1),
                    quarter=dict_name,
                    turn_index=orig_idx,
                    speaker=speaker,
                    match_type=(
                        "exact_bow" if condition.is_exact else "morph_bow"
                    ),
                    word_distance_used=level,
                    cascade_order=cascade_order,
                    is_exact_match=condition.is_exact,
                    word_distance=condition.word_distance,
                    channel_constraint=condition.channel_constraint,
                    dict_level=level,
                ))

        # Apply suppression
        if not suppressed:
            all_matches.extend(node_matches)

        level_key = str(level)
        level_counts[level_key] = len(node_matches) if not suppressed else 0

        # GATE for children: if this node matched → children search ALL turns
        child_allowed: Optional[Set[int]] = (
            None if (matched_original_indices and not suppressed) else set()
        )

        for child in node.children:
            child_matches, child_counts = _search_recursive(
                node=child,
                turns=turns,
                channel_map=channel_map,
                allowed_turn_indices=child_allowed,
                level=level + 1,
                dict_name=child.name,
                cascade_order=cascade_order,
            )
            all_matches.extend(child_matches)
            for k, v in child_counts.items():
                level_counts[k] = level_counts.get(k, 0) + v
    else:
        # INV-6: Container node — children inherit same level
        for child in node.children:
            child_matches, child_counts = _search_recursive(
                node=child,
                turns=turns,
                channel_map=channel_map,
                allowed_turn_indices=allowed_turn_indices,
                level=level,
                dict_name=child.name,
                cascade_order=cascade_order,
            )
            all_matches.extend(child_matches)
            for k, v in child_counts.items():
                level_counts[k] = level_counts.get(k, 0) + v

    return all_matches, level_counts


# ---------------------------------------------------------------------------
# Condition matching
# ---------------------------------------------------------------------------


def _match_condition(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
) -> List[Tuple[int, str, dict]]:
    """Match a single condition against dialogue turns.

    CHANGES from original:
      1. INV-8 REMOVED: is_exact from XML is now passed through [1][2][4].
         Quotes mean exact word form (no lemmatization) but FREE word order.
      2. WITHOUT filter applied from condition.without_list [1][3].

    Args:
        condition: The phrase condition to search for.
        turns: Dialogue turns in smartlogger format.
        channel_map: Turn index → speaker mapping.

    Returns:
        List of (turn_index, speaker, detail_dict) tuples.
    """
    matches = _do_match(condition, turns, channel_map)

    # Apply WITHOUT filter from XML <ExtraLimitations>
    if matches and condition.without_list:
        if _check_without(turns, condition.without_list):
            return []

    return matches


def _do_match(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
) -> List[Tuple[int, str, dict]]:
    """Execute the actual matching algorithm."""
    try:
        from app.services.morph_matcher import match_phrase_morphological_detailed
        # Pass real is_exact flag — no longer ignored (INV-8 removed)
        return match_phrase_morphological_detailed(
            phrase_text=condition.text,
            word_distance=condition.word_distance,
            channel_constraint=condition.channel_constraint,
            turns=turns,
            channel_map=channel_map,
            is_exact=condition.is_exact,
        )
    except ImportError:
        logger.warning("morph_matcher unavailable — trying smartlogger")

    try:
        from smartlogger.matcher import match_phrase_sliding_window
        simple = match_phrase_sliding_window(
            phrase_text=condition.text,
            word_distance=condition.word_distance,
            channel_constraint=condition.channel_constraint,
            turns=turns,
            channel_map=channel_map,
        )
        return [
            (idx, spk, {
                "matched_text": condition.text,
                "matched_start": -1,
                "matched_end": -1,
            })
            for idx, spk in simple
        ]
    except ImportError:
        logger.warning("smartlogger unavailable — using fallback")

    return _fallback_match(condition, turns, channel_map)


def _check_without(turns: List[dict], without_list: List[str]) -> bool:
    """Check if any WITHOUT phrase appears in the dialogue.

    Uses morphological BOW matching (same as main search) to avoid
    asymmetry where main search finds morphological variants but
    WITHOUT check misses them [1].
    """
    try:
        from app.services.morph_matcher import match_phrase_morphological
        for phrase in without_list:
            channel_map = {i: "" for i in range(len(turns))}
            matches = match_phrase_morphological(
                phrase_text=phrase,
                word_distance=2,
                channel_constraint="ANY",
                turns=turns,
                channel_map=channel_map,
                is_exact=False,
            )
            if matches:
                return True
        return False
    except ImportError:
        pass

    try:
        from smartlogger.matcher import check_without as sl_check
        return sl_check(turns, without_list)
    except ImportError:
        pass

    return False


# ---------------------------------------------------------------------------
# Fallback matching
# ---------------------------------------------------------------------------


def _fallback_match(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
) -> List[Tuple[int, str, dict]]:
    """Fallback match when morph_matcher and smartlogger unavailable.

    Uses simple bag-of-words with exact string comparison (no morphology).
    Word order is FREE (per SmartLogger spec [4]).
    """
    import re
    _pattern = re.compile(r'[а-яёa-z0-9]+')

    def tokenize(text: str) -> List[str]:
        return _pattern.findall(text.lower())

    phrase_words = tokenize(condition.text)
    if not phrase_words:
        return []

    matches: List[Tuple[int, str, dict]] = []
    window_size = len(phrase_words) + condition.word_distance

    for turn_idx, turn in enumerate(turns):
        speaker = channel_map.get(turn_idx, "")
        if condition.channel_constraint == "CLIENT" and speaker != "Клиент":
            continue
        if condition.channel_constraint == "OPERATOR" and speaker != "Сотрудник":
            continue

        turn_text = turn.get("text", "")
        turn_words = tokenize(turn_text)
        if len(turn_words) < len(phrase_words):
            continue

        word_positions = [
            (m.start(), m.end())
            for m in _pattern.finditer(turn_text.lower())
        ]

        for i in range(len(turn_words) - len(phrase_words) + 1):
            end_idx = min(i + window_size, len(turn_words))
            window = turn_words[i:end_idx]

            # BOW match — free word order, exact string (no morphology)
            matched_indices = _bow_match_fallback(window, phrase_words)

            if matched_indices is not None:
                abs_indices = [i + idx for idx in matched_indices]
                first = min(abs_indices)
                last = max(abs_indices)
                span_start = word_positions[first][0] if first < len(word_positions) else -1
                span_end = word_positions[last][1] if last < len(word_positions) else -1
                matched_text = (
                    turn_text[span_start:span_end]
                    if span_start >= 0 and span_end >= 0
                    else condition.text
                )
                matches.append((turn_idx, speaker, {
                    "matched_text": matched_text,
                    "matched_start": span_start,
                    "matched_end": span_end,
                }))
                break

    return matches


def _bow_match_fallback(
    window: List[str], phrase_words: List[str]
) -> Optional[List[int]]:
    """Simple BOW match without morphology — exact string, free order."""
    if len(window) < len(phrase_words):
        return None

    used = [False] * len(window)
    matched_indices: List[int] = []

    for p_word in phrase_words:
        found = False
        for w_idx in range(len(window)):
            if used[w_idx]:
                continue
            if window[w_idx] == p_word:
                used[w_idx] = True
                matched_indices.append(w_idx)
                found = True
                break
        if not found:
            return None

    return matched_indices


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_turns(dialog: ParsedDialog) -> List[dict]:
    """Convert ParsedDialog to smartlogger turn format.

    Args:
        dialog: Parsed dialogue.

    Returns:
        List of {"speaker": str, "text": str} dicts.
    """
    return [
        {"speaker": turn.speaker, "text": turn.text}
        for turn in dialog.turns
    ]


def _build_segments(dialog: ParsedDialog) -> List[TextSegment]:
    """Build TextSegment list from dialogue turns.

    Args:
        dialog: Parsed dialogue.

    Returns:
        List of TextSegment for the search result.
    """
    return [
        TextSegment(
            turn_index=turn.turn_index,
            text=turn.text,
            speaker=turn.speaker,
        )
        for turn in dialog.turns
    ]


def _has_matching_child(node: DictionaryNode, name_set: set) -> bool:
    """Check if any descendant dictionary matches the name set.

    Args:
        node: Root dictionary node.
        name_set: Set of dictionary names to match.

    Returns:
        True if any descendant (or self) is in the name set.
    """
    if node.name in name_set:
        return True
    return any(_has_matching_child(child, name_set) for child in node.children)

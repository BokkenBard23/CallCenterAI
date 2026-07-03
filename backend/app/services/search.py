"""Hierarchical search engine service.

CRITICAL ALGORITHM (INV-5):
  1. For each ROOT dictionary (parent_name is None):
     - Run morphological sliding-window on FULL dialogue text → level=1 matches
  2. For each CHILD dictionary (parent_name matches a root dict):
     - Run search ONLY on turns where parent had matches → level=2
  3. Recurse for grandchildren → level=3, etc.
  4. Build TextSegment array from dialogue turns
  5. Collect DictMatch results with level tracking

Key invariant: child search happens ONLY within parent-matched fragments.

LEVEL ASSIGNMENT (INV-6):
  Level numbers correspond to actual search depth, NOT tree depth.
  Container nodes (no conditions, only attributes/children) do NOT
  consume a level — their children inherit the same level.
  This ensures Q1 phrases are level=1, Q2 phrases are level=2, etc.,
  matching the SmartLogger and frontend color coding.

CASCADE SEMANTICS (INV-7 — revised GATE model):
  When cascade=True (default), hierarchy is a PREREQUISITE GATE,
  not a turn-level filter. Each level searches ALL turns in the
  dialogue, but ONLY IF the previous level had at least one match.
  This is the SmartLogger behavior:
    1. Dict 1 (e.g. "Риск расторжения") searches ALL turns
    2. Dict 2 (e.g. "Отказ от диагностики") searches ALL turns,
       BUT ONLY IF Dict 1 had at least one match (gate passed)
    3. Dict 3 searches ALL turns, BUT ONLY IF both Dict 1 and
       Dict 2 had at least one match each
  Rationale: Q2 phrases (e.g. "клиент отказывается") typically
  appear in DIFFERENT turns than Q1 phrases (e.g. "риск
  расторжения"). Restricting Q2 to Q1-matched turns would never
  find a match. The gate model correctly captures: "Q2 is
  relevant only when Q1 matched somewhere in this dialogue."
  When cascade=False, each dictionary searches ALL turns independently.

MORPHOLOGICAL MATCHING (INV-8):
  Uses app.services.morph_matcher for pymorphy3-based lemma comparison.
  Russian verbs in different aspects (переходить/перейти, перешёл/перейти)
  are correctly matched via their shared lemma group.
  IMPORTANT: The is_exact flag from XML is IGNORED for matching.
  SmartLogger always uses morphological BOW matching; the "exact" flag
  only reflects XML quoting convention, not a different matching mode.
  Using exact matching loses ~82% of valid matches on production data.

Uses smartlogger.tokenizer.tokenize() — NOT .split() (INV-2).
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


async def run_hierarchical_search(
    dialog: ParsedDialog,
    dictionaries: List[DictionaryNode],
    selected_dict_names: Optional[List[str]] = None,
    cascade: bool = True,
) -> SearchResult:
    """Run hierarchical phrase matching on a parsed dialogue.

    CASCADE MODE (default=True) — GATE semantics (INV-7 revised):
      Hierarchy is a prerequisite gate, NOT a turn-level filter.
      Each subsequent dictionary searches ALL turns in the dialogue,
      but ONLY IF the previous dictionary had at least one match.
      This is the SmartLogger behavior:
        1. Dict 1 (e.g. "Риск расторжения") searches ALL turns
        2. Dict 2 (e.g. "Клиент отказывается") searches ALL turns,
           BUT ONLY IF Dict 1 had at least one match (gate passed)
        3. Dict 3 searches ALL turns, BUT ONLY IF Dicts 1 and 2
           both had at least one match each
      Rationale: Q2 phrases typically appear in DIFFERENT turns
      than Q1 phrases. Restricting Q2 to Q1-matched turns would
      never find a match. The gate model correctly captures:
      "Q2 is relevant only when Q1 matched somewhere in dialogue."

    NON-CASCADE MODE (cascade=False):
      Each dictionary searches ALL turns independently.

    Args:
        dialog: The parsed dialogue with turns.
        dictionaries: List of root dictionary nodes (with children).
        selected_dict_names: Optional filter — only search these dictionaries.
            Empty/None means search all.
        cascade: If True, use cascade (gate) mode where each
            subsequent dictionary only searches if ALL previous
            dictionaries had at least one match.

    Returns:
        SearchResult with segments, total_matches, matches, and level statistics.
    """
    if not dialog.turns:
        return SearchResult(
            segments=[], total_matches=0, matches=[], matches_by_level={},
            search_source="morph",
        )

    # Build turn data in smartlogger format
    turns = _build_smartlogger_turns(dialog)

    # Build channel map: turn_index → speaker
    channel_map = {i: turn.speaker for i, turn in enumerate(dialog.turns)}

    # Filter dictionaries if specific ones are requested
    if selected_dict_names:
        name_set = set(selected_dict_names)
        dictionaries = [d for d in dictionaries if d.name in name_set or _has_matching_child(d, name_set)]

    # Build segments from dialogue turns
    segments = _build_segments(dialog)

    # Run hierarchical search with cascade
    all_matches: List[DictMatch] = []
    matches_by_level: Dict[str, int] = {}
    # INV-7 revised: Cascade is a GATE, not a turn-level filter.
    # Each subsequent ROOT dictionary searches ALL turns if the previous
    # one had ANY match in the dialogue. This is the SmartLogger behavior:
    #   1. Dict 1 (e.g. "Риск расторжения") searches ALL turns
    #   2. Dict 2 (e.g. "Отказ от диагностики") searches ALL turns,
    #      BUT ONLY IF Dict 1 had at least one match (gate passed)
    #   3. Dict 3 searches ALL turns, BUT ONLY IF Dicts 1 and 2 both matched
    # If any previous dict has zero matches → the cascade is broken,
    # all subsequent dicts are skipped.
    previous_dict_matched: bool = True  # Gate: True = all previous dicts matched

    for cascade_idx, root_dict in enumerate(dictionaries, start=1):
        # Gate check: if any previous dictionary in the cascade had zero
        # matches, skip this and all subsequent dictionaries.
        if cascade and not previous_dict_matched:
            break

        # Always search ALL turns (allowed=None) — the gate only
        # controls whether we search at all, not WHICH turns.
        root_matches, level_counts = _search_recursive(
            root_dict=root_dict,
            turns=turns,
            channel_map=channel_map,
            allowed_turn_indices=None,  # Always search all turns
            level=1,
            dict_name=root_dict.name,
            cascade_order=cascade_idx,
        )
        all_matches.extend(root_matches)

        # Update gate: did this dictionary match anywhere?
        this_dict_matched = len(root_matches) > 0
        previous_dict_matched = previous_dict_matched and this_dict_matched

        for level_key, count in level_counts.items():
            matches_by_level[level_key] = matches_by_level.get(level_key, 0) + count

    return SearchResult(
        segments=segments,
        total_matches=len(all_matches),
        matches=all_matches,
        matches_by_level=matches_by_level,
        search_source="morph",
    )


def _search_recursive(
    root_dict: DictionaryNode,
    turns: List[dict],
    channel_map: Dict[int, str],
    allowed_turn_indices: Optional[Set[int]],
    level: int,
    dict_name: str,
    cascade_order: int = 1,
) -> Tuple[List[DictMatch], Dict[str, int]]:
    """Recursively search a dictionary and its children.

    CRITICAL: When allowed_turn_indices is not None, the child search
    is restricted to ONLY those turns. This is the hierarchical invariant.

    LEVEL ASSIGNMENT (INV-6):
      Container nodes (no conditions, only attributes/children) do NOT
      consume a level number. When recursing through such a node,
      children inherit the SAME level as the container, because the
      container itself performed no search.
      This ensures:
        - Root SpeechLabRequest (no conditions) → children start at level=1
        - Q1 conditions → level=1 (not level=2)
        - Q2 conditions → level=2 (not level=3)
      The frontend color coding (Level 1=yellow, Level 2=green, etc.)
      must match the semantic search depth, not the XML tree depth.

    Args:
        root_dict: Dictionary node to search.
        turns: All dialogue turns in smartlogger format.
        channel_map: Turn index → speaker mapping.
        allowed_turn_indices: If set, restrict search to these turns only.
        level: Current search level (1=first searchable depth, etc.).
        dict_name: Name of the dictionary being searched.
        cascade_order: Dictionary position in cascade sequence (1-based).

    Returns:
        Tuple of (matches, level_counts).
    """
    all_matches: List[DictMatch] = []
    level_counts: Dict[str, int] = {}

    # Filter turns if restricted
    search_turns = turns
    search_channel_map = channel_map
    if allowed_turn_indices is not None:
        search_turns = [t for i, t in enumerate(turns) if i in allowed_turn_indices]
        # Remap indices: original turn index → position in filtered list
        index_mapping = {}
        new_idx = 0
        for orig_idx in range(len(turns)):
            if orig_idx in allowed_turn_indices:
                index_mapping[new_idx] = orig_idx
                new_idx += 1
    else:
        index_mapping = {i: i for i in range(len(turns))}

    # Search with this dictionary's conditions
    if root_dict.conditions:
        # This node has actual search conditions → it owns this level
        # TODO: Attribute filtering (attribute_tree).
        # root_dict.attribute_tree contains AND/OR/NOT logic for call metadata
        # (Duration, CallDirection, RemotePhoneNumber, etc.). However, RTF
        # dialogues do not carry call metadata, so attribute filters cannot
        # be applied at search time. When call metadata becomes available
        # (e.g. from a CRM integration), evaluate attribute_tree against
        # the call's metadata here and skip the entire dictionary if the
        # attribute tree evaluates to False.
        matched_original_indices: Set[int] = set()

        for condition in root_dict.conditions:
            condition_matches = _match_condition(
                condition=condition,
                turns=search_turns,
                channel_map=search_channel_map if allowed_turn_indices is None else {
                    new_i: channel_map[orig_i]
                    for new_i, orig_i in index_mapping.items()
                },
            )

            for new_idx, speaker, detail in condition_matches:
                orig_idx = index_mapping.get(new_idx, new_idx)
                matched_original_indices.add(orig_idx)

                all_matches.append(
                    DictMatch(
                        phrase_text=condition.text,
                        matched_text=detail.get("matched_text", condition.text),
                        matched_start=detail.get("matched_start", -1),
                        matched_end=detail.get("matched_end", -1),
                        quarter=dict_name,
                        turn_index=orig_idx,
                        speaker=speaker,
                        match_type="exact" if condition.is_exact else "sliding_window",
                        word_distance_used=level,  # Hierarchy level within dictionary
                        cascade_order=cascade_order,  # Dictionary position in cascade
                        is_exact_match=condition.is_exact,
                        # Extended fields (AG-UIREWORK-1): from DictionaryCondition
                        word_distance=condition.word_distance,
                        channel_constraint=condition.channel_constraint,
                        dict_level=level,  # Alias for word_distance_used — explicit for frontend
                    )
                )

        # Track level counts
        level_key = str(level)
        level_counts[level_key] = len(all_matches)

        # Recurse into children — GATE semantics (INV-7 revised):
        # If this node matched somewhere in the dialogue → children search
        # the ENTIRE dialogue (allowed=None). The hierarchy is a prerequisite
        # gate, NOT a turn-level filter. Q2 must find its phrases in ANY
        # turn, not only turns where Q1 matched.
        # If this node did NOT match → children are skipped (empty set).
        child_allowed: Optional[Set[int]] = None if matched_original_indices else set()

        for child in root_dict.children:
            child_matches, child_counts = _search_recursive(
                root_dict=child,
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
        # INV-6: Container node — no conditions, just structure.
        # This node does NOT own a level. Children inherit the same level.
        # Example: Root SpeechLabRequest with only attributes → its children
        # (Q1) should be level=1, not level=2.
        for child in root_dict.children:
            child_matches, child_counts = _search_recursive(
                root_dict=child,
                turns=turns,
                channel_map=channel_map,
                allowed_turn_indices=allowed_turn_indices,
                level=level,  # Same level — container did not search
                dict_name=child.name,
                cascade_order=cascade_order,
            )
            all_matches.extend(child_matches)
            for k, v in child_counts.items():
                level_counts[k] = level_counts.get(k, 0) + v

    return all_matches, level_counts


def _match_condition(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
) -> List[Tuple[int, str, dict]]:
    """Match a single condition against dialogue turns.

    ALWAYS uses morphological bag-of-words matching (pymorphy3 lemma comparison)
    which correctly handles Russian verb aspectual pairs AND word reordering:
      "переходить" matches "перейти", "перешёл", "перейду", etc.
      "не хочу подключавать" matches "не подключил хотел" (any word order)

    IMPORTANT (INV-8 — morphological override):
      The is_exact flag from XML reflects SmartLogger quoting convention
      (phrases in quotes), NOT a matching mode. The original SmartLogger
      always uses morphological BOW matching. Using exact matching loses
      ~82% of valid matches (420 vs 2354 on production data) because:
        - "не нужен мне" (dict) vs "не нужен я" (dialog) — form variation
        - "не устраивает меня" (dict) vs "меня не устраивает" (dialog) — reorder
        - "я не буду платить" (dict) vs "заплатите... я не буду" (dialog) — aspect
      Therefore is_exact is preserved in the data model for display/sorting
      but IGNORED for matching — always is_exact=False (morphological BOW).

    Returns detailed match info including matched_text and character offsets.

    Args:
        condition: The phrase condition to search for.
        turns: Dialogue turns in smartlogger format.
        channel_map: Turn index → speaker mapping.

    Returns:
        List of (turn_index, speaker, detail_dict) tuples for matches.
        detail_dict has: matched_text, matched_start, matched_end
    """
    try:
        from app.services.morph_matcher import match_phrase_morphological_detailed

        # INV-8: Always use morphological BOW matching, regardless of is_exact.
        # The is_exact flag is an XML quoting artifact, not a matching mode.
        matches = match_phrase_morphological_detailed(
            phrase_text=condition.text,
            word_distance=condition.word_distance,
            channel_constraint=condition.channel_constraint,
            turns=turns,
            channel_map=channel_map,
            is_exact=False,  # INV-8: Always morphological
        )
        return matches

    except ImportError:
        logger.warning("morph_matcher not available — trying smartlogger exact match")
        try:
            from smartlogger.matcher import match_phrase_sliding_window
            simple_matches = match_phrase_sliding_window(
                phrase_text=condition.text,
                word_distance=condition.word_distance,
                channel_constraint=condition.channel_constraint,
                turns=turns,
                channel_map=channel_map,
            )
            # Convert to detailed format (no offsets from exact match)
            return [(idx, spk, {"matched_text": condition.text, "matched_start": -1, "matched_end": -1})
                    for idx, spk in simple_matches]
        except ImportError:
            logger.warning("smartlogger not available — using built-in sliding window")
            return _fallback_match(condition, turns, channel_map)


def _fallback_match(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
) -> List[Tuple[int, str, dict]]:
    """Fallback morphological sliding-window match when smartlogger is unavailable.

    Uses pymorphy3 lemma comparison via app.services.morph_matcher.
    Falls back to exact token match if pymorphy3 is also unavailable.
    Uses smartlogger.tokenizer.tokenize() for tokenization (INV-2).

    When condition.is_exact is True, uses exact string matching (no
    lemmatization, ordered subsequence) instead of morphological matching.

    Returns detailed match info including matched_text and character offsets.

    Args:
        condition: The phrase condition to search for.
        turns: Dialogue turns.
        channel_map: Turn index → speaker mapping.

    Returns:
        List of (turn_index, speaker, detail_dict) tuples for matches.
    """
    try:
        from smartlogger.tokenizer import tokenize
    except ImportError:
        import re
        _pattern = re.compile(r'[а-яёa-z0-9]+')
        def tokenize(text: str) -> list[str]:
            return _pattern.findall(text.lower())

    try:
        from app.services.morph_matcher import same_lemma, get_lemma
        use_morph = True
    except ImportError:
        use_morph = False

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

        # Find word positions for offset mapping
        import re
        word_positions = [(m.start(), m.end()) for m in re.finditer(r'[а-яёa-z0-9]+', turn_text.lower())]

        if condition.is_exact:
            # Exact match: ordered subsequence, no lemmatization
            for i in range(len(turn_words) - len(phrase_words) + 1):
                end_idx = min(i + window_size, len(turn_words))
                window = turn_words[i:end_idx]
                phrase_idx = 0
                last_window_idx = i
                for w_idx in range(len(window)):
                    if phrase_idx >= len(phrase_words):
                        break
                    if window[w_idx] == phrase_words[phrase_idx]:
                        last_window_idx = i + w_idx
                        phrase_idx += 1
                    if phrase_idx == len(phrase_words):
                        span_start = word_positions[i][0] if i < len(word_positions) else -1
                        span_end = word_positions[last_window_idx][1] if last_window_idx < len(word_positions) else -1
                        matched_text = turn_text[span_start:span_end] if span_start >= 0 else condition.text

                        matches.append((turn_idx, speaker, {
                            "matched_text": matched_text,
                            "matched_start": span_start,
                            "matched_end": span_end,
                        }))
                        break
                if phrase_idx == len(phrase_words):
                    break
        else:
            # Morphological bag-of-words match (consistent with morph_matcher._bag_of_words_match)
            # Words from the phrase can appear in ANY ORDER within the window,
            # each phrase word matches exactly one window word (greedy one-to-one).
            for i in range(len(turn_words) - len(phrase_words) + 1):
                end_idx = min(i + window_size, len(turn_words))
                window = turn_words[i:end_idx]

                # Greedy one-to-one: each phrase word must find a match in the window
                used = [False] * len(window)
                all_matched = True
                for p_word in phrase_words:
                    found = False
                    for w_idx in range(len(window)):
                        if used[w_idx]:
                            continue
                        if use_morph:
                            if same_lemma(window[w_idx], p_word):
                                used[w_idx] = True
                                found = True
                                break
                        else:
                            if window[w_idx] == p_word:
                                used[w_idx] = True
                                found = True
                                break
                    if not found:
                        all_matched = False
                        break

                if all_matched:
                    span_start = word_positions[i][0] if i < len(word_positions) else -1
                    span_end = word_positions[end_idx - 1][1] if end_idx - 1 < len(word_positions) else -1
                    matched_text = turn_text[span_start:span_end] if span_start >= 0 else condition.text

                    matches.append((turn_idx, speaker, {
                        "matched_text": matched_text,
                        "matched_start": span_start,
                        "matched_end": span_end,
                    }))
                    break  # One match per turn is enough

    # Apply WITHOUT filter
    if matches and condition.without_list:
        try:
            from smartlogger.matcher import check_without
            if check_without(turns, condition.without_list):
                return []
        except ImportError:
            pass  # No filter available — keep matches

    return matches


def _build_smartlogger_turns(dialog: ParsedDialog) -> List[dict]:
    """Convert ParsedDialog turns to smartlogger format.

    smartlogger expects: [{"speaker": "Клиент"|"Сотрудник", "text": str}, ...]

    Args:
        dialog: ParsedDialog with DialogueTurn list.

    Returns:
        List of turn dicts for smartlogger.
    """
    return [
        {"speaker": turn.speaker, "text": turn.text}
        for turn in dialog.turns
    ]


def _build_segments(dialog: ParsedDialog) -> List[TextSegment]:
    """Build TextSegment array from dialogue turns.

    Each turn becomes one segment. The frontend renderer will
    overlay match highlights on these segments.

    Args:
        dialog: ParsedDialog with turns.

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


def _has_matching_child(node: DictionaryNode, name_set: Set[str]) -> bool:
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

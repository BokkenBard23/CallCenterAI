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
    ExtraLimitation,
    ExtraLimitationLimit,
    ParsedDialog,
    SearchResult,
    TextSegment,
)
from app.services.logic_builder import build_phrase_logic_tree

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
    parent_match_times: Optional[List[float]] = None,
) -> Tuple[List[DictMatch], Dict[str, int]]:
    """Recursively search a dictionary node and its children.

    INV-6: Container nodes (no conditions) pass the same level to children.
    INV-7: GATE — children search ALL turns if parent matched, else skip.

    Negated conditions (is_negated=True from logic_builder):
      If a negated condition matches, the ENTIRE node result is suppressed.
      This implements the НЕ (LEXEME) operator from SmartLogger spec [4].

    UI-2.6 — Time-gap filtering (EventType=Parent):
      parent_match_times is the list of THIS node's parent matched turn
      start_offsets (seconds). For root-level dictionaries it is None —
      Parent-type limits are then skipped. The function passes its OWN
      matched turn start_offsets down to children so children can evaluate
      their Parent-type limits relative to this node's matches.

    UI-2.6 — Remainder catch-all fallback:
      Matches from <SpeechLabRemainderRequest> nodes (node.is_remainder=True)
      are marked DictMatch.is_remainder=True and included in results like
      any other match. They do NOT change the GATE — children of a remainder
      node follow the same GATE rule (gate opens iff this node matched).
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

    # Mark matches coming from a <SpeechLabRemainderRequest> node so the FE
    # can render them distinctly if desired. Remainder matches are still
    # included in all_matches and participate in GATE for children exactly
    # like ordinary matches — they do not get special catch-all suppression.
    is_remainder_node = bool(getattr(node, "is_remainder", False))

    if node.conditions:
        # This node has conditions — it owns this level
        matched_original_indices: Set[int] = set()
        matched_phrase_texts: Set[str] = set()
        node_matches: List[DictMatch] = []
        suppressed = False

        # Collect start_offsets of THIS node's matches for children's
        # EventType=Parent time-gap filtering.
        node_match_times: List[float] = []

        # N18 perf optimization: tokenize each search turn + compute word
        # (start,end) char positions ONCE for the whole node. Every condition
        # of this node sees the same `search_turns`, so the per-turn work
        # does not depend on the phrase and is reused across all conditions.
        # For typical production dictionaries (~5 conditions per node,
        # ~50 turns per dialogue) this cuts tokenizer calls from
        # ~5*50*2 = 500 down to ~50*2 = 100 per node.
        precomputed_turn_words: Optional[List[List[str]]] = None
        precomputed_word_positions: Optional[
            List[List[Tuple[int, int]]]
        ] = None
        try:
            from app.services.morph_matcher import (
                _find_word_positions,
                _tokenize,
            )

            precomputed_turn_words = [
                _tokenize(t.get("text", "")) for t in search_turns
            ]
            precomputed_word_positions = [
                _find_word_positions(t.get("text", "")) for t in search_turns
            ]
        except ImportError:
            # morph_matcher unavailable — _do_match will fall back to
            # smartlogger or _fallback_match, which tokenize internally.
            pass

        for condition in node.conditions:
            # Single source of truth for НЕ: condition.is_exception
            # (set in xml_parser._parse_tokens_enriched from pg.is_negated).
            # The redundant PhraseGroup.is_negated re-scan loop (RISK-1/N2)
            # has been removed — is_exception already captures the same signal.
            condition_is_negated = getattr(condition, "is_exception", False)

            condition_matches = _match_condition(
                condition=condition,
                turns=search_turns,
                channel_map=(
                    channel_map if allowed_turn_indices is None
                    else {ni: channel_map[oi] for ni, oi in index_mapping.items()}
                ),
                parent_match_times=parent_match_times,
                precomputed_word_positions=precomputed_word_positions,
                precomputed_turn_words=precomputed_turn_words,
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

                # Track this match's start_offset for children's Parent filter.
                t_offset = _turn_offset(turns, orig_idx, "start_offset")
                if t_offset is not None:
                    node_match_times.append(float(t_offset))

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
                    is_remainder=is_remainder_node,
                ))

            # Track which positive phrase texts matched — used by the
            # phrase_logic_tree GATE below (N15).
            if condition_matches:
                matched_phrase_texts.add(condition.text)

        # Apply suppression
        if not suppressed:
            all_matches.extend(node_matches)

        level_key = str(level)
        level_counts[level_key] = len(node_matches) if not suppressed else 0

        # GATE for children (N15): the gate opens iff the phrase_logic_tree
        # of this node evaluates True (ALL AND-children match, ANY OR-child
        # matches, NOT-child not matched) AND the node was not suppressed by
        # an explicit НЕ-condition.
        #
        # Backward-compat: when node.phrase_groups is empty (e.g. manually
        # constructed test fixtures without phrase_groups, or legacy parsed
        # nodes), fall back to the legacy "any positive match" semantics —
        # gate opens iff at least one positive condition matched.
        if node.phrase_groups:
            node_matched = evaluate_phrase_logic_tree(
                node.phrase_groups, matched_phrase_texts
            )
        else:
            node_matched = bool(matched_original_indices)
        child_allowed: Optional[Set[int]] = (
            None if (node_matched and not suppressed) else set()
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
                parent_match_times=node_match_times if node_match_times else None,
            )
            all_matches.extend(child_matches)
            for k, v in child_counts.items():
                level_counts[k] = level_counts.get(k, 0) + v
    else:
        # ────────────────────────────────────────────────────────────────
        # INV-6 (verified UI-2.6 BE-timestamps iteration):
        # Container node — children inherit same `level` (no level
        # consumed), `allowed_turn_indices` (GATE inheritance) and
        # `parent_match_times` (their "parent" is still the nearest
        # ancestor that produced matches — container passthrough).
        # Container nodes have NO conditions, so they:
        #   (1) do NOT increase `level` — children stay at parent's level;
        #   (2) produce NO matches of their own;
        #   (3) inherit allowed_turn_indices verbatim (open / closed / None);
        #   (4) node_matched is implicitly True via
        #       evaluate_phrase_logic_tree([], set()) == True — gate stays
        #       open for children exactly when it was open for this node.
        # Real SmartLogger dictionaries have not been observed with pure
        # container nodes (see docs/specs/smartlogger-xml-verification.md
        # V7: all 31 SpeechLabRequest nodes carry non-empty <Tokens>), but
        # the code path is intentionally supported for synthetic test
        # fixtures and forward compatibility.
        # ────────────────────────────────────────────────────────────────
        for child in node.children:
            child_matches, child_counts = _search_recursive(
                node=child,
                turns=turns,
                channel_map=channel_map,
                allowed_turn_indices=allowed_turn_indices,
                level=level,
                dict_name=child.name,
                cascade_order=cascade_order,
                parent_match_times=parent_match_times,
            )
            all_matches.extend(child_matches)
            for k, v in child_counts.items():
                level_counts[k] = level_counts.get(k, 0) + v

    return all_matches, level_counts


# ---------------------------------------------------------------------------
# Condition matching
# ---------------------------------------------------------------------------


# Speaker ↔ channel mapping (mirrors morph_matcher.py hardcode).
_SPEAKER_BY_CHANNEL: Dict[str, str] = {
    "CLIENT": "Клиент",
    "OPERATOR": "Сотрудник",
}


def _has_timestamps(turns: List[dict]) -> bool:
    """Return True iff at least one turn has a non-None start_offset.

    Time-gap filtering is only meaningful when turns carry timing. RTF files
    without reliable timing produce turns with start_offset=None, in which
    case the filter becomes a no-op (per UI-2.6 contract: skip filtering
    rather than silently dropping all matches).
    """
    return any(t.get("start_offset") is not None for t in turns)


def _turn_offset(
    turns: List[dict], turn_idx: int, key: str
) -> Optional[float]:
    """Safely read `start_offset`/`end_offset` from a turn."""
    if 0 <= turn_idx < len(turns):
        return turns[turn_idx].get(key)
    return None


def _find_channel_gaps(
    turns: List[dict], channel: str, min_duration: float
) -> List[Tuple[float, float]]:
    """Find time intervals where `channel` has no speech for >= min_duration.

    A gap is a maximal interval between consecutive same-channel turn
    intervals whose length (in seconds) >= min_duration. Gaps before the
    first and after the last turn of the channel are also included.

    For channel=ANY the function treats *any* turn as filling time, so gaps
    are intervals of total dialogue silence (rare; useful for testing).

    Args:
        turns: Dialogue turns with start_offset/end_offset.
        channel: "CLIENT" | "OPERATOR" | "ANY".
        min_duration: Minimum silence duration in seconds.

    Returns:
        List of (gap_start, gap_end) tuples (sorted, non-overlapping).
    """
    if not turns:
        return []

    speaker = _SPEAKER_BY_CHANNEL.get(channel.upper(), "")
    intervals: List[Tuple[float, float]] = []
    for t in turns:
        if channel.upper() == "ANY" or t.get("speaker") == speaker:
            s = t.get("start_offset")
            e = t.get("end_offset")
            if s is not None and e is not None:
                intervals.append((float(s), float(e)))

    # Dialogue bounds (first turn start to last turn end).
    dialogue_start = turns[0].get("start_offset")
    dialogue_end = turns[-1].get("end_offset")
    if dialogue_start is None or dialogue_end is None:
        return []

    if not intervals:
        # No turns of this channel — the entire dialogue is a gap.
        if dialogue_end - dialogue_start >= min_duration:
            return [(dialogue_start, dialogue_end)]
        return []

    intervals.sort(key=lambda iv: iv[0])
    gaps: List[Tuple[float, float]] = []

    # Gap before first channel turn.
    if intervals[0][0] - dialogue_start >= min_duration:
        gaps.append((dialogue_start, intervals[0][0]))

    # Gaps between channel turns.
    for i in range(1, len(intervals)):
        prev_end = intervals[i - 1][1]
        curr_start = intervals[i][0]
        if curr_start - prev_end >= min_duration:
            gaps.append((prev_end, curr_start))

    # Gap after last channel turn.
    if dialogue_end - intervals[-1][1] >= min_duration:
        gaps.append((intervals[-1][1], dialogue_end))

    return gaps


def _match_in_gaps(
    turn_idx: int,
    turns: List[dict],
    gaps: List[Tuple[float, float]],
) -> bool:
    """Return True iff the match turn's time interval is fully inside a gap."""
    s = _turn_offset(turns, turn_idx, "start_offset")
    e = _turn_offset(turns, turn_idx, "end_offset")
    if s is None or e is None:
        return False
    for g_start, g_end in gaps:
        if g_start <= s and e <= g_end:
            return True
    return False


def _apply_gap_filter(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    el: ExtraLimitation,
    limit: ExtraLimitationLimit,
) -> List[Tuple[int, str, dict]]:
    """Apply OnlyInGaps / ExcludeGaps filter using limit.value as gap threshold.

    SearchSpecifier semantics (reconstructed from real XML structure):
      - OnlyInGaps:  keep matches whose turn interval is fully inside a gap
                     (interval of silence on the limit's channel >= value sec)
      - ExcludeGaps: exclude matches whose turn interval is fully inside a gap

    limit.value is interpreted as the minimum gap duration in seconds when
    value_type == "Seconds"; otherwise filtering is skipped (returns matches
    unchanged) — the only value_type observed in real dictionaries is Seconds.
    """
    if el.search_specifier not in ("OnlyInGaps", "ExcludeGaps"):
        return matches

    if limit.value_type != "Seconds":
        return matches

    min_duration = float(limit.value)
    gaps = _find_channel_gaps(turns, limit.channel or "ANY", min_duration)
    if not gaps:
        # No qualifying gaps → OnlyInGaps keeps nothing, ExcludeGaps keeps all.
        if el.search_specifier == "OnlyInGaps":
            return []
        return matches

    if el.search_specifier == "OnlyInGaps":
        return [m for m in matches if _match_in_gaps(m[0], turns, gaps)]
    # ExcludeGaps
    return [m for m in matches if not _match_in_gaps(m[0], turns, gaps)]


def _filter_start_end(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    el: ExtraLimitation,
    limit: ExtraLimitationLimit,
) -> List[Tuple[int, str, dict]]:
    """EventType=StartEnd: keep matches in first/last N seconds of dialogue.

    - LimitType=First: keep matches with start_offset <= dialogue_start + N
    - LimitType=Last:  keep matches with end_offset >= dialogue_end - N
    """
    if not turns:
        return matches
    dialogue_start = turns[0].get("start_offset")
    dialogue_end = turns[-1].get("end_offset")
    if dialogue_start is None or dialogue_end is None:
        return matches
    if limit.value_type != "Seconds":
        return matches

    n_seconds = float(limit.value)
    if limit.limit_type == "First":
        window_end = dialogue_start + n_seconds
        result = [
            m for m in matches
            if (_turn_offset(turns, m[0], "start_offset") is not None
                and _turn_offset(turns, m[0], "start_offset") <= window_end)
        ]
    elif limit.limit_type == "Last":
        window_start = dialogue_end - n_seconds
        result = [
            m for m in matches
            if (_turn_offset(turns, m[0], "end_offset") is not None
                and _turn_offset(turns, m[0], "end_offset") >= window_start)
        ]
    else:
        # Unknown LimitType — keep matches unchanged (defensive).
        result = matches

    # Apply SearchSpecifier (OnlyInGaps / ExcludeGaps) on top.
    result = _apply_gap_filter(result, turns, el, limit)
    return result


def _filter_parent(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    el: ExtraLimitation,
    limit: ExtraLimitationLimit,
    parent_match_times: Optional[List[float]],
) -> List[Tuple[int, str, dict]]:
    """EventType=Parent: keep matches within N seconds before/after parent match.

    - SearchDirection=Before: keep matches within N seconds BEFORE a parent match
      (parent_match_time - N <= match_start <= parent_match_time)
    - SearchDirection=After:  keep matches within N seconds AFTER a parent match
      (parent_match_time <= match_start <= parent_match_time + N)

    When parent_match_times is None or empty (root-level node, no parent
    context), Parent-type limits cannot be evaluated — return matches
    unchanged (filtering skipped, per UI-2.6 contract).
    """
    if not parent_match_times:
        return matches
    if limit.value_type != "Seconds":
        return matches

    n_seconds = float(limit.value)
    result: List[Tuple[int, str, dict]] = []
    for m in matches:
        t = _turn_offset(turns, m[0], "start_offset")
        if t is None:
            continue
        if limit.search_direction == "Before":
            if any(0 <= (pt - t) <= n_seconds for pt in parent_match_times):
                result.append(m)
        elif limit.search_direction == "After":
            if any(0 <= (t - pt) <= n_seconds for pt in parent_match_times):
                result.append(m)
        else:
            # Unknown SearchDirection — keep the match (defensive).
            result.append(m)

    # Apply SearchSpecifier (OnlyInGaps / ExcludeGaps) on top.
    result = _apply_gap_filter(result, turns, el, limit)
    return result


def _filter_by_limit(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    el: ExtraLimitation,
    limit: ExtraLimitationLimit,
    parent_match_times: Optional[List[float]],
) -> List[Tuple[int, str, dict]]:
    """Dispatch a single Limit to its EventType-specific filter."""
    if el.event_type == "StartEnd":
        return _filter_start_end(matches, turns, el, limit)
    if el.event_type == "Parent":
        return _filter_parent(matches, turns, el, limit, parent_match_times)
    # Unknown EventType — keep matches unchanged (defensive).
    return matches


def _apply_time_gap_filter(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    extra_limitations: List[ExtraLimitation],
    parent_match_times: Optional[List[float]] = None,
) -> List[Tuple[int, str, dict]]:
    """Filter matches by time-gap limits from real <ExtraLimitations>.

    Real SmartLogger dictionaries store time-gap limits as
    <ExtraLimitation><EventType>StartEnd|Parent</EventType>
      <SearchSpecifier>OnlyInGaps|ExcludeGaps</SearchSpecifier>
      <Limits><Limit>...</Limit></Limits>
    </ExtraLimitation>.

    If turn timestamps (start_offset/end_offset) are unavailable → skip
    filtering entirely (return matches as-is). This matches the UI-2.6
    contract: filtering is best-effort, never silently drops all matches
    when timing data is missing.

    For EventType=StartEnd:
        - LimitType=First: keep matches in first N seconds of dialogue
        - LimitType=Last:  keep matches in last N seconds of dialogue
        - OnlyInGaps:      keep matches whose turn falls within a silence
                          gap on limit.channel of >= N seconds
        - ExcludeGaps:     exclude matches whose turn falls within such a gap

    For EventType=Parent:
        - SearchDirection=Before: keep matches within N seconds before any
          parent match (parent_match_times)
        - SearchDirection=After:  keep matches within N seconds after any
          parent match
        - OnlyInGaps / ExcludeGaps: same gap semantics, applied on top

    Args:
        matches: List of (turn_idx, speaker, detail) tuples.
        turns: Dialogue turns with optional start_offset/end_offset.
        extra_limitations: Parsed ExtraLimitation list from condition.
        parent_match_times: Optional parent node matched turn start_offsets
            (seconds). Required for EventType=Parent; None skips Parent
            filtering (root-level nodes).

    Returns:
        Filtered matches list (same tuple shape).
    """
    if not extra_limitations or not matches:
        return matches

    # Skip filtering entirely when no turn carries timing.
    if not turns or not _has_timestamps(turns):
        return matches

    filtered = list(matches)
    for el in extra_limitations:
        if not el.limits:
            continue
        for limit in el.limits:
            if not limit.enabled:
                continue
            filtered = _filter_by_limit(
                filtered, turns, el, limit, parent_match_times
            )
            if not filtered:
                break
        if not filtered:
            break

    return filtered


def _match_condition(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
    parent_match_times: Optional[List[float]] = None,
    precomputed_word_positions: Optional[List[List[Tuple[int, int]]]] = None,
    precomputed_turn_words: Optional[List[List[str]]] = None,
) -> List[Tuple[int, str, dict]]:
    """Match a single condition against dialogue turns.

    CHANGES from original [1][2][4]:
      1. INV-8 REMOVED: is_exact from XML is now passed through [1][2][4].
         Quotes mean exact word form (no lemmatization) but FREE word order.
      2. V3/UI-2.6: WITHOUT filter from condition.without_list is NO LONGER
         applied — real SmartLogger dictionaries store time-gap limits in
         <ExtraLimitations> as EventType/SearchSpecifier/Limits, not as
         <Tokens>. without_list is always [] for real dictionaries.
      3. UI-2.6: Time-gap filter (_apply_time_gap_filter) IS now applied
         when condition.extra_limitations is non-empty AND turns carry
         start_offset/end_offset timestamps. EventType=Parent limits use
         parent_match_times (parent node's matched turn offsets); when
         parent_match_times is None (root-level node), Parent-type limits
         are skipped.
      4. N18 perf: ``precomputed_word_positions`` / ``precomputed_turn_words``
         let callers reuse a single per-turn tokenize across all conditions
         of the same node (the canonical case from ``_search_recursive``).

    Args:
        condition: The phrase condition to search for.
        turns: Dialogue turns in smartlogger format.
        channel_map: Turn index → speaker mapping.
        parent_match_times: Optional list of parent node match timestamps
            (seconds from dialogue start). Used by EventType=Parent limits.
            None for root-level nodes (Parent limits then skipped).
        precomputed_word_positions: optional cache of word (start,end) char
            positions per turn — see ``match_phrase_morphological_detailed``.
        precomputed_turn_words: optional cache of token lists per turn.

    Returns:
        List of (turn_index, speaker, detail_dict) tuples.
    """
    matches = _do_match(
        condition=condition,
        turns=turns,
        channel_map=channel_map,
        precomputed_word_positions=precomputed_word_positions,
        precomputed_turn_words=precomputed_turn_words,
    )

    # Apply time-gap filter from real <ExtraLimitations> (UI-2.6).
    # Filter is a no-op when extra_limitations is empty or when turns
    # lack timestamps.
    if matches and condition.extra_limitations:
        matches = _apply_time_gap_filter(
            matches=matches,
            turns=turns,
            extra_limitations=condition.extra_limitations,
            parent_match_times=parent_match_times,
        )

    # Legacy WITHOUT filter (deprecated — without_list always [] for real
    # dictionaries). Kept for synthetic test fixtures that set without_list
    # manually; preserves prior behaviour for those fixtures.
    if matches and condition.without_list:
        if _check_without(turns, condition.without_list):
            return []

    return matches


def _do_match(
    condition: DictionaryCondition,
    turns: List[dict],
    channel_map: Dict[int, str],
    precomputed_word_positions: Optional[List[List[Tuple[int, int]]]] = None,
    precomputed_turn_words: Optional[List[List[str]]] = None,
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
            precomputed_word_positions=precomputed_word_positions,
            precomputed_turn_words=precomputed_turn_words,
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
    """DEPRECATED: without_list always [] for real dictionaries.

    V3 (smartlogger-xml-verification.md): real <ExtraLimitations> stores
    EventType/SearchSpecifier/Settings/Limits — NEVER <Tokens>. Therefore
    condition.without_list is always [] in production, and this function
    is never called from _match_condition.

    Time-gap filtering (OnlyInGaps / ExcludeGaps) against real turn
    timestamps is a TODO — only the ExtraLimitation model + parser exist.

    Kept for legacy test fixtures that synthesise without_list manually.

    Uses morphological BOW matching (same as main search) to avoid
    asymmetry where main search finds morphological variants but
    WITHOUT check misses them [1].
    """
    if not without_list:
        return False
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
# phrase_logic_tree GATE (N15)
# ---------------------------------------------------------------------------


def _eval_logic_node(node, matched_phrase_texts: Set[str]) -> bool:
    """Recursively evaluate a LogicNode against matched phrase texts.

    - PHRASE: True iff its phrase_text is in matched_phrase_texts
    - NOT:    True iff child evaluates False
    - AND:    True iff ALL children evaluate True
    - OR:     True iff ANY child evaluates True
    - ATTRIBUTE / GROUP / leaf without recognised type: True (vacuous)
    """
    nt = node.node_type
    if nt == "PHRASE":
        text = node.payload.get("text", "") if node.payload else ""
        return text in matched_phrase_texts
    if nt == "NOT":
        if not node.children:
            return True
        return not _eval_logic_node(node.children[0], matched_phrase_texts)
    if nt == "AND":
        if not node.children:
            # Empty AND = no conditions = gate open (container semantics)
            return True
        return all(
            _eval_logic_node(c, matched_phrase_texts) for c in node.children
        )
    if nt == "OR":
        if not node.children:
            return False
        return any(
            _eval_logic_node(c, matched_phrase_texts) for c in node.children
        )
    # ATTRIBUTE / GROUP / unknown leaf — treat as vacuously True
    return True


def evaluate_phrase_logic_tree(
    phrase_groups, matched_phrase_texts: Set[str]
) -> bool:
    """Evaluate the AND/OR/NOT phrase_logic_tree as a GATE (N15).

    Builds the logic tree via build_phrase_logic_tree and evaluates it:
      - ALL AND-children must match
      - ANY OR-child must match
      - NOT-child must NOT match

    For an empty phrase_groups list (no conditions / container node),
    returns True — the gate is open (consistent with prior behaviour where
    a node without positive conditions was treated as a passthrough).

    Args:
        phrase_groups: List[PhraseGroup] from the dictionary node.
        matched_phrase_texts: Set of condition.text strings that matched
            the dialogue for this node.

    Returns:
        True iff the phrase_logic_tree evaluates True.
    """
    if not phrase_groups:
        return True
    tree = build_phrase_logic_tree(phrase_groups)
    return _eval_logic_node(tree, matched_phrase_texts)


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

    Includes optional `start_offset` / `end_offset` (seconds from dialogue
    start) when the RTF parser was able to extract timing. Time-gap
    filtering (UI-2.6 ExtraLimitations) is skipped when offsets are absent.

    Args:
        dialog: Parsed dialogue.

    Returns:
        List of {"speaker": str, "text": str,
                  "start_offset": Optional[float], "end_offset": Optional[float]} dicts.
    """
    return [
        {
            "speaker": turn.speaker,
            "text": turn.text,
            "start_offset": turn.start_offset,
            "end_offset": turn.end_offset,
        }
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

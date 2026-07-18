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
from typing import Callable, Dict, List, Optional, Set, Tuple

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


def _channel_turns(
    turns: List[dict], channel: str,
) -> List[dict]:
    """Return sub-list of turns belonging to `channel` (or all for ANY)."""
    ch = (channel or "ANY").upper()
    if ch == "ANY":
        return list(turns)
    speaker = _SPEAKER_BY_CHANNEL.get(ch, "")
    return [t for t in turns if t.get("speaker") == speaker]


def _build_seconds_window(
    turns: List[dict], limit: ExtraLimitationLimit,
) -> Optional[Tuple[float, float]]:
    """Compute (win_start, win_end) for ValueType=Seconds.

    Channel=ANY:  window anchored to dialogue bounds (First/Last).
    Channel=CLIENT/OPERATOR: window anchored to first/last channel turn.
    """
    ch_turns = _channel_turns(turns, limit.channel or "ANY")
    if not ch_turns:
        return None

    n_seconds = float(limit.value)
    if limit.limit_type == "First":
        ref_start = ch_turns[0].get("start_offset")
        if ref_start is None:
            return None
        return (float(ref_start), float(ref_start) + n_seconds)
    if limit.limit_type == "Last":
        ref_end = ch_turns[-1].get("end_offset")
        if ref_end is None:
            return None
        return (float(ref_end) - n_seconds, float(ref_end))
    return None


def _build_words_window(
    turns: List[dict], limit: ExtraLimitationLimit,
) -> Optional[Tuple[float, float]]:
    """Compute (win_start, win_end) for ValueType=Words.

    Words are counted only within `limit.channel` (ANY = all speakers).
      - First: window from first channel turn start to end of the N-th word.
      - Last:  window from start of the (total-N+1)-th word to last channel
               turn end.
    """
    ch_turns = _channel_turns(turns, limit.channel or "ANY")
    if not ch_turns:
        return None

    n = int(limit.value)
    if n <= 0:
        return None

    if limit.limit_type == "First":
        first_start: Optional[float] = None
        word_count = 0
        nth_word_end: Optional[float] = None
        for t in ch_turns:
            s = t.get("start_offset")
            e = t.get("end_offset")
            text = t.get("text") or ""
            words_in_turn = len(text.split())
            if words_in_turn == 0:
                continue
            if first_start is None and s is not None:
                first_start = float(s)
            if word_count + words_in_turn >= n:
                nth_word_end = float(e) if e is not None else None
                break
            word_count += words_in_turn
        # If total words < N, the window extends to the end of the last
        # channel word (i.e. all words fall inside the "first N" window).
        if nth_word_end is None:
            for t in reversed(ch_turns):
                e = t.get("end_offset")
                text = t.get("text") or ""
                if text.split() and e is not None:
                    nth_word_end = float(e)
                    break
        if first_start is None or nth_word_end is None:
            return None
        return (first_start, nth_word_end)

    if limit.limit_type == "Last":
        last_end: Optional[float] = None
        word_count = 0
        nth_word_start: Optional[float] = None
        for t in reversed(ch_turns):
            s = t.get("start_offset")
            e = t.get("end_offset")
            text = t.get("text") or ""
            words_in_turn = len(text.split())
            if words_in_turn == 0:
                continue
            if last_end is None and e is not None:
                last_end = float(e)
            if word_count + words_in_turn >= n:
                nth_word_start = float(s) if s is not None else None
                break
            word_count += words_in_turn
        # If total words < N, the window starts at the first channel word.
        if nth_word_start is None:
            for t in ch_turns:
                s = t.get("start_offset")
                text = t.get("text") or ""
                if text.split() and s is not None:
                    nth_word_start = float(s)
                    break
        if last_end is None or nth_word_start is None:
            return None
        return (nth_word_start, last_end)

    return None


def _build_phrases_predicate(
    turns: List[dict], limit: ExtraLimitationLimit,
) -> Optional[Callable[[int], bool]]:
    """Compute in-window predicate for ValueType=Phrases (turn-index based).

    Phrases = turns (channel-scoped when Channel != ANY).
      - First: first N channel turns (indices in `turns` list).
      - Last:  last N channel turns.
    """
    ch = (limit.channel or "ANY").upper()
    if ch == "ANY":
        relevant_indices = list(range(len(turns)))
    else:
        speaker = _SPEAKER_BY_CHANNEL.get(ch, "")
        relevant_indices = [
            i for i, t in enumerate(turns) if t.get("speaker") == speaker
        ]

    n = int(limit.value)
    if n <= 0:
        return None

    if limit.limit_type == "First":
        window_indices = set(relevant_indices[:n])
    elif limit.limit_type == "Last":
        window_indices = set(relevant_indices[-n:])
    else:
        return None

    def predicate(turn_idx: int) -> bool:
        return turn_idx in window_indices

    return predicate


def _build_time_predicate(
    turns: List[dict], limit: ExtraLimitationLimit,
) -> Optional[Callable[[int], bool]]:
    """Build predicate that returns True if a match's turn is in the window.

    Used for ValueType=Seconds | Words (time-window based).
    """
    if limit.value_type == "Seconds":
        window = _build_seconds_window(turns, limit)
    elif limit.value_type == "Words":
        window = _build_words_window(turns, limit)
    else:
        return None

    if window is None:
        return None
    win_start, win_end = window

    def predicate(turn_idx: int) -> bool:
        if not (0 <= turn_idx < len(turns)):
            return False
        s = turns[turn_idx].get("start_offset")
        e = turns[turn_idx].get("end_offset")
        if s is None or e is None:
            return False
        # Intersection of [s, e] and [win_start, win_end].
        return float(s) <= win_end and float(e) >= win_start

    return predicate


def _filter_start_end(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    el: ExtraLimitation,
    limit: ExtraLimitationLimit,
) -> List[Tuple[int, str, dict]]:
    """EventType=StartEnd: filter matches by dialogue-bounded window.

    SearchSpecifier semantics (ground truth from SmartLogger dictionaries):
      - OnlyInGaps:  INCLUDE mode — keep only matches inside the window.
      - ExcludeGaps: EXCLUDE mode — drop matches inside the window.

    The window is derived from Limit:
      - LimitType=First | Last: anchor at start / end of dialogue or channel.
      - ValueType=Seconds: time window [anchor, anchor±value].
      - ValueType=Words:   time window from first channel turn start to the
                            end of the N-th channel word (First) or from the
                            start of the (total-N+1)-th channel word to the
                            last channel turn end (Last).
      - ValueType=Phrases:  set of turn indices — first/last N channel turns.
      - Channel=ANY|CLIENT|OPERATOR: scope turn/word/phrase counting to a
        specific speaker (ANY = all speakers combined).
    """
    if not turns:
        return matches
    if el.search_specifier not in ("OnlyInGaps", "ExcludeGaps"):
        # Unknown SearchSpecifier — defensive no-op.
        return matches

    if limit.value_type == "Phrases":
        predicate = _build_phrases_predicate(turns, limit)
    else:
        predicate = _build_time_predicate(turns, limit)

    if predicate is None:
        return matches

    if el.search_specifier == "OnlyInGaps":
        return [m for m in matches if predicate(m[0])]
    # ExcludeGaps
    return [m for m in matches if not predicate(m[0])]


def _filter_parent(
    matches: List[Tuple[int, str, dict]],
    turns: List[dict],
    el: ExtraLimitation,
    limit: ExtraLimitationLimit,
    parent_match_times: Optional[List[float]],
) -> List[Tuple[int, str, dict]]:
    """EventType=Parent: filter matches by window relative to parent matches.

    SearchSpecifier semantics (ground truth from SmartLogger dictionaries):
      - OnlyInGaps:  INCLUDE mode — keep only matches inside any parent window.
      - ExcludeGaps: EXCLUDE mode — drop matches inside any parent window.

    Window per parent match (parent_t = parent match start_offset):
      - SearchDirection=Before: [parent_t - value, parent_t]
      - SearchDirection=After:  [parent_t, parent_t + value]

    EventSelector selects which parent matches anchor the windows:
      - First: only the first parent match.
      - Last:  only the last parent match.
      - Each:  every parent match (union of windows).

    If parent_match_times is None or empty, Parent filtering cannot be
    evaluated → no-op (per UI-2.6 contract: never silently drop all matches
    when parent context is unavailable).
    """
    if not parent_match_times:
        return matches
    if el.search_specifier not in ("OnlyInGaps", "ExcludeGaps"):
        return matches
    if limit.value_type != "Seconds":
        return matches

    n_seconds = float(limit.value)
    direction = limit.search_direction
    if direction not in ("Before", "After"):
        # Unknown direction — defensive no-op.
        return matches

    selector = (limit.event_selector or "Each").lower() if limit.event_selector else "each"
    if selector == "first":
        selected_parents: List[float] = [parent_match_times[0]]
    elif selector == "last":
        selected_parents = [parent_match_times[-1]]
    else:  # each
        selected_parents = list(parent_match_times)

    windows: List[Tuple[float, float]] = []
    for pt in selected_parents:
        if direction == "Before":
            windows.append((float(pt) - n_seconds, float(pt)))
        else:  # After
            windows.append((float(pt), float(pt) + n_seconds))

    def in_window(turn_idx: int) -> bool:
        if not (0 <= turn_idx < len(turns)):
            return False
        s = turns[turn_idx].get("start_offset")
        e = turns[turn_idx].get("end_offset")
        if s is None or e is None:
            return False
        s_f = float(s)
        e_f = float(e)
        for w_start, w_end in windows:
            if s_f <= w_end and e_f >= w_start:
                return True
        return False

    if el.search_specifier == "OnlyInGaps":
        return [m for m in matches if in_window(m[0])]
    # ExcludeGaps
    return [m for m in matches if not in_window(m[0])]


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
        - LimitType=First: window anchored at the start of the dialogue
          (or the start of the channel's first turn when Channel != ANY).
        - LimitType=Last:  window anchored at the end of the dialogue
          (or the end of the channel's last turn when Channel != ANY).
        - ValueType=Seconds: time window [anchor, anchor ± N] seconds.
        - ValueType=Words:   time window from the first channel turn start
                              to the end of the N-th channel word (First) or
                              from the start of the (total-N+1)-th channel
                              word to the last channel turn end (Last).
        - ValueType=Phrases: set of turn indices — first/last N channel turns.
        - Channel=ANY|CLIENT|OPERATOR scopes word/phrase/turn counting to a
          specific speaker (ANY = all speakers combined, in dialogue order).
        - SearchSpecifier=OnlyInGaps:  INCLUDE — keep matches inside window.
        - SearchSpecifier=ExcludeGaps: EXCLUDE — drop matches inside window.

    For EventType=Parent:
        - SearchDirection=Before: window [parent_t - N, parent_t].
        - SearchDirection=After:  window [parent_t, parent_t + N].
        - EventSelector=First | Last | Each: which parent matches anchor
          the windows (only the first, only the last, or every one).
        - SearchSpecifier=OnlyInGaps / ExcludeGaps: same INCLUDE/EXCLUDE
          semantics applied to the union of parent-anchored windows.

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
            # Snapshot matches before this limit is applied so we can log
            # how many were discarded by it (observability for the
            # "0 matches" regression — see pii_masking.py fix).
            matches_before = list(filtered)
            filtered = _filter_by_limit(
                filtered, turns, el, limit, parent_match_times
            )
            if len(filtered) < len(matches_before):
                logger.info(
                    "time_gap_filter discarded %d/%d matches "
                    "(event_type=%s, limit_type=%s, value=%s, specifier=%s)",
                    len(matches_before) - len(filtered),
                    len(matches_before),
                    el.event_type,
                    getattr(limit, "limit_type", None),
                    getattr(limit, "value", None),
                    getattr(el, "search_specifier", None),
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

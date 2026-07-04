"""Morphological matching service for Russian dialogue analysis.

Uses pymorphy3 for Russian lemmatization with special handling for
verb aspectual pairs (совершенный/несовершенный вид).

MATCHING MODES (from SmartLogger XML spec):
  - Without quotes (is_exact=False): morphological BOW matching.
    Words match by lemma (any word form). Order is FREE.
    WordDistance controls intermediate words allowed.
  - With quotes (is_exact=True): exact form BOW matching.
    Words match by EXACT string (no lemmatization). Order is FREE.
    WordDistance controls intermediate words (same rules as without quotes).

CRITICAL: Word order is ALWAYS FREE — both with and without quotes.
Quotes fix ONLY morphology (exact word form), NOT word order.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Module-level compiled regex (NOT inside functions)
# ═══════════════════════════════════════════════════════════════
_WORD_PATTERN = re.compile(r'[а-яёa-z0-9]+')


# ═══════════════════════════════════════════════════════════════
# Authoritative tokenizer
# ═══════════════════════════════════════════════════════════════
def _tokenize(text: str) -> List[str]:
    """Tokenize text using smartlogger tokenizer or fallback regex.

    INV-2: Only smartlogger.tokenizer.tokenize() or identical regex.
    Never .split().
    """
    try:
        from smartlogger.tokenizer import tokenize
        return tokenize(text)
    except ImportError:
        return _WORD_PATTERN.findall(text.lower())


# ═══════════════════════════════════════════════════════════════
# Aspectual verb pair mapping (imperfective ↔ perfective)
# ═══════════════════════════════════════════════════════════════

_ASPECTUAL_PAIRS: Dict[str, str] = {
    "переключить": "переключать",
    "переключаться": "переключить",
    "переключиться": "переключать",
    "перейти": "переходить",
    "уйти": "уходить",
    "сменить": "сменять",
    "поменять": "менять",
    "отказаться": "отказываться",
    "расторгнуть": "расторгать",
    "отключить": "отключать",
    "отключиться": "отключаться",
    "подключить": "подключать",
    "подключиться": "подключаться",
    "переехать": "переезжать",
    "перебраться": "перебираться",
    "отвергнуть": "отвергать",
    "забрать": "забирать",
    "переместить": "перемещать",
    "перенести": "переносить",
    "передать": "передавать",
    "разорвать": "разрывать",
    "закрыть": "закрывать",
    "остановить": "останавливать",
    "прекратить": "прекращать",
    "закончить": "заканчивать",
    "завершить": "завершать",
    "продолжить": "продолжать",
    "изменить": "изменять",
    "заменить": "заменять",
    "отменить": "отменять",
    "перевести": "переводить",
    "перевестись": "переводиться",
    "перевернуть": "переворачивать",
    "приостановить": "приостанавливать",
    "возобновить": "возобновлять",
    "восстановить": "восстанавливать",
    "купить": "покупать",
    "продлить": "продлевать",
    "оформить": "оформлять",
    "подписать": "подписывать",
    "оплатить": "оплачивать",
    "заплатить": "платить",
    "вернуть": "возвращать",
    "вернуться": "возвращаться",
    "перезвонить": "перезванивать",
    "связать": "связывать",
    "связаться": "связываться",
    "решить": "решать",
    "разобраться": "разбираться",
    "разобрать": "разбирать",
    "обсудить": "обсуждать",
    "рассмотреть": "рассматривать",
    "предложить": "предлагать",
    "помочь": "помогать",
}

# Build lemma groups: all lemmas that should be considered equivalent.
# Uses frozenset for deduplication and guarantees both directions.
_LEMMA_GROUPS: Dict[str, str] = {}
_group_id = 0
_pair_seen: Set[frozenset] = set()

for _lemma1, _lemma2 in _ASPECTUAL_PAIRS.items():
    _pair = frozenset({_lemma1, _lemma2})
    if _pair in _pair_seen:
        continue
    _pair_seen.add(_pair)
    _existing = _LEMMA_GROUPS.get(_lemma1) or _LEMMA_GROUPS.get(_lemma2)
    if _existing is None:
        _gk = f"g{_group_id}"
        _group_id += 1
    else:
        _gk = _existing
    _LEMMA_GROUPS[_lemma1] = _gk
    _LEMMA_GROUPS[_lemma2] = _gk

# Cleanup module-level temp vars
del _lemma1, _lemma2, _pair, _existing, _gk, _pair_seen, _group_id


# ═══════════════════════════════════════════════════════════════
# pymorphy3 integration
# ═══════════════════════════════════════════════════════════════
_morph = None


def _get_morph():
    """Lazily initialize pymorphy3 MorphAnalyzer."""
    global _morph
    if _morph is None:
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
            logger.info("pymorphy3 MorphAnalyzer initialized successfully")
        except ImportError:
            logger.warning(
                "pymorphy3 not available — morphological matching disabled"
            )
            _morph = False  # Sentinel: tried and failed
    return _morph if _morph is not False else None


@lru_cache(maxsize=50000)
def get_lemma(word: str) -> str:
    """Get the lemma (normal form) of a Russian word using pymorphy3.

    Falls back to the word itself if pymorphy3 is unavailable.
    """
    morph = _get_morph()
    if morph is None:
        return word
    parsed = morph.parse(word)
    if parsed:
        return parsed[0].normal_form
    return word


@lru_cache(maxsize=50000)
def get_lemma_group(word: str) -> Optional[str]:
    """Get the aspectual pair group ID for a word's lemma."""
    lemma = get_lemma(word)
    return _LEMMA_GROUPS.get(lemma)


def same_lemma(word_a: str, word_b: str) -> bool:
    """Check if two words match by lemma (with aspectual pair support).

    Matching logic:
    1. Exact token match
    2. Same pymorphy3 lemma
    3. Same aspectual pair group
    """
    if word_a == word_b:
        return True

    lemma_a = get_lemma(word_a)
    lemma_b = get_lemma(word_b)

    if lemma_a == lemma_b:
        return True

    group_a = _LEMMA_GROUPS.get(lemma_a)
    group_b = _LEMMA_GROUPS.get(lemma_b)

    if group_a is not None and group_b is not None and group_a == group_b:
        return True

    return False


def same_exact(word_a: str, word_b: str) -> bool:
    """Check if two words match by exact string (case-insensitive).

    Used for quoted phrases where morphology is fixed.
    No lemmatization, no aspectual pairs — only string equality.
    """
    return word_a == word_b


def lemmatize_text(text: str) -> List[str]:
    """Tokenize and lemmatize text for matching."""
    tokens = _tokenize(text)
    return [get_lemma(t) for t in tokens]


# ═══════════════════════════════════════════════════════════════
# Core matching functions
# ═══════════════════════════════════════════════════════════════


def _find_word_positions(text: str) -> List[Tuple[int, int]]:
    """Find (start, end) character positions of each word token in text.

    Uses module-level compiled regex for performance.
    Searches in lowercased text — positions are valid for original text
    because .lower() preserves string length for Cyrillic and ASCII.
    """
    return [(m.start(), m.end()) for m in _WORD_PATTERN.finditer(text.lower())]


def _bag_of_words_match_morph(
    window: List[str],
    phrase_lemmas: List[str],
) -> Optional[List[int]]:
    """Check if all phrase lemmas are found in the window (any order).

    Returns list of matched window indices if all phrase words matched,
    or None if not all matched.

    Uses morphological matching: compares lemmas of window words
    against pre-computed phrase lemmas + aspectual pair groups.
    """
    n = len(phrase_lemmas)
    if len(window) < n:
        return None

    used = [False] * len(window)
    matched_indices: List[int] = []

    for p_lemma in phrase_lemmas:
        found = False
        p_group = _LEMMA_GROUPS.get(p_lemma)
        for w_idx in range(len(window)):
            if used[w_idx]:
                continue
            w_lemma = get_lemma(window[w_idx])
            if w_lemma == p_lemma:
                used[w_idx] = True
                matched_indices.append(w_idx)
                found = True
                break
            # Check aspectual pair group
            if p_group is not None:
                w_group = _LEMMA_GROUPS.get(w_lemma)
                if w_group is not None and w_group == p_group:
                    used[w_idx] = True
                    matched_indices.append(w_idx)
                    found = True
                    break
        if not found:
            return None

    return matched_indices


def _bag_of_words_match_exact(
    window: List[str],
    phrase_words: List[str],
) -> Optional[List[int]]:
    """Check if all phrase words are found in window by EXACT string match.

    Any order allowed, but each phrase word must match exactly one window word.
    No morphological matching — only case-insensitive string equality.

    Per SmartLogger spec [4]:
      - Quotes fix ONLY morphology (exact word form)
      - Word order is ALWAYS free
      - WordDistance works as usual
    """
    n = len(phrase_words)
    if len(window) < n:
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


def _compute_match_span(
    window_start: int,
    matched_indices: List[int],
    word_positions: List[Tuple[int, int]],
    turn_text: str,
) -> dict:
    """Compute matched_text and character offsets from matched word indices.

    Uses actual matched word positions (not full window end) to avoid
    including extra unmatched words in the highlighted span.
    """
    if not matched_indices:
        return {"matched_text": "", "matched_start": -1, "matched_end": -1}

    # Convert window-relative indices to absolute indices
    abs_indices = [window_start + idx for idx in matched_indices]

    first_abs = min(abs_indices)
    last_abs = max(abs_indices)

    if first_abs < len(word_positions) and last_abs < len(word_positions):
        span_start = word_positions[first_abs][0]
        span_end = word_positions[last_abs][1]
        matched_text = turn_text[span_start:span_end]
    else:
        span_start = -1
        span_end = -1
        matched_text = ""

    return {
        "matched_text": matched_text,
        "matched_start": span_start,
        "matched_end": span_end,
    }


# ═══════════════════════════════════════════════════════════════
# Public matching API
# ═══════════════════════════════════════════════════════════════


def match_phrase_morphological_detailed(
    phrase_text: str,
    word_distance: int,
    channel_constraint: str,
    turns: List[dict],
    channel_map: Dict[int, str],
    is_exact: bool = False,
    precomputed_word_positions: Optional[List[List[Tuple[int, int]]]] = None,
    precomputed_turn_words: Optional[List[List[str]]] = None,
) -> List[Tuple[int, str, dict]]:
    """Detailed morphological match returning matched text and character offsets.

    Two matching modes per SmartLogger XML spec [4]:
      - is_exact=False: morphological BOW — lemmatization + free word order
      - is_exact=True:  exact form BOW — no lemmatization, but STILL free word order

    CRITICAL: Word order is ALWAYS FREE in both modes.
    Quotes (is_exact) fix ONLY morphology, NOT word order [4].

    Performance (N18): ``_find_word_positions`` and ``_tokenize`` are
    O(len(turn_text)) each. Previously they were called per-turn per-condition
    inside the loop, i.e. for a node with K conditions on N turns the work was
    ~2*K*N tokenizations of identical turn text. Callers in ``search.py``
    invoke this function once per condition, so the per-call cost is already
    N tokenizations — but precomputing once at the top of the call avoids
    recomputing ``word_positions`` and ``turn_words`` for every phrase
    variant of the same condition. Optional ``precomputed_*`` arguments let
    ``search.py`` share a single precompute across all conditions of a node.

    Args:
        phrase_text: text of the phrase to search for.
        word_distance: max allowed extra words between phrase words.
        channel_constraint: "CLIENT" | "OPERATOR" | "ANY".
        turns: list of dialogue turns [{"speaker": ..., "text": ...}, ...].
        channel_map: mapping turn_idx -> speaker ("Клиент"/"Сотрудник").
        is_exact: if True, use exact form matching (no morphology, free order).
        precomputed_word_positions: optional cache of ``_find_word_positions``
            results per turn (same length & order as ``turns``). When supplied,
            this function will NOT recompute positions for any turn.
        precomputed_turn_words: optional cache of ``_tokenize`` results per turn.

    Returns:
        list of (turn_idx, speaker, detail_dict) tuples.
        detail_dict has: matched_text, matched_start, matched_end.
    """
    phrase_words = _tokenize(phrase_text)
    if not phrase_words:
        return []

    # Pre-compute lemmas for morphological mode
    phrase_lemmas = [get_lemma(w) for w in phrase_words] if not is_exact else None

    # Precompute per-turn word positions and token lists ONCE per call.
    # When the caller (search.py) supplies caches that span multiple
    # conditions of the same node, we reuse them directly — the arrays
    # never depend on the phrase, only on the turn text.
    use_cached_positions = (
        precomputed_word_positions is not None
        and len(precomputed_word_positions) == len(turns)
    )
    use_cached_words = (
        precomputed_turn_words is not None
        and len(precomputed_turn_words) == len(turns)
    )

    # Lazily-built local caches only when caller did not provide one.
    local_word_positions: Optional[List[List[Tuple[int, int]]]] = (
        None if use_cached_positions else [None] * len(turns)
    )
    local_turn_words: Optional[List[List[str]]] = (
        None if use_cached_words else [None] * len(turns)
    )

    def _word_positions_for(turn_idx: int, turn_text: str) -> List[Tuple[int, int]]:
        if use_cached_positions:
            return precomputed_word_positions[turn_idx]
        cached = local_word_positions[turn_idx]
        if cached is None:
            cached = _find_word_positions(turn_text)
            local_word_positions[turn_idx] = cached
        return cached

    def _words_for(turn_idx: int, turn_text: str) -> List[str]:
        if use_cached_words:
            return precomputed_turn_words[turn_idx]
        cached = local_turn_words[turn_idx]
        if cached is None:
            cached = _tokenize(turn_text)
            local_turn_words[turn_idx] = cached
        return cached

    matches: List[Tuple[int, str, dict]] = []
    window_size = len(phrase_words) + word_distance

    for turn_idx, turn in enumerate(turns):
        # Check channel constraint
        speaker = channel_map.get(turn_idx, "")
        if channel_constraint == "CLIENT" and speaker != "Клиент":
            continue
        if channel_constraint == "OPERATOR" and speaker != "Сотрудник":
            continue

        turn_text = turn.get("text", "")
        turn_words = _words_for(turn_idx, turn_text)
        if len(turn_words) < len(phrase_words):
            continue

        # Find word positions for character offset mapping (cached)
        word_positions = _word_positions_for(turn_idx, turn_text)

        # Sliding window — bag-of-words match (any order in BOTH modes)
        for i in range(len(turn_words) - len(phrase_words) + 1):
            end_idx = min(i + window_size, len(turn_words))
            window = turn_words[i:end_idx]

            # Choose matching function based on mode
            if is_exact:
                matched_indices = _bag_of_words_match_exact(window, phrase_words)
            else:
                matched_indices = _bag_of_words_match_morph(window, phrase_lemmas)

            if matched_indices is not None:
                # Compute span from actual matched word positions
                span = _compute_match_span(
                    i, matched_indices, word_positions, turn_text
                )
                matches.append((turn_idx, speaker, span))
                break  # One match per turn is enough

    return matches


def match_phrase_morphological(
    phrase_text: str,
    word_distance: int,
    channel_constraint: str,
    turns: List[dict],
    channel_map: Dict[int, str],
    is_exact: bool = False,
    precomputed_word_positions: Optional[List[List[Tuple[int, int]]]] = None,
    precomputed_turn_words: Optional[List[List[str]]] = None,
) -> List[Tuple[int, str]]:
    """Check if a phrase appears in a dialogue.

    Thin wrapper over match_phrase_morphological_detailed() that
    strips the detail dict for callers that only need (turn_idx, speaker).
    """
    result = match_phrase_morphological_detailed(
        phrase_text, word_distance, channel_constraint,
        turns, channel_map, is_exact=is_exact,
        precomputed_word_positions=precomputed_word_positions,
        precomputed_turn_words=precomputed_turn_words,
    )
    return [(turn_idx, speaker) for turn_idx, speaker, _detail in result]

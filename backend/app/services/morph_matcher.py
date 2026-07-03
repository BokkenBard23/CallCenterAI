"""Morphological matching service for Russian dialogue analysis.

Uses pymorphy3 for Russian lemmatization with special handling for
verb aspectual pairs (совершенный/несовершенный вид).

CRITICAL INSIGHT: In real ЦРТ SmartLogger dictionaries, ALL phrases
are QUOTED (exact match required). However, the matching algorithm
must still handle morphological variations because:
  - Dictionary phrase "перейти мтс" must match dialog "переходить на мтс"
  - Dictionary phrase "отказаться" must match dialog "отказываюсь"
  - Dictionary phrase "буду переходить" must match dialog "буду переходить" (exact)

The sliding-window algorithm compares TOKENS from the dialog against
PHRASE WORDS from the dictionary. Without lemmatization, "переходить"
does NOT match "перейти" even though they are the same verb in
different aspects (imperfective vs perfective).

Solution: Compare LEMMAS (normal forms) instead of raw tokens.
For verbs, also check the aspectual pair — "переходить" (imperf) and
"перейти" (perf) share the same semantic meaning and must match.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Aspectual verb pair mapping (imperfective ↔ perfective)
# ═══════════════════════════════════════════════════════════════
# In Russian, most verbs come in aspectual pairs where:
#   - Несовершенный вид (imperfective): ongoing/repeated action
#   - Совершенный вид (perfective): completed action
#
# pymorphy3 returns different lemmas for each aspect:
#   "переходить" → lemma "переходить" (imperf)
#   "перейти"   → lemma "перейти"   (perf)
#
# For dictionary matching these MUST be considered the same word.
# This mapping covers the most common verbs in call-center dialogues.

_ASPECTUAL_PAIRS: Dict[str, str] = {
    # переключить/переключиться ↔ переключать/переключаться
    "переключить": "переключать",
    "переключаться": "переключить",
    "переключиться": "переключать",
    # перейти ↔ переходить
    "перейти": "переходить",
    # уйти ↔ уходить
    "уйти": "уходить",
    # сменить ↔ сменять
    "сменить": "сменять",
    # поменять ↔ менять
    "поменять": "менять",
    # отказаться ↔ отказываться
    "отказаться": "отказываться",
    # расторгнуть ↔ расторгать
    "расторгнуть": "расторгать",
    # отключить ↔ отключать
    "отключить": "отключать",
    "отключиться": "отключаться",
    # подключить ↔ подключать
    "подключить": "подключать",
    "подключиться": "подключаться",
    # переехать ↔ переезжать
    "переехать": "переезжать",
    # перебраться ↔ перебираться
    "перебраться": "перебираться",
    # отвергнуть ↔ отвергать
    "отвергнуть": "отвергать",
    # забрать ↔ забирать
    "забрать": "забирать",
    # переместить ↔ перемещать
    "переместить": "перемещать",
    # перенести ↔ переносить
    "перенести": "переносить",
    # передать ↔ передавать
    "передать": "передавать",
    # разорвать ↔ разрывать
    "разорвать": "разрывать",
    # закрыть ↔ закрывать
    "закрыть": "закрывать",
    # остановить ↔ останавливать
    "остановить": "останавливать",
    # прекратить ↔ прекращать
    "прекратить": "прекращать",
    # закончить ↔ заканчивать
    "закончить": "заканчивать",
    # завершить ↔ завершать
    "завершить": "завершать",
    # продолжить ↔ продолжать
    "продолжить": "продолжать",
    # изменить ↔ изменять
    "изменить": "изменять",
    # заменить ↔ заменять
    "заменить": "заменять",
    # отменить ↔ отменять
    "отменить": "отменять",
    # перевести ↔ переводить
    "перевести": "переводить",
    # перевестись ↔ переводиться
    "перевестись": "переводиться",
    # перевернуть ↔ переворачивать
    "перевернуть": "переворачивать",
    # приостановить ↔ приостанавливать
    "приостановить": "приостанавливать",
    # возобновить ↔ возобновлять
    "возобновить": "возобновлять",
    # восстановить ↔ восстанавливать
    "восстановить": "восстанавливать",
    # купить ↔ покупать
    "купить": "покупать",
    # продлить ↔ продлевать
    "продлить": "продлевать",
    # оформить ↔ оформлять
    "оформить": "оформлять",
    # подписать ↔ подписывать
    "подписать": "подписывать",
    # оплатить ↔ оплачивать
    "оплатить": "оплачивать",
    # заплатить ↔ платить
    "заплатить": "платить",
    # вернуть ↔ возвращать
    "вернуть": "возвращать",
    # вернуться ↔ возвращаться
    "вернуться": "возвращаться",
    # перезвонить ↔ перезванивать
    "перезвонить": "перезванивать",
    # связать ↔ связывать
    "связать": "связывать",
    # связаться ↔ связываться
    "связаться": "связываться",
    # решить ↔ решать
    "решить": "решать",
    # разобраться ↔ разбираться
    "разобраться": "разбираться",
    # разобрать ↔ разбирать
    "разобрать": "разбирать",
    # обсудить ↔ обсуждать
    "обсудить": "обсуждать",
    # рассмотреть ↔ рассматривать
    "рассмотреть": "рассматривать",
    # предложить ↔ предлагать
    "предложить": "предлагать",
    # помочь ↔ помогать
    "помочь": "помогать",
}

# Build "lemma group" — all lemmas that should be considered equivalent
# Each entry in _ASPECTUAL_PAIRS creates a frozenset pair; _pair_seen
# ensures each unique pair is processed exactly once even when the same
# pair relationship is expressed from different entry points
# (e.g. via transitive group membership).
_LEMMA_GROUPS: Dict[str, str] = {}  # lemma → group_id
_group_id = 0
_pair_seen: Set[frozenset] = set()

for lemma1, lemma2 in _ASPECTUAL_PAIRS.items():
    pair = frozenset({lemma1, lemma2})
    if pair in _pair_seen:
        continue
    _pair_seen.add(pair)
    
    # Check if either lemma already belongs to a group
    existing_group = _LEMMA_GROUPS.get(lemma1) or _LEMMA_GROUPS.get(lemma2)
    if existing_group is None:
        group_key = f"g{_group_id}"
        _group_id += 1
    else:
        group_key = existing_group
    
    _LEMMA_GROUPS[lemma1] = group_key
    _LEMMA_GROUPS[lemma2] = group_key


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
            logger.warning("pymorphy3 not available — morphological matching disabled")
            _morph = False  # Sentinel: tried and failed
    return _morph if _morph is not False else None


@lru_cache(maxsize=10000)
def get_lemma(word: str) -> str:
    """Get the lemma (normal form) of a Russian word using pymorphy3.
    
    Falls back to the word itself if pymorphy3 is unavailable.
    
    Args:
        word: Lowercase Russian word.
        
    Returns:
        Lemma (normal form) of the word.
    """
    morph = _get_morph()
    if morph is None:
        return word
    
    parsed = morph.parse(word)
    if parsed:
        return parsed[0].normal_form
    return word


@lru_cache(maxsize=10000)
def get_lemma_group(word: str) -> Optional[str]:
    """Get the aspectual pair group ID for a word's lemma.
    
    Returns None if the word's lemma is not part of any known
    aspectual pair group.
    
    Args:
        word: Lowercase Russian word.
        
    Returns:
        Group ID string, or None.
    """
    lemma = get_lemma(word)
    return _LEMMA_GROUPS.get(lemma)


def same_lemma(word_a: str, word_b: str) -> bool:
    """Check if two words match by lemma (with aspectual pair support).
    
    Matching logic:
    1. Exact token match: "мтс" == "мтс" → True
    2. Same lemma: "переходить" and "перейти" both have different lemmas,
       but they belong to the same aspectual pair group → True
    3. Same pymorphy3 lemma: "перешёл" → lemma "перейти",
       "перейти" → lemma "перейти" → True
    
    Args:
        word_a: First word (lowercase).
        word_b: Second word (lowercase).
        
    Returns:
        True if the words are considered morphologically equivalent.
    """
    # Fast path: exact match
    if word_a == word_b:
        return True
    
    lemma_a = get_lemma(word_a)
    lemma_b = get_lemma(word_b)
    
    # Same lemma
    if lemma_a == lemma_b:
        return True
    
    # Check aspectual pair group
    group_a = _LEMMA_GROUPS.get(lemma_a)
    group_b = _LEMMA_GROUPS.get(lemma_b)
    
    if group_a is not None and group_b is not None and group_a == group_b:
        return True
    
    return False


def lemmatize_text(text: str) -> List[str]:
    """Tokenize and lemmatize text for matching.
    
    Uses smartlogger.tokenizer for tokenization (INV-2),
    then pymorphy3 for lemmatization.
    
    Args:
        text: Input text.
        
    Returns:
        List of lemmas (one per token).
    """
    try:
        from smartlogger.tokenizer import tokenize
    except ImportError:
        import re
        _pattern = re.compile(r'[а-яёa-z0-9]+')
        def tokenize(t: str) -> list[str]:
            return _pattern.findall(t.lower())
    
    tokens = tokenize(text)
    return [get_lemma(t) for t in tokens]


def match_phrase_morphological(
    phrase_text: str,
    word_distance: int,
    channel_constraint: str,
    turns: list[dict],
    channel_map: dict[int, str],
    is_exact: bool = False,
) -> list[tuple[int, str]]:
    """Check if a phrase appears in a dialogue using morphological bag-of-words matching.
    
    KEY DIFFERENCE from old sliding-window: words can appear in ANY ORDER.
    This matches ЦРТ SmartLogger behavior where "не хочу подключавать" matches
    "не подключил хотел" — all phrase words must be found within a window,
    regardless of order.
    
    When is_exact=True, delegates to match_phrase_exact() which requires
    token-by-token EXACT match (no morphological, no word reordering).
    
    Algorithm (bag-of-words in sliding window):
    1. Tokenize phrase_text → phrase_words, pre-lemmatize
    2. For each turn, tokenize → turn_words
    3. Slide a window of size (len(phrase_words) + word_distance) across turn_words
    4. In each window position, check if ALL phrase lemmas are found (any order)
    5. Each phrase word can only match once per window position
    
    Args:
        phrase_text: text of the phrase to search for
        word_distance: max allowed extra words between phrase words
        channel_constraint: "CLIENT" | "OPERATOR" | "ANY"
        turns: list of dialogue turns [{"speaker": ..., "text": ...}, ...]
        channel_map: mapping turn_idx -> speaker ("Клиент"/"Сотрудник")
        is_exact: if True, use exact matching (no morphology, no reordering)
    
    Returns:
        list of (turn_idx, speaker) tuples for matches
    """
    result = match_phrase_morphological_detailed(
        phrase_text, word_distance, channel_constraint, turns, channel_map, is_exact=is_exact
    )
    return [(turn_idx, speaker) for turn_idx, speaker, _detail in result]


def match_phrase_morphological_detailed(
    phrase_text: str,
    word_distance: int,
    channel_constraint: str,
    turns: list[dict],
    channel_map: dict[int, str],
    is_exact: bool = False,
) -> list[tuple[int, str, dict]]:
    """Detailed morphological match returning matched text and character offsets.
    
    Same algorithm as match_phrase_morphological, but returns additional info:
      - matched_text: the actual text span from the dialog that was matched
      - matched_start: character offset of match start in the turn's text
      - matched_end: character offset of match end in the turn's text
    
    When is_exact=True, delegates to match_phrase_exact() which requires
    contiguous sequence of exact string matches (no lemma, no reordering).
    
    Args:
        phrase_text: text of the phrase to search for
        word_distance: max allowed extra words between phrase words
        channel_constraint: "CLIENT" | "OPERATOR" | "ANY"
        turns: list of dialogue turns [{"speaker": ..., "text": ...}, ...]
        channel_map: mapping turn_idx -> speaker ("Клиент"/"Сотрудник")
        is_exact: if True, use exact matching (no morphology, no reordering)
    
    Returns:
        list of (turn_idx, speaker, detail_dict) where detail_dict has:
          matched_text, matched_start, matched_end
    """
    if is_exact:
        return match_phrase_exact(phrase_text, word_distance, channel_constraint, turns, channel_map)
    
    try:
        from smartlogger.tokenizer import tokenize
    except ImportError:
        import re
        _pattern = re.compile(r'[а-яёa-z0-9]+')
        def tokenize(t: str) -> list[str]:
            return _pattern.findall(t.lower())
    
    phrase_words = tokenize(phrase_text)
    if not phrase_words:
        return []
    
    # Pre-lemmatize phrase words
    phrase_lemmas = [get_lemma(w) for w in phrase_words]
    
    matches: list[tuple[int, str, dict]] = []
    window_size = len(phrase_words) + word_distance
    
    for turn_idx, turn in enumerate(turns):
        # Check channel constraint
        speaker = channel_map.get(turn_idx, "")
        if channel_constraint == "CLIENT" and speaker != "Клиент":
            continue
        if channel_constraint == "OPERATOR" and speaker != "Сотрудник":
            continue
        
        turn_text = turn.get("text", "")
        turn_words = tokenize(turn_text)
        if len(turn_words) < len(phrase_words):
            continue
        
        # Find word positions (start, end) in the original text for offset mapping
        word_positions = _find_word_positions(turn_text)
        
        # Sliding window — bag-of-words match (any order)
        for i in range(len(turn_words) - len(phrase_words) + 1):
            end_idx = min(i + window_size, len(turn_words))
            window = turn_words[i:end_idx]
            
            # Check if ALL phrase lemmas are found in this window (any order)
            if _bag_of_words_match(window, phrase_words, phrase_lemmas):
                # Found a match! Compute character offsets.
                span_start = word_positions[i][0]
                span_end = word_positions[end_idx - 1][1]
                
                matched_text = turn_text[span_start:span_end]
                
                matches.append((turn_idx, speaker, {
                    "matched_text": matched_text,
                    "matched_start": span_start,
                    "matched_end": span_end,
                }))
                break  # One match per turn is enough
    
    return matches


def _find_word_positions(text: str) -> list[tuple[int, int]]:
    """Find (start, end) character positions of each word token in text.
    
    Uses the same regex as smartlogger.tokenizer to ensure consistency.
    
    Args:
        text: The text to scan.
    
    Returns:
        List of (start_char, end_char) for each token found.
    """
    import re
    pattern = re.compile(r'[а-яёa-z0-9]+')
    return [(m.start(), m.end()) for m in pattern.finditer(text.lower())]


def _bag_of_words_match(
    window: list[str],
    phrase_words: list[str],
    phrase_lemmas: list[str],
) -> bool:
    """Check if all phrase lemmas are found in the window (any order, one-to-one).
    
    This implements the ЦРТ SmartLogger matching logic:
    - Words can appear in ANY order within the window
    - Each phrase word must match exactly one window word (no double-use)
    - Morphological matching via same_lemma()
    
    Example:
      phrase_words = ["не", "хочу", "подключавать"]
      window = ["не", "подключил", "хотел"]
      → True  (не=не, подключил→подключить≈подключать, хотел→хотеть≈хотеть)
    
    Args:
        window: List of words from the dialog window.
        phrase_words: List of words from the dictionary phrase (original tokens).
        phrase_lemmas: List of lemmas for phrase_words (same length).
    
    Returns:
        True if all phrase words are matched in the window.
    """
    n = len(phrase_lemmas)
    if len(window) < n:
        return False
    
    # Track which window positions have been matched
    used = [False] * len(window)
    
    for p_idx in range(n):
        found = False
        for w_idx in range(len(window)):
            if used[w_idx]:
                continue
            if same_lemma(window[w_idx], phrase_words[p_idx]):
                used[w_idx] = True
                found = True
                break
        if not found:
            return False
    
    return True


def match_phrase_exact(
    phrase_text: str,
    word_distance: int,
    channel_constraint: str,
    turns: list[dict],
    channel_map: dict[int, str],
) -> list[tuple[int, str, dict]]:
    """Exact match: phrase words must appear as contiguous sequence, no morphological variation.

    Used when is_exact=True (phrase was inside TERMINAL quotes in the XML).
    The matching is strict:
      - Words must appear in the SAME ORDER as in the phrase
      - Each word must match EXACTLY (lowercase comparison, no lemmatization)
      - No word reordering is allowed
      - word_distance still allows extra words BETWEEN the phrase words

    Algorithm:
    1. Tokenize phrase_text -> phrase_words (lowercase)
    2. For each turn, tokenize -> turn_words (lowercase)
    3. Slide a window of size (len(phrase_words) + word_distance) across turn_words
    4. In each window, check if phrase_words appear as a subsequence in order
    5. Each phrase word must EXACTLY match a turn word (case-insensitive string equality)

    Args:
        phrase_text: text of the phrase to search for
        word_distance: max allowed extra words between phrase words
        channel_constraint: "CLIENT" | "OPERATOR" | "ANY"
        turns: list of dialogue turns [{"speaker": ..., "text": ...}, ...]
        channel_map: mapping turn_idx -> speaker ("Клиент"/"Сотрудник")

    Returns:
        list of (turn_idx, speaker, detail_dict) where detail_dict has:
          matched_text, matched_start, matched_end
    """
    try:
        from smartlogger.tokenizer import tokenize
    except ImportError:
        import re
        _pattern = re.compile(r'[а-яёa-z0-9]+')
        def tokenize(t: str) -> list[str]:
            return _pattern.findall(t.lower())

    phrase_words = tokenize(phrase_text)
    if not phrase_words:
        return []

    matches: list[tuple[int, str, dict]] = []
    window_size = len(phrase_words) + word_distance

    for turn_idx, turn in enumerate(turns):
        # Check channel constraint
        speaker = channel_map.get(turn_idx, "")
        if channel_constraint == "CLIENT" and speaker != "Клиент":
            continue
        if channel_constraint == "OPERATOR" and speaker != "Сотрудник":
            continue

        turn_text = turn.get("text", "")
        turn_words = tokenize(turn_text)
        if len(turn_words) < len(phrase_words):
            continue

        # Find word positions for offset mapping
        word_positions = _find_word_positions(turn_text)

        # Sliding window — ordered subsequence match
        for i in range(len(turn_words) - len(phrase_words) + 1):
            end_idx = min(i + window_size, len(turn_words))

            # Check if phrase_words appear as ordered subsequence within window
            match_result = _exact_subsequence_match(
                turn_words[i:end_idx], phrase_words
            )
            if match_result is not None:
                # match_result is the index of last matched word in the window
                last_matched = i + match_result
                span_start = word_positions[i][0]
                span_end = word_positions[last_matched][1]

                matched_text = turn_text[span_start:span_end]

                matches.append((turn_idx, speaker, {
                    "matched_text": matched_text,
                    "matched_start": span_start,
                    "matched_end": span_end,
                }))
                break  # One match per turn is enough

    return matches


def _exact_subsequence_match(
    window: list[str],
    phrase_words: list[str],
) -> Optional[int]:
    """Check if phrase_words appear as an ordered subsequence in window.

    Each phrase word must match EXACTLY (case-insensitive string equality).
    No morphological matching, no reordering.

    Args:
        window: List of words from the dialog window (lowercase).
        phrase_words: List of words from the phrase (lowercase).

    Returns:
        Index of last matched word in window if match found, None otherwise.
    """
    phrase_idx = 0
    last_window_idx = 0

    for w_idx in range(len(window)):
        if phrase_idx >= len(phrase_words):
            break
        if window[w_idx] == phrase_words[phrase_idx]:
            last_window_idx = w_idx
            phrase_idx += 1

    if phrase_idx == len(phrase_words):
        return last_window_idx
    return None

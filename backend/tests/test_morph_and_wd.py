"""Unit tests for morphological matching and WordDistance semantics.

Covers:
  - same_lemma: exact match, pymorphy3 lemma match, aspectual pair group match
  - match_phrase_morphological: sliding window with lemma comparison
  - WordDistance=0: strict contiguous match (no extra words allowed)
  - WordDistance=1: 1 extra word allowed between phrase words
  - WordDistance=2: 2 extra words allowed between phrase words
  - Channel constraint filtering
"""
import sys
import os
import pytest

# Ensure smartlogger is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))
# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.morph_matcher import (
    same_lemma,
    get_lemma,
    match_phrase_morphological,
    match_phrase_morphological_detailed,
)


# ═══════════════════════════════════════════════════════════
# same_lemma tests
# ═══════════════════════════════════════════════════════════

class TestSameLemma:
    """Tests for the same_lemma() morphological comparison function."""

    def test_exact_match(self):
        """Identical words must match."""
        assert same_lemma("мтс", "мтс") is True

    def test_case_sensitivity(self):
        """same_lemma expects lowercase input; same lowercase must match."""
        assert same_lemma("перейти", "перейти") is True

    def test_pymorphy3_lemma_match(self):
        """Words with same pymorphy3 lemma must match.

        'перешёл' → lemma 'перейти', so 'перешёл' matches 'перейти'.
        """
        assert same_lemma("перешёл", "перейти") is True

    def test_pymorphy3_lemma_match_reflexive(self):
        """'отказываюсь' → lemma 'отказываться', matches 'отказываться'."""
        assert same_lemma("отказываюсь", "отказываться") is True

    def test_aspectual_pair_group(self):
        """Words from different aspectual pairs but same group must match.

        'переходить' (imperf) and 'перейти' (perf) have different lemmas
        but belong to the same aspectual pair group in _ASPECTUAL_PAIRS.
        """
        assert same_lemma("переходить", "перейти") is True

    def test_aspectual_pair_group_reverse(self):
        """Aspectual pair matching must be symmetric."""
        assert same_lemma("перейти", "переходить") is True

    def test_no_match_different_words(self):
        """Completely unrelated words must NOT match."""
        assert same_lemma("мтс", "билайн") is False

    def test_no_match_abbreviations(self):
        """'мтс' and 'эмтэс' are NOT the same — different word forms."""
        # pymorphy3 may or may not normalize these; they are NOT in aspectual pairs
        result = same_lemma("мтс", "эмтэс")
        # This should be False — they are different words
        assert result is False

    def test_verb_conjugation_matches_lemma(self):
        """'перейду' → lemma 'перейти', must match 'перейти'."""
        assert same_lemma("перейду", "перейти") is True

    def test_verb_conjugation_matches_aspectual_pair(self):
        """'перейду' → lemma 'перейти', which is in aspectual pair with 'переходить'."""
        assert same_lemma("перейду", "переходить") is True

    def test_noun_no_false_positive(self):
        """Nouns with different lemmas must not match."""
        assert same_lemma("оператор", "провайдер") is False

    def test_reflexive_verb_pair(self):
        """'отказаться' (perf) matches 'отказываться' (imperf) via aspectual pair."""
        assert same_lemma("отказаться", "отказываться") is True

    def test_switch_pair(self):
        """'переключиться' (perf) matches 'переключаться' (imperf)."""
        assert same_lemma("переключиться", "переключаться") is True


# ═══════════════════════════════════════════════════════════
# get_lemma tests
# ═══════════════════════════════════════════════════════════

class TestGetLemma:
    """Tests for the get_lemma() lemmatization function."""

    def test_noun_lemma(self):
        """Noun lemma should be nominative singular."""
        assert get_lemma("оператора") == "оператор"

    def test_verb_lemma_imperfective(self):
        """Imperfective verb lemma."""
        assert get_lemma("переходить") == "переходить"

    def test_verb_lemma_perfective(self):
        """Perfective verb lemma — different from imperfective."""
        assert get_lemma("перейти") == "перейти"

    def test_past_tense_lemma(self):
        """Past tense verb → lemma should be infinitive."""
        assert get_lemma("перешёл") == "перейти"

    def test_unknown_word(self):
        """Unknown word returns itself."""
        result = get_lemma("xyzabc")
        assert result == "xyzabc"


# ═══════════════════════════════════════════════════════════
# match_phrase_morphological tests
# ═══════════════════════════════════════════════════════════

# Sample dialogue turns for testing
SAMPLE_TURNS = [
    {"speaker": "Сотрудник", "text": "Здравствуйте чем могу помочь"},
    {"speaker": "Клиент", "text": "я хочу перейти на мтс"},
    {"speaker": "Сотрудник", "text": "давайте обсудим"},
    {"speaker": "Клиент", "text": "мне невыгодно буду переходить на мтс"},
    {"speaker": "Клиент", "text": "переключусь в мтс"},
    {"speaker": "Клиент", "text": "я перейду возможно на другую связь"},
    {"speaker": "Клиент", "text": "отказываюсь от ваших услуг"},
    {"speaker": "Сотрудник", "text": "понял"},
]

SAMPLE_CHANNEL_MAP = {i: t["speaker"] for i, t in enumerate(SAMPLE_TURNS)}


class TestMatchPhraseMorphological:
    """Tests for the match_phrase_morphological() sliding window search."""

    def test_exact_phrase_match(self):
        """Exact phrase 'перейти на мтс' must match turn 1 exactly."""
        matches = match_phrase_morphological(
            phrase_text="перейти на мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=SAMPLE_TURNS,
            channel_map=SAMPLE_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 1 in turn_indices, f"Expected turn 1 match, got {turn_indices}"

    def test_morphological_match_aspectual_pair(self):
        """'перейти на мтс' must also match 'переходить на мтс' (aspectual pair)."""
        matches = match_phrase_morphological(
            phrase_text="перейти на мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=SAMPLE_TURNS,
            channel_map=SAMPLE_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 3 in turn_indices, f"Expected turn 3 match (morphological), got {turn_indices}"

    def test_channel_constraint_client(self):
        """CLIENT constraint must exclude Сотрудник turns."""
        matches = match_phrase_morphological(
            phrase_text="обсудить",
            word_distance=2,
            channel_constraint="CLIENT",
            turns=SAMPLE_TURNS,
            channel_map=SAMPLE_CHANNEL_MAP,
        )
        for idx, speaker in matches:
            assert speaker == "Клиент", f"Expected only Клиент matches, got {speaker} in turn {idx}"

    def test_channel_constraint_operator(self):
        """OPERATOR constraint must exclude Клиент turns."""
        matches = match_phrase_morphological(
            phrase_text="помочь",
            word_distance=2,
            channel_constraint="OPERATOR",
            turns=SAMPLE_TURNS,
            channel_map=SAMPLE_CHANNEL_MAP,
        )
        for idx, speaker in matches:
            assert speaker == "Сотрудник", f"Expected only Сотрудник matches, got {speaker}"

    def test_channel_any(self):
        """ANY constraint must match both speakers."""
        matches = match_phrase_morphological(
            phrase_text="мтс",
            word_distance=0,
            channel_constraint="ANY",
            turns=SAMPLE_TURNS,
            channel_map=SAMPLE_CHANNEL_MAP,
        )
        # 'мтс' appears in turns 1, 3, 4 (Клиент) and nowhere in Сотрудник
        assert len(matches) >= 1, "Expected at least 1 match for 'мтс' with ANY channel"


# ═══════════════════════════════════════════════════════════
# WordDistance semantics tests
# ═══════════════════════════════════════════════════════════

class TestWordDistanceSemantics:
    """Tests for WordDistance parameter behavior.

    WordDistance=N means: up to N extra words are allowed between
    the phrase words in the dialogue text.

    WD=0: strict contiguous — phrase words must appear consecutively
    WD=1: 1 extra word allowed between phrase words
    WD=2: 2 extra words allowed between phrase words
    """

    # Custom turns for precise WD testing
    # WD counts extra words BETWEEN phrase words, NOT before the phrase.
    # Phrase: "перейду на другую связь" (4 words)
    WD_TURNS = [
        {"speaker": "Клиент", "text": "перейду на другую связь"},             # 0: exact contiguous (0 between)
        {"speaker": "Клиент", "text": "я перейду на другую связь"},           # 1: "я" before phrase, 0 between → WD=0 match
        {"speaker": "Клиент", "text": "я перейду завтра на другую связь"},    # 2: "я" before, 1 between ("завтра") → WD=1 match
        {"speaker": "Клиент", "text": "я перейду вот прямо сейчас на другую связь"},  # 3: "я" before, 3 between → needs WD≥3
        {"speaker": "Клиент", "text": "перейду связь"},                      # 4: missing "на другую"
    ]
    WD_CHANNEL_MAP = {i: "Клиент" for i in range(len(WD_TURNS))}

    def test_wd0_exact_contiguous(self):
        """WD=0: 'перейду на другую связь' must match only turn 0 (exact contiguous)."""
        matches = match_phrase_morphological(
            phrase_text="перейду на другую связь",
            word_distance=0,
            channel_constraint="CLIENT",
            turns=self.WD_TURNS,
            channel_map=self.WD_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 0 in turn_indices, f"WD=0 should match exact turn 0, got {turn_indices}"

    def test_wd0_no_extra_words(self):
        """WD=0: phrase words must be contiguous WITHIN the window.
        
        Turn 1 'я перейду на другую связь' has 'я' BEFORE the phrase
        start — the phrase words 'перейду на другую связь' are still
        contiguous. WD=0 restricts extra words BETWEEN phrase words,
        not before the phrase. So this IS a valid WD=0 match.
        
        Turn 2 'я перейду завтра на другую связь' has 'завтра' BETWEEN
        phrase words — this should NOT match with WD=0.
        """
        matches = match_phrase_morphological(
            phrase_text="перейду на другую связь",
            word_distance=0,
            channel_constraint="CLIENT",
            turns=self.WD_TURNS,
            channel_map=self.WD_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        # Turn 1 has 'я' before the phrase — phrase words are contiguous → matches
        assert 0 in turn_indices, f"WD=0 should match turn 0, got {turn_indices}"
        assert 1 in turn_indices, f"WD=0 should match turn 1 (extra word before phrase), got {turn_indices}"
        # Turn 2 has 'завтра' between phrase words → should NOT match
        assert 2 not in turn_indices, f"WD=0 should NOT match turn 2 (word between phrase words), got {turn_indices}"

    def test_wd1_one_extra_word(self):
        """WD=1: must match turn 0 (exact) AND turn 1 (1 extra word 'я')."""
        matches = match_phrase_morphological(
            phrase_text="перейду на другую связь",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.WD_TURNS,
            channel_map=self.WD_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 0 in turn_indices, f"WD=1 should match turn 0, got {turn_indices}"
        assert 1 in turn_indices, f"WD=1 should match turn 1 (1 extra word), got {turn_indices}"

    def test_wd2_two_extra_words(self):
        """WD=2: must match turns 0, 1, 2 (up to 2 extra words)."""
        matches = match_phrase_morphological(
            phrase_text="перейду на другую связь",
            word_distance=2,
            channel_constraint="CLIENT",
            turns=self.WD_TURNS,
            channel_map=self.WD_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 0 in turn_indices, f"WD=2 should match turn 0, got {turn_indices}"
        assert 1 in turn_indices, f"WD=2 should match turn 1, got {turn_indices}"
        assert 2 in turn_indices, f"WD=2 should match turn 2, got {turn_indices}"

    def test_wd2_not_three_extra(self):
        """WD=2: must NOT match turn 3 (3 extra words between phrase words).
        
        Turn 3: 'я перейду вот прямо сейчас на другую связь'
        Between 'перейду' and 'на' there are 3 words ('вот', 'прямо', 'сейчас').
        WD=2 allows max 2 extra words between → should NOT match.
        """
        matches = match_phrase_morphological(
            phrase_text="перейду на другую связь",
            word_distance=2,
            channel_constraint="CLIENT",
            turns=self.WD_TURNS,
            channel_map=self.WD_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 3 not in turn_indices, f"WD=2 should NOT match turn 3 (3 extra words between), got {turn_indices}"

    def test_wd_missing_words_no_match(self):
        """Any WD: missing essential words must not match.
        Turn 4 'перейду связь' is missing 'на другую' — should not match."""
        matches = match_phrase_morphological(
            phrase_text="перейду на другую связь",
            word_distance=5,
            channel_constraint="CLIENT",
            turns=self.WD_TURNS,
            channel_map=self.WD_CHANNEL_MAP,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 4 not in turn_indices, f"Should NOT match turn 4 (missing words), got {turn_indices}"


# ═══════════════════════════════════════════════════════════
# Integration test: morph + WD together
# ═══════════════════════════════════════════════════════════

class TestMorphAndWordDistance:
    """Tests combining morphological matching with WordDistance."""

    MORPH_WD_TURNS = [
        {"speaker": "Клиент", "text": "буду переходить на мтс"},              # 0: 1 extra between ("на")
        {"speaker": "Клиент", "text": "я буду переходить от вас на мтс"},    # 1: 3 extra between ("от", "вас", "на")
        {"speaker": "Клиент", "text": "перешёл на мтс"},                     # 2: 1 extra between ("на")
    ]
    MORPH_WD_CHANNEL = {i: "Клиент" for i in range(len(MORPH_WD_TURNS))}

    def test_morph_wd1_pereyti_mts(self):
        """'перейти мтс' (WD=1) must match 'буду переходить на мтс' (1 extra word 'на')."""
        matches = match_phrase_morphological(
            phrase_text="перейти мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.MORPH_WD_TURNS,
            channel_map=self.MORPH_WD_CHANNEL,
        )
        turn_indices = [idx for idx, _ in matches]
        # "перейти" matches "переходить" (aspectual pair)
        # "мтс" matches "мтс" (exact)
        # WD=1 allows 1 extra word "на" between them
        assert 0 in turn_indices, f"Expected morph+WD match in turn 0, got {turn_indices}"

    def test_morph_wd2_pereyti_mts(self):
        """'перейти мтс' (WD=2) must match turn 0 (1 extra) and turn 2 (1 extra).
        
        Turn 1 'я буду переходить от вас на мтс' has 3 words between
        'переходить' and 'мтс' ('от', 'вас', 'на'), so WD=2 is NOT enough.
        """
        matches = match_phrase_morphological(
            phrase_text="перейти мтс",
            word_distance=2,
            channel_constraint="CLIENT",
            turns=self.MORPH_WD_TURNS,
            channel_map=self.MORPH_WD_CHANNEL,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 0 in turn_indices, f"Expected match turn 0, got {turn_indices}"
        assert 2 in turn_indices, f"Expected match turn 2, got {turn_indices}"
        # Turn 1 has 3 extra words between → WD=2 is not enough
        assert 1 not in turn_indices, f"WD=2 should NOT match turn 1 (3 extra between), got {turn_indices}"

    def test_morph_past_tense_match(self):
        """'перейти мтс' (WD=1) must match 'перешёл на мтс' (past tense + 1 extra word)."""
        matches = match_phrase_morphological(
            phrase_text="перейти мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.MORPH_WD_TURNS,
            channel_map=self.MORPH_WD_CHANNEL,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 2 in turn_indices, f"Expected past-tense morph match in turn 2, got {turn_indices}"


# ═══════════════════════════════════════════════════════════
# Bag-of-words matching tests (word reordering)
# ═══════════════════════════════════════════════════════════

class TestBagOfWordsMatch:
    """Tests for bag-of-words matching (words in any order).

    ЦРТ SmartLogger behavior: phrase words can appear in ANY ORDER
    within the sliding window. This is critical for Russian where
    word order is flexible:
      Dictionary: "не хочу подключавать" 
      Dialog: "не подключил хотел" → MATCH (same words, different order)
    """

    BOW_TURNS = [
        {"speaker": "Клиент", "text": "я я ничего не подключил хотел бы вернуть средства обратно"},
        {"speaker": "Клиент", "text": "просто лехе уйду на другого оператора"},
        {"speaker": "Клиент", "text": "я не хочу подключать услуги"},
        {"speaker": "Клиент", "text": "не подключил хотел"},
    ]
    BOW_CHANNEL = {i: "Клиент" for i in range(len(BOW_TURNS))}

    def test_word_reorder_match(self):
        """'не хочу подключать' (WD=2) must match 'не подключил хотел' (reordered).
        
        Dictionary phrase: не хочу подключать
        Dialog text: не подключил хотел
        - не = не (exact)
        - хочу → хотел (same lemma via pymorphy3: хотеть)
        - подключать → подключил (same lemma group via aspectual pair подключать/подключить)
        Words are in different order but all present within the window.
        """
        matches = match_phrase_morphological(
            phrase_text="не хочу подключать",
            word_distance=2,
            channel_constraint="CLIENT",
            turns=self.BOW_TURNS,
            channel_map=self.BOW_CHANNEL,
        )
        turn_indices = [idx for idx, _ in matches]
        # Turn 0 contains "не подключил хотел" — reordered match
        assert 0 in turn_indices, f"Expected bag-of-words match in turn 0, got {turn_indices}"
        # Turn 3 also contains the reordered phrase
        assert 3 in turn_indices, f"Expected bag-of-words match in turn 3, got {turn_indices}"

    def test_word_reorder_exact_phrase_also_matches(self):
        """'не хочу подключать' (WD=2) must also match the exact-order turn 2."""
        matches = match_phrase_morphological(
            phrase_text="не хочу подключать",
            word_distance=2,
            channel_constraint="CLIENT",
            turns=self.BOW_TURNS,
            channel_map=self.BOW_CHANNEL,
        )
        turn_indices = [idx for idx, _ in matches]
        # Turn 2 has the phrase in exact order
        assert 2 in turn_indices, f"Expected exact-order match in turn 2, got {turn_indices}"

    def test_morph_match_uydu_operátoru(self):
        """'уйду другому оператору' (WD=1) must match 'уйду на другого оператора'.
        
        Dictionary phrase: уйду другому оператору
        Dialog text: уйду на другого оператора
        - уйду = уйду (exact)
        - другому → другого (same lemma 'другой', different case)
        - оператору → оператора (same lemma 'оператор', different case)
        - 'на' is the extra filler word (WD=1 allows it)
        """
        matches = match_phrase_morphological(
            phrase_text="уйду другому оператору",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.BOW_TURNS,
            channel_map=self.BOW_CHANNEL,
        )
        turn_indices = [idx for idx, _ in matches]
        assert 1 in turn_indices, f"Expected morph match in turn 1, got {turn_indices}"


# ═══════════════════════════════════════════════════════════
# Detailed match tests (matched_text, offsets)
# ═══════════════════════════════════════════════════════════

class TestDetailedMatch:
    """Tests for match_phrase_morphological_detailed returning offsets."""

    def test_detailed_returns_matched_text(self):
        """Detailed match must return matched_text from the dialog."""
        turns = [{"speaker": "Клиент", "text": "просто лехе уйду на другого оператора"}]
        channel_map = {0: "Клиент"}

        matches = match_phrase_morphological_detailed(
            phrase_text="уйду другому оператору",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=turns,
            channel_map=channel_map,
        )
        assert len(matches) == 1
        turn_idx, speaker, detail = matches[0]
        assert turn_idx == 0
        assert "уйду" in detail["matched_text"]
        assert detail["matched_start"] >= 0
        assert detail["matched_end"] > detail["matched_start"]

    def test_detailed_offsets_are_correct(self):
        """Character offsets must correctly locate the matched text."""
        text = "просто лехе уйду на другого оператора"
        turns = [{"speaker": "Клиент", "text": text}]
        channel_map = {0: "Клиент"}

        matches = match_phrase_morphological_detailed(
            phrase_text="уйду другому оператору",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=turns,
            channel_map=channel_map,
        )
        assert len(matches) == 1
        _, _, detail = matches[0]
        # Verify offsets point to correct text
        extracted = text[detail["matched_start"]:detail["matched_end"]]
        assert extracted == detail["matched_text"]
        assert "уйду" in extracted
        assert "оператора" in extracted

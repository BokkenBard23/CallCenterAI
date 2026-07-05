"""Tests for app.services.dict_utils — dictionary analysis utilities."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import DictionaryCondition, DictionaryNode, PhraseGroup, TokenModel, TokenSection
from app.services.dict_utils import (
    DuplicateReport,
    WordFreq,
    dictionary_stats,
    find_duplicates,
    normalize_phrase,
    stratified_sample,
    validate_dictionary,
    word_frequency,
)


# ═══════════════════════════════════════════════════════════════════════
# normalize_phrase
# ═══════════════════════════════════════════════════════════════════════


class TestNormalizePhrase:
    def test_basic(self) -> None:
        assert normalize_phrase("  Hello   World  ") == "hello world"

    def test_strip_double_quotes(self) -> None:
        assert normalize_phrase('"Привет мир"') == "привет мир"

    def test_strip_russian_quotes(self) -> None:
        assert normalize_phrase("«Привет мир»") == "привет мир"

    def test_strip_single_quotes(self) -> None:
        assert normalize_phrase("'abc'") == "abc"

    def test_only_strip_outer_quotes(self) -> None:
        # Inner quotes are preserved
        assert normalize_phrase('a "b" c') == 'a "b" c'

    def test_empty(self) -> None:
        assert normalize_phrase("") == ""

    def test_collapses_whitespace(self) -> None:
        assert normalize_phrase("a\t b\n c") == "a b c"


# ═══════════════════════════════════════════════════════════════════════
# find_duplicates
# ═══════════════════════════════════════════════════════════════════════


def _cond(text: str, is_exact: bool = False, channel: str = "ANY",
          word_distance: int = 2) -> DictionaryCondition:
    return DictionaryCondition(
        text=text,
        word_distance=word_distance,
        word_count=len(text.split()),
        channel_constraint=channel,
        is_exact=is_exact,
    )


class TestFindDuplicates:
    def test_no_duplicates(self) -> None:
        conds = [_cond("a b"), _cond("c d")]
        report = find_duplicates(conds)
        assert report.full == []
        assert report.soft == []

    def test_full_duplicate(self) -> None:
        conds = [_cond("a b"), _cond("a b")]
        report = find_duplicates(conds)
        assert len(report.full) == 1
        assert report.full[0].row_a == 0
        assert report.full[0].row_b == 1
        assert report.full[0].phrase == "a b"

    def test_quoted_vs_unquoted_is_soft_not_full(self) -> None:
        """B16 fix: is_exact distinguishes full from soft duplicates."""
        conds = [
            _cond("привет мир", is_exact=False),
            _cond("привет мир", is_exact=True),
        ]
        report = find_duplicates(conds)
        assert report.full == []
        assert len(report.soft) == 1

    def test_soft_duplicate_different_channel(self) -> None:
        conds = [
            _cond("a b", channel="CLIENT"),
            _cond("a b", channel="OPERATOR"),
        ]
        report = find_duplicates(conds)
        # Same is_exact, different channel → NOT a full duplicate
        assert report.full == []
        assert len(report.soft) == 1

    def test_soft_duplicate_different_word_distance(self) -> None:
        conds = [
            _cond("a b", word_distance=2),
            _cond("a b", word_distance=0),
        ]
        report = find_duplicates(conds)
        assert report.full == []
        assert len(report.soft) == 1

    def test_brackets_in_key_treated_as_separate_phrase(self) -> None:
        """Bracketed phrases are separate conditions, not collapsed."""
        conds = [_cond("( a b )"), _cond("a b")]
        report = find_duplicates(conds)
        # "( a b )" normalised != "a b" → no duplicates
        assert report.full == []

    def test_case_insensitive_full_duplicate(self) -> None:
        conds = [_cond("Hello World"), _cond("hello world")]
        report = find_duplicates(conds)
        assert len(report.full) == 1
        assert report.full[0].phrase == "hello world"

    def test_is_exact_in_full_dup_key(self) -> None:
        """B16: identical phrase with same is_exact → full duplicate."""
        conds = [
            _cond("hello", is_exact=True),
            _cond("hello", is_exact=True),
        ]
        report = find_duplicates(conds)
        assert len(report.full) == 1
        assert report.full[0].is_exact_a is True


# ═══════════════════════════════════════════════════════════════════════
# word_frequency
# ═══════════════════════════════════════════════════════════════════════


class TestWordFrequency:
    def test_basic(self) -> None:
        conds = [_cond("привет мир"), _cond("мир привет"), _cond("да")]
        freq = word_frequency(conds, top_n=10)
        words = {f.word: f.count for f in freq}
        assert words["привет"] == 2
        assert words["мир"] == 2
        assert words["да"] == 1

    def test_default_stop_words_filtered(self) -> None:
        # "и", "не" are stop words by default
        conds = [_cond("привет и мир"), _cond("не уходи")]
        freq = word_frequency(conds, top_n=10)
        words = {f.word: f.count for f in freq}
        assert "и" not in words
        assert "не" not in words
        assert "привет" in words

    def test_custom_stop_words(self) -> None:
        conds = [_cond("привет мир"), _cond("мир пока")]
        freq = word_frequency(conds, custom_stop_words={"мир"})
        words = {f.word: f.count for f in freq}
        assert "мир" not in words
        assert words["привет"] == 1
        assert words["пока"] == 1

    def test_empty_stop_words_disables_filtering(self) -> None:
        conds = [_cond("и мир")]
        freq = word_frequency(conds, custom_stop_words=set())
        words = {f.word: f.count for f in freq}
        assert words["и"] == 1
        assert words["мир"] == 1

    def test_top_n_limit(self) -> None:
        conds = [_cond(f"word{i}") for i in range(10)]
        freq = word_frequency(conds, top_n=3)
        assert len(freq) == 3


# ═══════════════════════════════════════════════════════════════════════
# dictionary_stats
# ═══════════════════════════════════════════════════════════════════════


class TestDictionaryStats:
    def test_basic_stats(self) -> None:
        node = DictionaryNode(
            id="root",
            name="root",
            conditions=[_cond("a b"), _cond("c"), _cond("a b d")],
        )
        stats = dictionary_stats(node)
        assert stats.total_conditions == 3
        assert stats.total_words == 6  # 2 + 1 + 3 (a b d is 3 words)
        assert stats.unique_words == 4  # a, b, c, d
        assert stats.channels_distribution["ANY"] == 3

    def test_with_phrase_groups_and_brackets(self) -> None:
        node = DictionaryNode(
            id="root",
            name="root",
            conditions=[_cond("a b")],
            phrase_groups=[
                PhraseGroup(words=["a", "b"], channel="ANY", word_distance=2,
                            is_exact=False, is_negated=False, operator=""),
            ],
            token_section=TokenSection(tokens=[
                TokenModel(text="(", type="TERMINAL", channel="ANY", word_distance="2"),
                TokenModel(text="a", type="WORD", channel="ANY", word_distance="2"),
                TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
                TokenModel(text="b", type="WORD", channel="ANY", word_distance="2"),
                TokenModel(text=")", type="TERMINAL", channel="ANY", word_distance="2"),
            ]),
        )
        stats = dictionary_stats(node)
        assert stats.brackets_count == 2  # ( and )

    def test_recurses_into_children(self) -> None:
        child = DictionaryNode(
            id="child",
            name="child",
            conditions=[_cond("x y")],
        )
        root = DictionaryNode(
            id="root",
            name="root",
            conditions=[_cond("a b")],
            children=[child],
        )
        stats = dictionary_stats(root)
        assert stats.total_conditions == 2
        assert stats.total_words == 4


# ═══════════════════════════════════════════════════════════════════════
# stratified_sample
# ═══════════════════════════════════════════════════════════════════════


class TestStratifiedSample:
    def test_below_200_returns_all(self) -> None:
        phrases = [f"phrase{i}" for i in range(50)]
        result, was_sampled = stratified_sample(phrases)
        assert len(result) == 50
        assert was_sampled is False

    def test_300_returns_200_sampled(self) -> None:
        phrases = [f"phrase{i}" for i in range(300)]
        result, was_sampled = stratified_sample(phrases)
        assert len(result) == 200
        assert was_sampled is True

    def test_800_returns_250(self) -> None:
        phrases = [f"phrase{i}" for i in range(800)]
        result, was_sampled = stratified_sample(phrases)
        assert len(result) == 250
        assert was_sampled is True

    def test_1500_returns_300(self) -> None:
        phrases = [f"phrase{i}" for i in range(1500)]
        result, was_sampled = stratified_sample(phrases)
        assert len(result) == 300
        assert was_sampled is True

    def test_dedup(self) -> None:
        phrases = ["a", "A", "b", "B", "c"]
        result, was_sampled = stratified_sample(phrases)
        # Case-insensitive dedup → 3 unique
        assert len(result) == 3
        assert was_sampled is False

    def test_hard_cap_override(self) -> None:
        phrases = [f"p{i}" for i in range(500)]
        result, was_sampled = stratified_sample(phrases, hard_cap=10)
        assert len(result) == 10
        assert was_sampled is True


# ═══════════════════════════════════════════════════════════════════════
# validate_dictionary
# ═══════════════════════════════════════════════════════════════════════


class TestValidateDictionary:
    def test_valid_dictionary_no_errors(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[_cond("hello world", word_distance=2)],
        )
        result = validate_dictionary(node)
        assert result.is_valid is True
        assert result.errors == []

    def test_invalid_channel(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[DictionaryCondition(
                text="x", word_distance=2, word_count=1,
                channel_constraint="WEIRD",
            )],
        )
        result = validate_dictionary(node)
        assert not result.is_valid
        assert any("канал" in e.message.lower() for e in result.errors)

    def test_word_distance_negative_error(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[DictionaryCondition(
                text="x", word_distance=-1, word_count=1,
                channel_constraint="ANY",
            )],
        )
        result = validate_dictionary(node)
        assert not result.is_valid
        assert any("worddistance" in e.message.lower() for e in result.errors)

    def test_word_distance_above_3_warning(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[DictionaryCondition(
                text="x", word_distance=10, word_count=1,
                channel_constraint="ANY",
            )],
        )
        result = validate_dictionary(node)
        assert result.is_valid  # only warning
        assert any("worddistance=10" in w.message.lower() for w in result.warnings)

    def test_unbalanced_quotes(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[_cond("hello")],
            token_section=TokenSection(tokens=[
                TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
                TokenModel(text="hello", type="WORD", channel="ANY", word_distance="2"),
            ]),
        )
        result = validate_dictionary(node)
        assert not result.is_valid
        assert any("кавычк" in e.message.lower() for e in result.errors)

    def test_unbalanced_brackets(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[_cond("hello")],
            token_section=TokenSection(tokens=[
                TokenModel(text="(", type="TERMINAL", channel="ANY", word_distance="2"),
                TokenModel(text="hello", type="WORD", channel="ANY", word_distance="2"),
            ]),
        )
        result = validate_dictionary(node)
        assert not result.is_valid
        assert any("скобк" in e.message.lower() for e in result.errors)

    def test_closing_bracket_without_opening(self) -> None:
        node = DictionaryNode(
            id="r",
            name="root",
            conditions=[_cond("hello")],
            token_section=TokenSection(tokens=[
                TokenModel(text="hello", type="WORD", channel="ANY", word_distance="2"),
                TokenModel(text=")", type="TERMINAL", channel="ANY", word_distance="2"),
            ]),
        )
        result = validate_dictionary(node)
        assert not result.is_valid

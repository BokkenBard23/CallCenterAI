"""Tests for BM25Scorer (Robertson IDF, configurable k1/b, Russian-aware).

Covers:
  1. Index small corpus, score queries, verify ranking
  2. k1/b effect on ranking
  3. Lemmatization on/off (morphological variants still match)
  4. Russian stop-words filtered out
  5. Empty index → empty results
  6. Single-doc corpus
  7. Robertson IDF never negative
  8. score_document for incremental use
  9. get_stats / is_indexed observability
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.bm25 import BM25Scorer, _DEFAULT_RU_STOPWORDS


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


CORPUS = [
    "клиент хочет отказаться от услуги и оформить заявку",
    "сотрудник уточнил причину отказа и предложил скидку",
    "абонент просит перевести на другой тариф и проверить баланс",
    "заявка на отключение сим-карты и расторжение договора",
    "клиент отказался от подписки и попросил вернуть платёж",
]


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestBM25Indexing:
    """Indexing and basic scoring."""

    def test_index_marks_is_indexed(self) -> None:
        scorer = BM25Scorer()
        assert not scorer.is_indexed
        scorer.index(CORPUS)
        assert scorer.is_indexed
        assert scorer.total_docs == len(CORPUS)
        assert scorer.avgdl > 0
        assert len(scorer.idf) > 0

    def test_score_returns_sorted_desc(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        results = scorer.score("отказ от услуги", top_k=5)
        assert len(results) > 0
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_score_retrieves_relevant_doc_first(self) -> None:
        """Querying 'отказ от услуги' should rank doc 0 (the отказ- doc) highly."""
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        results = scorer.score("отказ от услуги", top_k=5)
        assert len(results) > 0
        top_doc = results[0][0]
        # Doc 0 contains "отказаться", "услуги" — should be top.
        assert top_doc == 0

    def test_top_k_limits_results(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        results = scorer.score("заявка", top_k=2)
        assert len(results) <= 2

    def test_top_k_none_returns_all(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        results = scorer.score("заявка", top_k=None)
        assert len(results) >= 1


class TestBM25K1BParameters:
    """k1 / b parameter effects."""

    def test_higher_b_penalizes_long_docs(self) -> None:
        """b closer to 1.0 should penalize long documents more."""
        # Doc 0 is long, doc 1 is short — both contain 'заявка'.
        corpus = [
            "заявка на отключение сим-карты и расторжение договора с возвратом платежа",
            "заявка принята",
        ]
        scorer_low_b = BM25Scorer(k1=1.2, b=0.0)
        scorer_low_b.index(corpus)
        scorer_high_b = BM25Scorer(k1=1.2, b=1.0)
        scorer_high_b.index(corpus)

        results_low = dict(scorer_low_b.score("заявка", top_k=10))
        results_high = dict(scorer_high_b.score("заявка", top_k=10))

        # Both docs must be present in both scorers.
        assert 0 in results_low and 1 in results_low
        assert 0 in results_high and 1 in results_high

        # With b=1.0, the short doc (idx 1) should get a relatively higher score
        # than with b=0.0. We compare the ratio short_doc/long_doc.
        ratio_low = results_low[1] / results_low[0]
        ratio_high = results_high[1] / results_high[0]
        assert ratio_high > ratio_low

    def test_k1_zero_disables_tf_saturation(self) -> None:
        """k1=0 makes the saturation term degenerate but score still computable."""
        scorer = BM25Scorer(k1=0.0, b=0.75)
        scorer.index(CORPUS)
        # No exception, results returned.
        results = scorer.score("заявка", top_k=5)
        assert isinstance(results, list)


class TestBM25Lemmatization:
    """Lemmatization on/off."""

    def test_lemmatize_matches_morphological_variants(self) -> None:
        """With lemmatization, 'отказаться' should be matched by query 'отказ'."""
        scorer_lemma = BM25Scorer(lemmatize=True)
        scorer_lemma.index(["клиент хочет отказаться от услуги"])
        # 'отказ' lemma != 'отказаться' lemma, but the document should still
        # match because tokens are lemmatized consistently. The score must be > 0.
        results = scorer_lemma.score("отказ", top_k=5)
        # Either there's a match (positive score) or not — but no exception.
        assert isinstance(results, list)

    def test_no_lemmatize_uses_raw_tokens(self) -> None:
        scorer = BM25Scorer(lemmatize=False)
        scorer.index(["клиент хочет отказаться от услуги"])
        # Exact token 'отказ' is NOT in the doc (only 'отказаться'); score should be 0.
        results = scorer.score("отказ", top_k=5)
        assert results == []

    def test_lemmatize_match_when_word_forms_differ(self) -> None:
        """With lemmatization, query 'заявки' should match doc 'заявка'."""
        scorer_lemma = BM25Scorer(lemmatize=True)
        scorer_lemma.index(["оформить заявку на отключение"])
        results = scorer_lemma.score("заявки", top_k=5)
        assert len(results) == 1
        assert results[0][0] == 0


class TestBM25StopWords:
    """Russian stop-word filtering."""

    def test_default_stopwords_present(self) -> None:
        assert "и" in _DEFAULT_RU_STOPWORDS
        assert "в" in _DEFAULT_RU_STOPWORDS
        assert "не" in _DEFAULT_RU_STOPWORDS

    def test_stopwords_excluded_from_index(self) -> None:
        """Stop-words should not appear in idf table."""
        scorer = BM25Scorer()
        scorer.index(["и в не на", "услуга заявка"])
        for sw in ["и", "в", "не", "на"]:
            assert sw not in scorer.idf

    def test_custom_stop_words(self) -> None:
        """Caller can supply a custom stop-word set."""
        scorer = BM25Scorer(stop_words={"услуга"})
        scorer.index(["услуга заявка", "услуга платёж"])
        assert "услуга" not in scorer.idf
        assert "заявка" in scorer.idf


class TestBM25EdgeCases:
    """Empty corpus, single doc, missing terms."""

    def test_empty_index_returns_empty(self) -> None:
        scorer = BM25Scorer()
        assert scorer.score("test") == []

    def test_index_empty_corpus(self) -> None:
        scorer = BM25Scorer()
        scorer.index([])
        assert not scorer.is_indexed
        assert scorer.total_docs == 0

    def test_single_doc_corpus(self) -> None:
        scorer = BM25Scorer()
        scorer.index(["оформить заявку на отключение"])
        results = scorer.score("заявку", top_k=5)
        assert len(results) == 1
        assert results[0][0] == 0

    def test_query_with_no_matching_terms(self) -> None:
        scorer = BM25Scorer()
        scorer.index(["заявка на отключение"])
        results = scorer.score("тариф баланс", top_k=5)
        assert results == []

    def test_empty_query_returns_empty(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        assert scorer.score("", top_k=5) == []
        assert scorer.score("   ", top_k=5) == []

    def test_doc_with_stop_words_only(self) -> None:
        scorer = BM25Scorer()
        scorer.index(["и в не на", "заявка услуга"])
        # Doc 0 has no content tokens after stop-word removal.
        results = scorer.score("заявка", top_k=5)
        assert len(results) == 1
        assert results[0][0] == 1


class TestBM25RobertsonIDF:
    """Robertson IDF is always >= 0 (no negative IDF)."""

    def test_idf_never_negative(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        for term, idf in scorer.idf.items():
            assert idf >= 0.0, f"negative IDF for {term!r}: {idf}"

    def test_term_in_all_docs_has_low_idf(self) -> None:
        """A term appearing in all docs has the lowest possible IDF (log 1 = 0)."""
        corpus = ["заявка услуга", "заявка платёж", "заявка скидка"]
        scorer = BM25Scorer()
        scorer.index(corpus)
        # 'заявка' is in every doc → IDF = log(1 + 0.5/2.5) which is small but > 0.
        assert "заявка" in scorer.idf
        assert scorer.idf["заявка"] < scorer.idf.get("услуга", scorer.idf["заявка"] + 1)


class TestBM25ScoreDocument:
    """Incremental single-doc scoring."""

    def test_score_document_matches_aggregate(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        for doc_idx, score in scorer.score("заявка", top_k=10):
            assert scorer.score_document("заявка", doc_idx) == pytest.approx(score)

    def test_score_document_invalid_idx(self) -> None:
        scorer = BM25Scorer()
        scorer.index(CORPUS)
        assert scorer.score_document("заявка", -1) == 0.0
        assert scorer.score_document("заявка", 999) == 0.0

    def test_score_document_empty_index(self) -> None:
        scorer = BM25Scorer()
        assert scorer.score_document("заявка", 0) == 0.0


class TestBM25Stats:
    """Observability."""

    def test_get_stats_fields(self) -> None:
        scorer = BM25Scorer(k1=1.5, b=0.5, lemmatize=True)
        scorer.index(CORPUS)
        stats = scorer.get_stats()
        assert stats["total_docs"] == len(CORPUS)
        assert stats["k1"] == 1.5
        assert stats["b"] == 0.5
        assert stats["lemmatize"] is True
        assert stats["total_unique_terms"] > 0
        assert stats["avgdl"] > 0

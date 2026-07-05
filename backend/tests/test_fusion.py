"""Tests for fusion strategies (RRF / Convex / LogOdds).

Covers:
  1. RRF basic correctness, k effect, weights
  2. Convex min-max normalization, weighted combination
  3. LogOdds dynamic sigmoid calibration (handles scale mismatch)
  4. Empty rankings, single ranking
  5. Dispatch via fuse()
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.fusion import (
    convex_fusion,
    fuse,
    log_odds_fusion,
    reciprocal_rank_fusion,
)


# ═══════════════════════════════════════════════════════════
# RRF
# ═══════════════════════════════════════════════════════════


class TestRRF:
    def test_single_ranking_single_doc(self) -> None:
        rrf = reciprocal_rank_fusion([[(0, 0.9)]], k=60)
        assert rrf == [(0, pytest.approx(1.0 / (1 + 60)))]

    def test_two_rankings_same_doc_at_rank_1(self) -> None:
        """Same doc at rank 1 in both rankings → 2 * 1/(1+k)."""
        rankings = [[(0, 0.9)], [(0, 0.8)]]
        rrf = reciprocal_rank_fusion(rankings, k=60)
        assert rrf[0][0] == 0
        assert rrf[0][1] == pytest.approx(2.0 * (1.0 / (1 + 60)))

    def test_higher_rank_lower_contribution(self) -> None:
        rankings = [[(0, 0.9), (1, 0.7)]]  # doc 0 rank 1, doc 1 rank 2
        rrf = reciprocal_rank_fusion(rankings, k=60)
        scores = dict(rrf)
        assert scores[0] > scores[1]
        assert scores[0] == pytest.approx(1.0 / (1 + 60))
        assert scores[1] == pytest.approx(1.0 / (2 + 60))

    def test_custom_k(self) -> None:
        rrf = reciprocal_rank_fusion([[(0, 0.9)]], k=10)
        assert rrf[0][1] == pytest.approx(1.0 / (1 + 10))

    def test_weights(self) -> None:
        """Weighted RRF: ranking 1 weight=2.0, ranking 2 weight=0.5."""
        rankings = [[(0, 0.9)], [(0, 0.8)]]
        rrf = reciprocal_rank_fusion(rankings, k=60, weights=[2.0, 0.5])
        expected = 2.0 * (1.0 / 61) + 0.5 * (1.0 / 61)
        assert rrf[0][1] == pytest.approx(expected)

    def test_zero_weight_skips_ranking(self) -> None:
        rankings = [[(0, 0.9)], [(1, 0.8)]]
        rrf = reciprocal_rank_fusion(rankings, k=60, weights=[1.0, 0.0])
        assert rrf == [(0, pytest.approx(1.0 / 61))]

    def test_empty_rankings(self) -> None:
        assert reciprocal_rank_fusion([], k=60) == []
        assert reciprocal_rank_fusion([[], []], k=60) == []

    def test_mismatched_weights_raises(self) -> None:
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([[(0, 0.9)]], weights=[1.0, 1.0])

    def test_results_sorted_desc(self) -> None:
        rankings = [[(0, 0.9), (1, 0.7), (2, 0.5)]]
        rrf = reciprocal_rank_fusion(rankings, k=60)
        scores = [s for _, s in rrf]
        assert scores == sorted(scores, reverse=True)


# ═══════════════════════════════════════════════════════════
# Convex
# ═══════════════════════════════════════════════════════════


class TestConvex:
    def test_single_ranking_normalized(self) -> None:
        """Single ranking 0..1 → convex score equals (s - min)/(max - min)."""
        ranking = [(0, 0.9), (1, 0.5), (2, 0.1)]
        result = convex_fusion([ranking])
        scores = dict(result)
        assert scores[0] == pytest.approx(1.0)  # max
        assert scores[2] == pytest.approx(0.0)  # min
        assert scores[1] == pytest.approx((0.5 - 0.1) / (0.9 - 0.1))

    def test_two_rankings_weighted_sum(self) -> None:
        """Equal weights (0.5, 0.5): result = 0.5*norm1 + 0.5*norm2."""
        r1 = [(0, 0.9), (1, 0.1)]
        r2 = [(0, 0.8), (1, 0.2)]
        result = convex_fusion([r1, r2])
        scores = dict(result)
        # Both rankings normalize to 1.0 for doc 0, 0.0 for doc 1.
        assert scores[0] == pytest.approx(0.5 * 1.0 + 0.5 * 1.0)
        assert scores[1] == pytest.approx(0.5 * 0.0 + 0.5 * 0.0)

    def test_all_equal_scores(self) -> None:
        """When all scores in a ranking are equal, normalization → 1.0 for each."""
        ranking = [(0, 0.5), (1, 0.5)]
        result = convex_fusion([ranking])
        scores = dict(result)
        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(1.0)

    def test_empty(self) -> None:
        assert convex_fusion([]) == []
        assert convex_fusion([[], []]) == []

    def test_weights_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            convex_fusion([[(0, 0.9)]], weights=[1.0, 1.0])

    def test_results_sorted_desc(self) -> None:
        ranking = [(0, 0.9), (1, 0.5), (2, 0.1)]
        result = convex_fusion([ranking])
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)


# ═══════════════════════════════════════════════════════════
# LogOdds
# ═══════════════════════════════════════════════════════════


class TestLogOdds:
    def test_both_signals_agree_high(self) -> None:
        """When dense + sparse both rank doc 0 highly, doc 0 should win."""
        dense = [(0, 0.95), (1, 0.5)]
        sparse = [(0, 0.9), (1, 0.4)]
        result = log_odds_fusion(dense, sparse)
        assert result[0][0] == 0
        assert result[0][1] > result[1][1]
        # Probabilities are in [0, 1].
        for _, score in result:
            assert 0.0 <= score <= 1.0

    def test_handles_scale_mismatch(self) -> None:
        """LogOdds should handle dense in [0.7..0.95] vs sparse in [0.0..1.0]."""
        dense = [(0, 0.95), (1, 0.7), (2, 0.85)]
        sparse = [(0, 0.9), (1, 0.1), (2, 0.5)]
        result = log_odds_fusion(dense, sparse)
        scores = dict(result)
        # Doc 0 should rank first (both signals strong).
        assert result[0][0] == 0
        # All docs present.
        assert len(result) == 3

    def test_dense_only_signal(self) -> None:
        """Doc present only in dense channel gets a calibrated logit-based score."""
        dense = [(0, 0.9), (1, 0.5)]
        sparse = [(0, 0.8)]
        result = log_odds_fusion(dense, sparse)
        # Both docs present in result (doc 1 dense-only).
        doc_ids = {idx for idx, _ in result}
        assert doc_ids == {0, 1}
        # Doc 0 should rank higher (both signals agree).
        assert result[0][0] == 0

    def test_sparse_only_signal(self) -> None:
        dense = [(0, 0.9)]
        sparse = [(0, 0.8), (1, 0.6)]
        result = log_odds_fusion(dense, sparse)
        doc_ids = {idx for idx, _ in result}
        assert doc_ids == {0, 1}

    def test_empty_inputs(self) -> None:
        assert log_odds_fusion([], []) == []
        assert log_odds_fusion([(0, 0.9)], []) != []
        assert log_odds_fusion([], [(0, 0.9)]) != []

    def test_scores_in_unit_interval(self) -> None:
        dense = [(0, 0.9), (1, 0.5), (2, 0.7)]
        sparse = [(0, 0.8), (1, 0.4), (2, 0.6)]
        result = log_odds_fusion(dense, sparse)
        for _, score in result:
            assert 0.0 <= score <= 1.0

    def test_results_sorted_desc(self) -> None:
        dense = [(0, 0.9), (1, 0.5), (2, 0.7)]
        sparse = [(0, 0.8), (1, 0.4), (2, 0.6)]
        result = log_odds_fusion(dense, sparse)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)

    def test_zero_std_dense(self) -> None:
        """When all dense scores are equal, std=0 → alpha=1.0 (no crash)."""
        dense = [(0, 0.5), (1, 0.5)]
        sparse = [(0, 0.8), (1, 0.4)]
        result = log_odds_fusion(dense, sparse)
        # No exception, sorted desc.
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════
# fuse() dispatcher
# ═══════════════════════════════════════════════════════════


class TestFuseDispatch:
    def test_rrf_default(self) -> None:
        result = fuse([[(0, 0.9)]], strategy="rrf")
        assert result == [(0, pytest.approx(1.0 / 61))]

    def test_convex(self) -> None:
        result = fuse([[(0, 0.9), (1, 0.1)]], strategy="convex")
        scores = dict(result)
        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(0.0)

    def test_log_odds_via_kwargs(self) -> None:
        result = fuse(
            [],
            strategy="log_odds",
            dense_scores=[(0, 0.9)],
            sparse_scores=[(0, 0.8)],
        )
        assert result[0][0] == 0

    def test_log_odds_via_rankings_pair(self) -> None:
        """When log_odds is selected, rankings[0] is dense, rankings[1] is sparse."""
        result = fuse(
            [[(0, 0.9)], [(0, 0.8)]],
            strategy="log_odds",
        )
        assert result[0][0] == 0

    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(ValueError):
            fuse([[(0, 0.9)]], strategy="bogus")

    def test_strategy_case_insensitive(self) -> None:
        result = fuse([[(0, 0.9)]], strategy="RRF")
        assert len(result) == 1

"""Hybrid fusion strategies for combining multiple retrieval signals.

Ported from txtai embeddings/search/hybrid.py. Three strategies:
  - RRF (Reciprocal Rank Fusion) — current default, k=60
  - Convex (weighted linear combination of min-max normalized scores)
  - LogOdds (dynamic sigmoid calibration per-query — best when sparse & dense
    scores have different scales)

LogOdds uses median + std of dense scores to dynamically calibrate per-query:
    beta  = median(dense_scores)
    alpha = 1.0 / std(dense_scores)  if std > 0 else 1.0
    calibrated_dense = sigmoid(alpha * (score - beta))
Then weighted mean of log-odds with confidence scaling.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Type alias: a ranking is a list of (doc_id, score) sorted descending.
Ranking = Sequence[Tuple[int, float]]
FusedResult = List[Tuple[int, float]]

_EPS = 1e-10  # numerical clamp for log-odds


# ═══════════════════════════════════════════════════════════════
# RRF
# ═══════════════════════════════════════════════════════════════


def reciprocal_rank_fusion(
    rankings: Sequence[Ranking],
    k: int = 60,
    weights: Optional[Sequence[float]] = None,
) -> FusedResult:
    """RRF: score = Σ (1 / (k + rank)) per document across rankings.

    Args:
        rankings: List of ranked result lists, each [(doc_idx, score), ...]
            sorted descending. Score is ignored — only rank position matters.
        k: RRF constant (default 60, IR standard).
        weights: Optional per-ranking weight (default all 1.0).

    Returns:
        Fused ranking [(doc_idx, fused_score), ...] sorted descending.
        Empty if all rankings are empty.
    """
    if not rankings:
        return []

    if weights is None:
        weights = [1.0] * len(rankings)
    elif len(weights) != len(rankings):
        raise ValueError(
            f"weights length {len(weights)} != rankings length {len(rankings)}"
        )

    fused: dict[int, float] = {}
    for weight, ranking in zip(weights, rankings):
        if weight <= 0:
            continue
        for rank, (doc_idx, _score) in enumerate(ranking, start=1):
            contribution = weight * (1.0 / (k + rank))
            fused[doc_idx] = fused.get(doc_idx, 0.0) + contribution

    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


# ═══════════════════════════════════════════════════════════════
# Convex (min-max normalized weighted linear combination)
# ═══════════════════════════════════════════════════════════════


def _minmax_normalize(ranking: Ranking) -> dict[int, float]:
    """Min-max normalize scores of a single ranking to [0, 1].

    If all scores are equal or the ranking is empty, returns 1.0 for each
    present doc (no discriminative signal — treat as equally relevant).
    """
    if not ranking:
        return {}
    scores = [s for _, s in ranking]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    if span <= 0:
        return {idx: 1.0 for idx, _ in ranking}
    return {idx: (s - lo) / span for idx, s in ranking}


def convex_fusion(
    rankings: Sequence[Ranking],
    weights: Optional[Sequence[float]] = None,
) -> FusedResult:
    """Convex (weighted linear combination of min-max normalized scores).

    Each ranking's scores are min-max normalized to [0, 1] before the
    weighted sum. This makes scales comparable across heterogeneous
    retrieval channels (cosine vs BM25 vs raw similarity).

    Args:
        rankings: List of ranked result lists.
        weights: Optional per-ranking weight. Default equal weights that
            sum to 1.0 across rankings (so the result stays in [0, 1]).

    Returns:
        Fused ranking sorted descending.
    """
    if not rankings:
        return []

    if weights is None:
        weights = [1.0 / len(rankings)] * len(rankings)
    elif len(weights) != len(rankings):
        raise ValueError(
            f"weights length {len(weights)} != rankings length {len(rankings)}"
        )

    fused: dict[int, float] = {}
    for weight, ranking in zip(weights, rankings):
        if weight <= 0:
            continue
        normalized = _minmax_normalize(ranking)
        for doc_idx, score in normalized.items():
            fused[doc_idx] = fused.get(doc_idx, 0.0) + weight * score

    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


# ═══════════════════════════════════════════════════════════════
# LogOdds (dynamic per-query sigmoid calibration)
# ═══════════════════════════════════════════════════════════════


def _calibrate_dense(raw_scores: List[float]) -> Tuple[float, float]:
    """Compute (median, alpha) for per-query sigmoid calibration.

    Mirrors txtai LogOdds.calibrate: beta = median of positive scores,
    alpha = 1 / std. Falls back to (0.0, 1.0) when no positive scores.
    """
    positive = [s for s in raw_scores if s > 0]
    if not positive:
        return 0.0, 1.0
    arr = sorted(positive)
    median = arr[len(arr) // 2]
    mean = sum(arr) / len(arr)
    variance = sum((x - mean) ** 2 for x in arr) / len(arr)
    std = math.sqrt(variance)
    alpha = 1.0 / std if std > 0 else 1.0
    return median, alpha


def log_odds_fusion(
    dense_scores: Ranking,
    sparse_scores: Ranking,
    dense_weight: float = 0.5,
    sparse_weight: float = 0.5,
) -> FusedResult:
    """LogOdds fusion with dynamic per-query sigmoid calibration.

    Calibrates dense scores via sigmoid(alpha * (score - beta)) where
    beta=median, alpha=1/std. Then computes weighted mean of log-odds
    with confidence scaling (n**alpha scaling per txtai LogOdds.fuse).

    Best when dense (cosine) and sparse (BM25) have different scales.

    Args:
        dense_scores: (doc_idx, similarity 0..1) from FAISS cosine.
        sparse_scores: (doc_idx, BM25 or probability 0..1) from sparse scorer.
            If BM25 scores are unbounded, caller should pre-normalize or pass
            probabilities; raw BM25 will be clamped to [EPS, 1-EPS] as a
            last-resort interpretation.
        dense_weight: Weight for the dense channel.
        sparse_weight: Weight for the sparse channel.

    Returns:
        Fused ranking of (doc_idx, probability-like score in [0, 1]).
    """
    # Collect raw scores per document.
    uids: dict[int, List[Optional[float]]] = {}
    dense_raw: List[float] = []
    for doc_idx, score in dense_scores:
        if doc_idx not in uids:
            uids[doc_idx] = [None, None]
        uids[doc_idx][0] = float(score)
        dense_raw.append(float(score))

    for doc_idx, score in sparse_scores:
        if doc_idx not in uids:
            uids[doc_idx] = [None, None]
        uids[doc_idx][1] = float(score)

    if not uids:
        return []

    beta, alpha = _calibrate_dense(dense_raw)

    # Confidence scaling: n**alpha_pow with n=2 (two channels), alpha_pow=0.5 → sqrt(2).
    n_channels = 2
    alpha_pow = 0.5
    scale = n_channels ** alpha_pow

    w_sum = dense_weight + sparse_weight
    if w_sum <= 0:
        # Degenerate weights — equal fallback.
        dense_weight = sparse_weight = 0.5

    fused: dict[int, float] = {}
    for doc_idx, pair in uids.items():
        raw_dense, p_sparse = pair

        if raw_dense is not None and p_sparse is not None:
            logit_dense = alpha * (raw_dense - beta)
            logit_dense = max(min(logit_dense, 500.0), -500.0)

            p_sparse_clamped = min(max(p_sparse, _EPS), 1.0 - _EPS)
            logit_sparse = math.log(p_sparse_clamped / (1.0 - p_sparse_clamped))

            lbar = dense_weight * logit_dense + sparse_weight * logit_sparse
            fused[doc_idx] = lbar * scale

        elif raw_dense is not None:
            logit_dense = alpha * (raw_dense - beta)
            logit_dense = max(min(logit_dense, 500.0), -500.0)
            fused[doc_idx] = logit_dense * dense_weight

        elif p_sparse is not None:
            p_sparse_clamped = min(max(p_sparse, _EPS), 1.0 - _EPS)
            logit_sparse = math.log(p_sparse_clamped / (1.0 - p_sparse_clamped))
            fused[doc_idx] = logit_sparse * sparse_weight

    # Convert logits → probabilities.
    result: FusedResult = [
        (doc_idx, 1.0 / (1.0 + math.exp(-score)))
        for doc_idx, score in fused.items()
    ]
    result.sort(key=lambda x: x[1], reverse=True)
    return result


# ═══════════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════════


def fuse(
    rankings: Sequence[Ranking],
    strategy: str = "rrf",
    **kwargs: object,
) -> FusedResult:
    """Dispatch to a fusion strategy by name.

    Args:
        rankings: For "rrf"/"convex" — list of rankings to fuse.
                  For "log_odds" — should be a (dense, sparse) pair passed as
                  `dense_scores` / `sparse_scores` keyword arguments.
        strategy: One of "rrf", "convex", "log_odds".
        **kwargs: Strategy-specific options.

    Returns:
        Fused ranking sorted descending.
    """
    strategy = (strategy or "rrf").lower()

    if strategy == "rrf":
        k = int(kwargs.get("k", 60))  # type: ignore[arg-type]
        weights = kwargs.get("weights")  # type: ignore[assignment]
        return reciprocal_rank_fusion(rankings, k=k, weights=weights)  # type: ignore[arg-type]

    if strategy == "convex":
        weights = kwargs.get("weights")  # type: ignore[assignment]
        return convex_fusion(rankings, weights=weights)  # type: ignore[arg-type]

    if strategy in ("log_odds", "logodds"):
        dense = kwargs.get("dense_scores", rankings[0] if rankings else [])  # type: ignore[arg-type]
        sparse = kwargs.get("sparse_scores", rankings[1] if len(rankings) > 1 else [])  # type: ignore[arg-type]
        dense_weight = float(kwargs.get("dense_weight", 0.5))  # type: ignore[arg-type]
        sparse_weight = float(kwargs.get("sparse_weight", 0.5))  # type: ignore[arg-type]
        return log_odds_fusion(
            dense_scores=dense,  # type: ignore[arg-type]
            sparse_scores=sparse,  # type: ignore[arg-type]
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
        )

    raise ValueError(f"Unknown fusion strategy: {strategy!r} (expected rrf|convex|log_odds)")

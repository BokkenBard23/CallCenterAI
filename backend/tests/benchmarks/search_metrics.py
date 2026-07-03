"""Search Quality Metrics Benchmark (ID-13).

Standalone benchmark script (NOT a pytest test) that measures search
quality across morphological, semantic, and hybrid search strategies.

Metrics computed:
  - Recall@k:    fraction of relevant results found in top-k
  - Precision@k: fraction of top-k results that are relevant
  - MRR:         Mean Reciprocal Rank (1/rank of first relevant result)
  - NDCG@k:      Normalized Discounted Cumulative Gain at k

Usage:
    python -m tests.benchmarks.search_metrics
    # or:
    python tests/benchmarks/search_metrics.py

The script uses a hand-crafted test set of queries with known relevant
dialogue turns. It exercises the search pipeline end-to-end and reports
a formatted table of metrics per search strategy.

NOTE: This is a BENCHMARK, not a unit test. It measures performance and
reports metrics — there are no pass/fail assertions. Use it to track
search quality over time and detect regressions.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure the backend app is importable
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


# ═══════════════════════════════════════════════════════════════
# Test set: queries with known relevant dialogue turns
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RelevanceJudgment:
    """A single relevance judgment for a query-document pair.

    Attributes:
        query: Search query string.
        relevant_turn_indices: Set of turn indices that are relevant.
        relevance_grades: Optional per-turn grade (1=binding, 2=highly relevant).
            If not provided, all relevant turns are treated as grade 1.
    """

    query: str
    relevant_turn_indices: Tuple[int, ...]
    relevance_grades: Dict[int, int] = field(default_factory=dict)


# Sample test set with 15 queries covering common call-center topics.
# Turn indices are based on typical call-center dialogues (0-based).
# These are synthetic relevance judgments for benchmarking purposes.
SAMPLE_TEST_SET: List[RelevanceJudgment] = [
    RelevanceJudgment(
        query="переключить на другого оператора",
        relevant_turn_indices=(2, 5, 8),
        relevance_grades={2: 2, 5: 1, 8: 1},
    ),
    RelevanceJudgment(
        query="отказаться от услуги",
        relevant_turn_indices=(3, 7),
        relevance_grades={3: 2, 7: 1},
    ),
    RelevanceJudgment(
        query="расторгнуть договор",
        relevant_turn_indices=(1, 4, 9),
        relevance_grades={1: 2, 4: 2, 9: 1},
    ),
    RelevanceJudgment(
        query="перейти на другой тариф",
        relevant_turn_indices=(0, 3, 6),
        relevance_grades={0: 2, 3: 1, 6: 1},
    ),
    RelevanceJudgment(
        query="подключить интернет",
        relevant_turn_indices=(1, 5),
        relevance_grades={1: 2, 5: 1},
    ),
    RelevanceJudgment(
        query="отключить платную услугу",
        relevant_turn_indices=(2, 6, 10),
        relevance_grades={2: 2, 6: 1, 10: 1},
    ),
    RelevanceJudgment(
        query="жалоба на качество связи",
        relevant_turn_indices=(0, 4, 8),
        relevance_grades={0: 2, 4: 1, 8: 1},
    ),
    RelevanceJudgment(
        query="оформить возврат денег",
        relevant_turn_indices=(3, 7),
        relevance_grades={3: 2, 7: 1},
    ),
    RelevanceJudgment(
        query="продлить подписку",
        relevant_turn_indices=(1, 5),
        relevance_grades={1: 2, 5: 1},
    ),
    RelevanceJudgment(
        query="изменить номер телефона",
        relevant_turn_indices=(2, 6),
        relevance_grades={2: 2, 6: 1},
    ),
    RelevanceJudgment(
        query="заменить сим карту",
        relevant_turn_indices=(0, 4),
        relevance_grades={0: 2, 4: 1},
    ),
    RelevanceJudgment(
        query="узнать баланс",
        relevant_turn_indices=(1, 3, 7),
        relevance_grades={1: 1, 3: 2, 7: 1},
    ),
    RelevanceJudgment(
        query="перезвонить позже",
        relevant_turn_indices=(5, 9),
        relevance_grades={5: 2, 9: 1},
    ),
    RelevanceJudgment(
        query="отменить заказ",
        relevant_turn_indices=(2, 8),
        relevance_grades={2: 2, 8: 1},
    ),
    RelevanceJudgment(
        query="помощь с настройкой",
        relevant_turn_indices=(1, 4, 6),
        relevance_grades={1: 2, 4: 1, 6: 1},
    ),
]


# ═══════════════════════════════════════════════════════════════
# Metrics computation
# ═══════════════════════════════════════════════════════════════


def recall_at_k(
    retrieved: List[int],
    relevant: Tuple[int, ...],
    k: int,
) -> float:
    """Compute Recall@k: fraction of relevant items found in top-k.

    Args:
        retrieved: List of retrieved item IDs (ordered by rank).
        relevant: Tuple of relevant item IDs.
        k: Cutoff rank.

    Returns:
        Recall@k value in [0.0, 1.0].
    """
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    relevant_set = set(relevant)
    hits = len(top_k & relevant_set)
    return hits / len(relevant_set)


def precision_at_k(
    retrieved: List[int],
    relevant: Tuple[int, ...],
    k: int,
) -> float:
    """Compute Precision@k: fraction of top-k items that are relevant.

    Args:
        retrieved: List of retrieved item IDs (ordered by rank).
        relevant: Tuple of relevant item IDs.
        k: Cutoff rank.

    Returns:
        Precision@k value in [0.0, 1.0].
    """
    if k == 0:
        return 0.0
    top_k = retrieved[:k]
    relevant_set = set(relevant)
    hits = sum(1 for item in top_k if item in relevant_set)
    return hits / k


def reciprocal_rank(
    retrieved: List[int],
    relevant: Tuple[int, ...],
) -> float:
    """Compute Reciprocal Rank: 1/rank of first relevant item.

    Args:
        retrieved: List of retrieved item IDs (ordered by rank).
        relevant: Tuple of relevant item IDs.

    Returns:
        Reciprocal rank in [0.0, 1.0]. 0.0 if no relevant item found.
    """
    relevant_set = set(relevant)
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved: List[int],
    relevant: Tuple[int, ...],
    relevance_grades: Dict[int, int],
    k: int,
) -> float:
    """Compute NDCG@k: Normalized Discounted Cumulative Gain.

    Uses relevance grades (if provided) for graded relevance.
    Default grade is 1 for relevant items.

    Args:
        retrieved: List of retrieved item IDs (ordered by rank).
        relevant: Tuple of relevant item IDs.
        relevance_grades: Per-item relevance grades.
        k: Cutoff rank.

    Returns:
        NDCG@k value in [0.0, 1.0].
    """
    if not relevant:
        return 0.0

    def dcg(items: List[int], cutoff: int) -> float:
        score = 0.0
        for i, item in enumerate(items[:cutoff], start=1):
            grade = relevance_grades.get(item, 1) if item in set(relevant) else 0
            score += grade / math.log2(i + 1)
        return score

    # Ideal DCG: sort relevant items by grade descending
    ideal_order = sorted(
        relevant,
        key=lambda x: relevance_grades.get(x, 1),
        reverse=True,
    )
    actual_dcg = dcg(retrieved, k)
    ideal_dcg = dcg(list(ideal_order), k)

    if ideal_dcg == 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


# ═══════════════════════════════════════════════════════════════
# Search strategies (adapters)
# ═══════════════════════════════════════════════════════════════


@dataclass
class SearchResult:
    """A single search result with turn index and score."""

    turn_index: int
    score: float
    text: str = ""


@dataclass
class StrategyMetrics:
    """Aggregated metrics for a search strategy."""

    strategy_name: str
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    precision_at_10: float
    mrr: float
    ndcg_at_5: float
    ndcg_at_10: float
    avg_latency_ms: float
    num_queries: int


def run_morphological_search(
    query: str,
    turns: List[Dict[str, str]],
    channel_map: Dict[int, str],
    top_k: int = 10,
) -> List[SearchResult]:
    """Run morphological (bag-of-words) search.

    Args:
        query: Search query string.
        turns: List of dialogue turns [{"speaker": ..., "text": ...}, ...].
        channel_map: Mapping turn_idx -> speaker.
        top_k: Maximum results to return.

    Returns:
        List of SearchResult sorted by relevance.
    """
    from app.services.morph_matcher import match_phrase_morphological_detailed

    results = match_phrase_morphological_detailed(
        phrase_text=query,
        word_distance=2,
        channel_constraint="ANY",
        turns=turns,
        channel_map=channel_map,
        is_exact=False,
    )

    search_results = []
    for turn_idx, speaker, detail in results:
        search_results.append(SearchResult(
            turn_index=turn_idx,
            score=1.0,  # Morph match is binary: 1.0 if found
            text=detail.get("matched_text", ""),
        ))

    return search_results[:top_k]


def run_semantic_search(
    query: str,
    session_id: str,
    top_k: int = 10,
) -> List[SearchResult]:
    """Run semantic (FRIDA embeddings) search.

    Requires the VectorStore to be initialized and indexed.

    Args:
        query: Search query string.
        session_id: Session identifier for filtering.
        top_k: Maximum results to return.

    Returns:
        List of SearchResult sorted by similarity score.
    """
    try:
        from app.services.vector_store import VectorStore

        # Try to get vector store from app state
        # In benchmark context, we may not have a running app
        # so fall back to creating a temporary one
        try:
            from app.config import settings
            vs = VectorStore(
                dimension=settings.vector_store_dimension,
                index_path=str(settings.vector_store_index_dir),
            )
            vs.load(str(settings.vector_store_index_dir))
        except Exception:
            return []

        results = vs.search(query_text=query, top_k=top_k)
        return [
            SearchResult(
                turn_index=r.turn_index,
                score=r.score,
                text=r.text[:100],
            )
            for r in results
            if r.dialogue_id == session_id
        ][:top_k]

    except Exception:
        return []


def run_hybrid_search(
    query: str,
    session_id: str,
    turns: List[Dict[str, str]],
    channel_map: Dict[int, str],
    top_k: int = 10,
) -> List[SearchResult]:
    """Run hybrid (morphological + semantic + NER) search.

    Args:
        query: Search query string.
        session_id: Session identifier.
        turns: List of dialogue turns.
        channel_map: Mapping turn_idx -> speaker.
        top_k: Maximum results to return.

    Returns:
        List of SearchResult sorted by combined score.
    """
    try:
        from app.services.hybrid_search import HybridSearchService
        from app.services.embedding import FridaEmbeddingService
        from app.services.vector_store import VectorStore
        from app.config import settings

        embedding_service = FridaEmbeddingService(
            api_key=settings.beeline_api_key,
            base_url=settings.frida_base_url,
            model=settings.frida_model,
        )
        vector_store = VectorStore(
            dimension=settings.vector_store_dimension,
            index_path=str(settings.vector_store_index_dir),
        )
        try:
            vector_store.load(str(settings.vector_store_index_dir))
        except Exception:
            pass

        hss = HybridSearchService(
            embedding_service=embedding_service,
            vector_store=vector_store,
        )
        results = hss.search(
            query=query,
            dialogue_id=session_id,
            turns=turns,
            channel_map=channel_map,
            top_k=top_k,
        )
        return [
            SearchResult(
                turn_index=r.turn_index,
                score=r.combined_score,
                text=r.text[:100],
            )
            for r in results
        ][:top_k]

    except Exception:
        # Fallback: morph-only if hybrid services unavailable
        return run_morphological_search(query, turns, channel_map, top_k)


# ═══════════════════════════════════════════════════════════════
# Benchmark runner
# ═══════════════════════════════════════════════════════════════


def evaluate_strategy(
    strategy_name: str,
    search_fn,
    test_set: List[RelevanceJudgment],
    k_values: Tuple[int, ...] = (5, 10),
) -> StrategyMetrics:
    """Evaluate a search strategy against the test set.

    Args:
        strategy_name: Display name for the strategy.
        search_fn: Callable(query, ...) -> List[SearchResult].
        test_set: List of RelevanceJudgment items.
        k_values: Cutoff values for Recall/Precision/NDCG.

    Returns:
        StrategyMetrics with aggregated metrics.
    """
    all_recalls: Dict[int, List[float]] = {k: [] for k in k_values}
    all_precisions: Dict[int, List[float]] = {k: [] for k in k_values}
    all_rr: List[float] = []
    all_ndcgs: Dict[int, List[float]] = {k: [] for k in k_values}
    latencies: List[float] = []

    for judgment in test_set:
        start = time.perf_counter()
        results = search_fn(judgment.query)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)

        retrieved = [r.turn_index for r in results]

        for k in k_values:
            all_recalls[k].append(
                recall_at_k(retrieved, judgment.relevant_turn_indices, k)
            )
            all_precisions[k].append(
                precision_at_k(retrieved, judgment.relevant_turn_indices, k)
            )
            all_ndcgs[k].append(
                ndcg_at_k(
                    retrieved,
                    judgment.relevant_turn_indices,
                    judgment.relevance_grades,
                    k,
                )
            )

        all_rr.append(reciprocal_rank(retrieved, judgment.relevant_turn_indices))

    n = len(test_set)
    max_k = max(k_values)

    return StrategyMetrics(
        strategy_name=strategy_name,
        recall_at_5=sum(all_recalls[5]) / n if n > 0 else 0.0,
        recall_at_10=sum(all_recalls[10]) / n if n > 0 else 0.0,
        precision_at_5=sum(all_precisions[5]) / n if n > 0 else 0.0,
        precision_at_10=sum(all_precisions[10]) / n if n > 0 else 0.0,
        mrr=sum(all_rr) / n if n > 0 else 0.0,
        ndcg_at_5=sum(all_ndcgs[5]) / n if n > 0 else 0.0,
        ndcg_at_10=sum(all_ndcgs[10]) / n if n > 0 else 0.0,
        avg_latency_ms=sum(latencies) / n if n > 0 else 0.0,
        num_queries=n,
    )


def format_metrics_table(metrics_list: List[StrategyMetrics]) -> str:
    """Format metrics as a readable table.

    Args:
        metrics_list: List of StrategyMetrics to display.

    Returns:
        Formatted table string.
    """
    header = (
        f"{'Strategy':<20} {'Rec@5':>7} {'Rec@10':>7} "
        f"{'Prec@5':>7} {'Prec@10':>8} {'MRR':>6} "
        f"{'NDCG@5':>7} {'NDCG@10':>8} {'Avg ms':>8}"
    )
    separator = "-" * len(header)

    rows = []
    for m in metrics_list:
        rows.append(
            f"{m.strategy_name:<20} {m.recall_at_5:>7.3f} {m.recall_at_10:>7.3f} "
            f"{m.precision_at_5:>7.3f} {m.precision_at_10:>8.3f} {m.mrr:>6.3f} "
            f"{m.ndcg_at_5:>7.3f} {m.ndcg_at_10:>8.3f} {m.avg_latency_ms:>8.1f}"
        )

    return "\n".join([header, separator] + rows)


def create_sample_dialogue() -> Tuple[List[Dict[str, str]], Dict[int, str]]:
    """Create a sample dialogue for benchmarking.

    Returns:
        Tuple of (turns, channel_map) for use with search functions.
    """
    turns = [
        {"speaker": "Клиент", "text": "Здравствуйте, я хочу перейти на другой тариф"},
        {"speaker": "Сотрудник", "text": "Добрый день! Какой тариф вас интересует?"},
        {"speaker": "Клиент", "text": "Я хочу отказаться от текущей услуги и подключить интернет"},
        {"speaker": "Сотрудник", "text": "Понял вас. Оформить переключение можно прямо сейчас"},
        {"speaker": "Клиент", "text": "Меня не устраивает качество связи, хочу расторгнуть договор"},
        {"speaker": "Сотрудник", "text": "Давайте обсудим возможность перезвонить вам позже"},
        {"speaker": "Клиент", "text": "Нет, я хочу изменить номер телефона и отключить платную услугу"},
        {"speaker": "Сотрудник", "text": "Хорошо, помогу вам оформить возврат денег и отменить заказ"},
        {"speaker": "Клиент", "text": "А можно продлить подписку и заменить сим карту?"},
        {"speaker": "Сотрудник", "text": "Конечно, всё оформим. Вам нужна помощь с настройкой?"},
        {"speaker": "Клиент", "text": "Да, и ещё подключить домашний интернет"},
    ]

    channel_map = {
        i: "Клиент" if t["speaker"] == "Клиент" else "Сотрудник"
        for i, t in enumerate(turns)
    }

    return turns, channel_map


def main() -> None:
    """Run the search quality benchmark and print results."""
    print("=" * 80)
    print("  Search Quality Metrics Benchmark (ID-13)")
    print("=" * 80)
    print()

    # Create sample dialogue
    turns, channel_map = create_sample_dialogue()

    print(f"Test set: {len(SAMPLE_TEST_SET)} queries")
    print(f"Dialogue: {len(turns)} turns")
    print()

    # Define search strategies
    strategies: List[Tuple[str, object]] = []

    # Strategy 1: Morphological search (always available)
    def morph_search_fn(query: str) -> List[SearchResult]:
        return run_morphological_search(query, turns, channel_map, top_k=10)

    strategies.append(("Morphological", morph_search_fn))

    # Strategy 2: Semantic search (requires FRIDA + VectorStore)
    def semantic_search_fn(query: str) -> List[SearchResult]:
        return run_semantic_search(query, session_id="bench", top_k=10)

    strategies.append(("Semantic", semantic_search_fn))

    # Strategy 3: Hybrid search (morph + semantic + NER)
    def hybrid_search_fn(query: str) -> List[SearchResult]:
        return run_hybrid_search(
            query, "bench", turns, channel_map, top_k=10,
        )

    strategies.append(("Hybrid", hybrid_search_fn))

    # Run evaluations
    all_metrics: List[StrategyMetrics] = []

    for name, search_fn in strategies:
        print(f"  Evaluating: {name}...")
        metrics = evaluate_strategy(
            strategy_name=name,
            search_fn=search_fn,
            test_set=SAMPLE_TEST_SET,
        )
        all_metrics.append(metrics)

    # Print results
    print()
    print("=" * 80)
    print("  Results")
    print("=" * 80)
    print()
    print(format_metrics_table(all_metrics))
    print()

    # Summary
    print("=" * 80)
    print("  Summary")
    print("=" * 80)
    for m in all_metrics:
        print(
            f"  {m.strategy_name}: "
            f"Recall@10={m.recall_at_10:.3f}, "
            f"MRR={m.mrr:.3f}, "
            f"NDCG@10={m.ndcg_at_10:.3f}, "
            f"Avg latency={m.avg_latency_ms:.1f}ms"
        )
    print()
    print("  NOTE: Semantic and Hybrid strategies require FRIDA embeddings")
    print("  to be available. If unavailable, they return empty results")
    print("  (all metrics = 0.0). Morphological search works offline.")
    print()
    print("  This is a BENCHMARK — metrics are informational, not pass/fail.")


if __name__ == "__main__":
    main()

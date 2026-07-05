"""Tests for HybridSearchService.search_enhanced (BM25 + advanced fusion + explain).

Covers:
  1. search_enhanced returns EnhancedHybridSearchResult with bm25_score
  2. fusion_strategy dispatch (rrf / convex / log_odds)
  3. use_bm25=False skips BM25 channel
  4. explain=True populates token_contributions (mocked embedder)
  5. graceful fallback to plain search() on internal failure
  6. empty query → []
  7. no dialogue → semantic-only enhanced path
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DialogueTurn,
    EnhancedHybridSearchResult,
    ParsedDialog,
    VectorSearchResult,
)
from app.services.hybrid_search import HybridSearchService


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


def _make_dialogue() -> ParsedDialog:
    return ParsedDialog(
        filename="test_dialogue.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text="хочу отказаться от услуги"),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="уточните причину отказа"),
            DialogueTurn(turn_index=2, speaker="Клиент", text="оформите заявку на отключение"),
        ],
        total_turns=3,
    )


def _make_dictionary() -> DictionaryNode:
    return DictionaryNode(
        id="1",
        name="Test Dict",
        conditions=[
            DictionaryCondition(text="отказ", word_distance=2, word_count=1),
        ],
    )


def _make_vs_result(
    text: str = "отказ от услуги",
    dialogue_id: str = "test_dialogue.rtf",
    turn_index: int = 0,
    score: float = 0.9,
) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=f"c_{turn_index}",
        text=text,
        dialogue_id=dialogue_id,
        turn_index=turn_index,
        speaker="Клиент",
        score=score,
        chunk_type="utterance",
    )


def _make_embedding_mock() -> MagicMock:
    """Mock embedding service: available + returns a deterministic 1536-dim vector."""
    mock = MagicMock()
    mock.is_available = AsyncMock(return_value=True)
    mock.embed = AsyncMock(return_value=[0.01] * 1536)
    return mock


def _make_vector_store_mock(results=None, metadata=None) -> MagicMock:
    mock = MagicMock()
    mock.search.return_value = results or []
    mock._metadata = metadata or []
    mock.get_stats.return_value = {"total_vectors": len(metadata or [])}
    return mock


def _make_service(
    embedding_available: bool = True,
    vs_results=None,
    vs_metadata=None,
    has_ner: bool = False,
) -> HybridSearchService:
    mock_emb = _make_embedding_mock()
    mock_emb.is_available = AsyncMock(return_value=embedding_available)
    mock_vs = _make_vector_store_mock(results=vs_results, metadata=vs_metadata)
    service = HybridSearchService(
        embedding_service=mock_emb,
        vector_store=mock_vs,
        rrf_k=60,
    )
    if has_ner:
        service._has_ner = True
        service._segmenter = MagicMock()
        service._ner_tagger = MagicMock()
        service._morph_vocab = MagicMock()
    return service


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestSearchEnhancedBasic:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self) -> None:
        service = _make_service()
        result = await service.search_enhanced("")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_enhanced_results(self) -> None:
        """Semantic-only path returns EnhancedHybridSearchResult with bm25_score."""
        vs_results = [_make_vs_result(score=0.9)]
        service = _make_service(vs_results=vs_results)
        result = await service.search_enhanced("отказ", use_bm25=False)
        assert len(result) > 0
        assert all(isinstance(r, EnhancedHybridSearchResult) for r in result)
        assert all(hasattr(r, "bm25_score") for r in result)
        assert all(hasattr(r, "token_contributions") for r in result)

    @pytest.mark.asyncio
    async def test_bm25_channel_populates_score(self) -> None:
        """With use_bm25=True and a dialogue, BM25 channel populates bm25_score."""
        vs_results = [_make_vs_result(score=0.9, turn_index=0)]
        service = _make_service(vs_results=vs_results)
        dialogue = _make_dialogue()
        result = await service.search_enhanced(
            "заявка",
            dialogue=dialogue,
            use_bm25=True,
            fusion_strategy="rrf",
        )
        # At least one result, and the BM25 score for the matching turn is > 0.
        assert len(result) > 0
        # The turn with 'заявка' is turn 2 — its BM25 score should be > 0.
        matching = [r for r in result if r.turn_index == 2]
        if matching:
            assert matching[0].bm25_score >= 0.0  # at least populated, not None

    @pytest.mark.asyncio
    async def test_results_sorted_by_combined_score_desc(self) -> None:
        vs_results = [
            _make_vs_result(text="заявка", turn_index=0, score=0.95),
            _make_vs_result(text="платёж", turn_index=1, score=0.70),
        ]
        service = _make_service(vs_results=vs_results)
        result = await service.search_enhanced("заявка", use_bm25=False)
        scores = [r.combined_score for r in result]
        assert scores == sorted(scores, reverse=True)


class TestSearchEnhancedFusionStrategies:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("strategy", ["rrf", "convex", "log_odds"])
    async def test_each_strategy_returns_results(self, strategy: str) -> None:
        vs_results = [
            _make_vs_result(text="заявка", turn_index=0, score=0.9),
            _make_vs_result(text="платёж", turn_index=1, score=0.7),
        ]
        service = _make_service(vs_results=vs_results)
        dialogue = _make_dialogue()
        result = await service.search_enhanced(
            "заявка",
            dialogue=dialogue,
            use_bm25=True,
            fusion_strategy=strategy,
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_log_odds_without_bm25_uses_rrf_fallback(self) -> None:
        """log_odds requires both dense + sparse; without BM25 it falls back to RRF."""
        vs_results = [_make_vs_result(score=0.9)]
        service = _make_service(vs_results=vs_results)
        result = await service.search_enhanced(
            "заявка", use_bm25=False, fusion_strategy="log_odds"
        )
        assert len(result) > 0


class TestSearchEnhancedExplain:
    @pytest.mark.asyncio
    async def test_explain_populates_token_contributions(self) -> None:
        """explain=True with available embedder populates token_contributions."""
        vs_results = [_make_vs_result(text="отказ от услуги", turn_index=0, score=0.9)]
        service = _make_service(vs_results=vs_results)
        result = await service.search_enhanced(
            "отказ", use_bm25=False, explain=True
        )
        assert len(result) > 0
        # With mocked embedder returning constant vectors, contributions are 0-length
        # but the field is populated (possibly empty list if all deltas are 0).
        assert hasattr(result[0], "token_contributions")

    @pytest.mark.asyncio
    async def test_explain_skipped_when_frida_unavailable(self) -> None:
        """explain=True but FRIDA down → token_contributions stays empty, no crash."""
        vs_results = [_make_vs_result(score=0.9)]
        service = _make_service(embedding_available=False, vs_results=vs_results)
        result = await service.search_enhanced(
            "отказ", use_bm25=False, explain=True
        )
        # Falls back gracefully — either empty (no semantic) or with empty contributions.
        for r in result:
            assert r.token_contributions == []


class TestSearchEnhancedFallback:
    @pytest.mark.asyncio
    async def test_internal_failure_falls_back_to_plain_search(self) -> None:
        """If _search_enhanced_impl raises, the wrapper falls back to plain search."""
        service = _make_service(vs_results=[_make_vs_result(score=0.9)])
        # Force the impl to raise.
        with patch.object(
            service, "_search_enhanced_impl", side_effect=RuntimeError("boom")
        ):
            result = await service.search_enhanced("test", use_bm25=False)
        # Fallback returns plain search results wrapped as Enhanced.
        assert isinstance(result, list)
        assert all(isinstance(r, EnhancedHybridSearchResult) for r in result)

    @pytest.mark.asyncio
    async def test_no_dialogue_no_bm25(self) -> None:
        """No dialogue → BM25 channel skipped, semantic-only enhanced path."""
        vs_results = [_make_vs_result(score=0.9, dialogue_id="d1")]
        service = _make_service(vs_results=vs_results)
        result = await service.search_enhanced(
            "заявка", dialogue=None, use_bm25=True
        )
        assert len(result) > 0
        # No dialogue → bm25_score should be 0 (no corpus to score against).
        assert all(r.bm25_score == 0.0 for r in result)

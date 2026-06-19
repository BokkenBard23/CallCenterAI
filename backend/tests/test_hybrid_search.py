"""Tests for HybridSearchService (RRF + NER boost).

Covers:
  1. Morphological-only search → morph_score > 0
  2. Semantic-only search → semantic_score > 0
  3. Hybrid search → combined_score, source="hybrid"
  4. FRIDA unavailable → fallback to morphology, source="morph"
  5. Empty query → []
  6. RRF correctly combines ranks
  7. NER boost: chunks with matching entities get higher score
  8. Query NER extracts entities and compares with chunk entities
  9. Performance: search 1000 vectors < 200ms
  10. NER boost: PER entities boost results by ~0.1 per match
  11. Combined score > 0 for valid results
  12. top_k clamping (range 1–100)
  13. No dictionaries → semantic-only, source="semantic"
  14. No dialogue → semantic-only search
  15. Natasha NER unavailable → no NER boost (graceful degradation)
"""

from __future__ import annotations

import time
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DictMatch,
    HybridSearchResult,
    ParsedDialog,
    VectorSearchResult,
)
from app.services.hybrid_search import HybridSearchService, _MorphResult


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


def _make_dialogue(
    turns: list[tuple[str, str]] | None = None,
    filename: str = "test_dialogue.rtf",
) -> ParsedDialog:
    """Create a ParsedDialog with given turns.

    Args:
        turns: List of (speaker, text) pairs.
        filename: Dialogue filename.

    Returns:
        ParsedDialog instance.
    """
    from app.models import DialogueTurn

    if turns is None:
        turns = [
            ("Клиент", "Здравствуйте, я хочу отказаться от услуги"),
            ("Сотрудник", "Добрый день, уточните причину"),
            ("Клиент", "Иванов позвонил и сказал что не нужно"),
        ]

    parsed = ParsedDialog(filename=filename)
    for i, (speaker, text) in enumerate(turns):
        parsed.turns.append(
            DialogueTurn(turn_index=i, speaker=speaker, text=text),
        )
    parsed.total_turns = len(turns)
    return parsed


def _make_dictionary(
    name: str = "Test Dict",
    conditions: list[str] | None = None,
) -> DictionaryNode:
    """Create a DictionaryNode with given conditions.

    Args:
        name: Dictionary name.
        conditions: List of phrase texts.

    Returns:
        DictionaryNode instance.
    """
    cond_list = []
    for text in (conditions or ["отказ"]):
        cond_list.append(
            DictionaryCondition(
                text=text,
                word_distance=2,
                word_count=len(text.split()),
            ),
        )
    return DictionaryNode(
        id="1",
        name=name,
        conditions=cond_list,
    )


def _make_vector_search_result(
    text: str = "test text",
    dialogue_id: str = "dialog_1",
    turn_index: int = 0,
    speaker: str = "Клиент",
    score: float = 0.85,
    entities: list[dict[str, str]] | None = None,
) -> VectorSearchResult:
    """Create a VectorSearchResult for testing.

    Args:
        text: Chunk text.
        dialogue_id: Dialogue ID.
        turn_index: Turn index.
        speaker: Speaker role.
        score: Cosine similarity score.
        entities: NER entities list.

    Returns:
        VectorSearchResult instance.
    """
    return VectorSearchResult(
        chunk_id=f"chunk_{dialogue_id}_{turn_index}",
        text=text,
        dialogue_id=dialogue_id,
        turn_index=turn_index,
        speaker=speaker,
        score=score,
        chunk_type="utterance",
        entities=entities or [],
    )


def _make_mock_embedding_service(available: bool = True) -> MagicMock:
    """Create a mock FridaEmbeddingService.

    Args:
        available: Whether FRIDA is available.

    Returns:
        MagicMock with is_available and embed configured.
    """
    mock = MagicMock()
    mock.is_available = AsyncMock(return_value=available)
    mock.embed = AsyncMock(return_value=[0.1] * 1536)
    return mock


def _make_mock_vector_store(
    search_results: list[VectorSearchResult] | None = None,
    metadata: list[dict] | None = None,
) -> MagicMock:
    """Create a mock VectorStore.

    Args:
        search_results: Results to return from search().
        metadata: Metadata list for entity lookup.

    Returns:
        MagicMock with search and _metadata configured.
    """
    mock = MagicMock()
    mock.search.return_value = search_results or []
    mock._metadata = metadata or []
    mock.get_stats.return_value = {"total_vectors": len(metadata or [])}
    return mock


def _make_hybrid_service(
    embedding_available: bool = True,
    vector_store_results: list[VectorSearchResult] | None = None,
    vector_store_metadata: list[dict] | None = None,
    rrf_k: int = 60,
    ner_boost_per_match: float = 0.1,
    ner_per_weight: float = 1.5,
    has_ner: bool = False,
) -> HybridSearchService:
    """Create a HybridSearchService with mocked dependencies.

    Args:
        embedding_available: Whether FRIDA embedding service is available.
        vector_store_results: Results from VectorStore search.
        vector_store_metadata: VectorStore metadata for NER lookup.
        rrf_k: RRF constant k.
        ner_boost_per_match: NER boost per matched entity.
        ner_per_weight: PER entity weight multiplier.
        has_ner: Whether to mock Natasha NER as available.

    Returns:
        HybridSearchService with mocked dependencies.
    """
    mock_embedding = _make_mock_embedding_service(available=embedding_available)
    mock_vs = _make_mock_vector_store(
        search_results=vector_store_results,
        metadata=vector_store_metadata,
    )

    # Create service (NER init will fail in test env, which is fine)
    service = HybridSearchService(
        embedding_service=mock_embedding,
        vector_store=mock_vs,
        rrf_k=rrf_k,
        ner_boost_per_match=ner_boost_per_match,
        ner_per_weight=ner_per_weight,
    )

    # Override NER availability if requested
    if has_ner:
        service._has_ner = True
        service._segmenter = MagicMock()
        service._ner_tagger = MagicMock()
        service._morph_vocab = MagicMock()

    return service


# ═══════════════════════════════════════════════════════════
# Test: Empty query
# ═══════════════════════════════════════════════════════════


class TestEmptyQuery:
    """Test empty query handling."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self) -> None:
        """Empty query → []."""
        service = _make_hybrid_service()
        result = await service.search("")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_empty_list(self) -> None:
        """Whitespace-only query → []."""
        service = _make_hybrid_service()
        result = await service.search("   ")
        assert result == []

    @pytest.mark.asyncio
    async def test_none_query_returns_empty_list(self) -> None:
        """None-like empty query → []."""
        service = _make_hybrid_service()
        result = await service.search("")
        assert result == []


# ═══════════════════════════════════════════════════════════
# Test: Morphological-only search
# ═══════════════════════════════════════════════════════════


class TestMorphOnlySearch:
    """Test morphological-only search (no semantic)."""

    @pytest.mark.asyncio
    async def test_morph_only_with_dictionaries(self) -> None:
        """Morph search with dictionaries → morph_score > 0, source='morph'."""
        service = _make_hybrid_service(embedding_available=False)
        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        # Mock the morph search to return results
        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            matched_start=0,
            matched_end=10,
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
            match_type="sliding_window",
            word_distance_used=1,
            cascade_order=1,
            is_exact_match=False,
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
                matches_by_level={"1": 1},
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
                use_semantic=False,
            )

        assert len(result) > 0
        assert result[0].morph_score > 0
        assert result[0].source == "morph"

    @pytest.mark.asyncio
    async def test_morph_score_is_1_for_match(self) -> None:
        """Morph score is 1.0 for matched results."""
        service = _make_hybrid_service(embedding_available=False)
        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
                use_semantic=False,
            )

        assert result[0].morph_score == 1.0


# ═══════════════════════════════════════════════════════════
# Test: Semantic-only search
# ═══════════════════════════════════════════════════════════


class TestSemanticOnlySearch:
    """Test semantic-only search (no morph)."""

    @pytest.mark.asyncio
    async def test_semantic_only_no_dictionaries(self) -> None:
        """No dictionaries → semantic-only search, source='semantic'."""
        vs_results = [
            _make_vector_search_result(
                text="Клиент хочет отказаться",
                dialogue_id="dialog_1",
                turn_index=0,
                score=0.92,
            ),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="отказ от услуги")

        assert len(result) > 0
        assert result[0].semantic_score > 0
        assert result[0].source == "semantic"

    @pytest.mark.asyncio
    async def test_semantic_score_is_cosine_similarity(self) -> None:
        """Semantic score equals cosine similarity from VectorStore."""
        expected_score = 0.85
        vs_results = [
            _make_vector_search_result(score=expected_score),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="test query")

        assert result[0].semantic_score == expected_score

    @pytest.mark.asyncio
    async def test_no_dialogue_semantic_only(self) -> None:
        """No dialogue provided → semantic-only search."""
        vs_results = [
            _make_vector_search_result(score=0.8),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="test query", dialogue=None)

        assert len(result) > 0
        assert result[0].semantic_score > 0
        assert result[0].source == "semantic"


# ═══════════════════════════════════════════════════════════
# Test: Hybrid search (morph + semantic)
# ═══════════════════════════════════════════════════════════


class TestHybridSearch:
    """Test hybrid search combining morph + semantic."""

    @pytest.mark.asyncio
    async def test_hybrid_has_combined_score(self) -> None:
        """Hybrid search → combined_score > 0, source='hybrid'."""
        vs_results = [
            _make_vector_search_result(
                text="отказ от услуги",
                dialogue_id="test_dialogue.rtf",
                turn_index=0,
                score=0.9,
            ),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)
        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
            )

        assert len(result) > 0
        assert result[0].combined_score > 0
        assert result[0].source == "hybrid"

    @pytest.mark.asyncio
    async def test_hybrid_combined_score_greater_than_individual(self) -> None:
        """Combined score from both sources > individual RRF contribution."""
        vs_results = [
            _make_vector_search_result(
                text="отказ от услуги",
                dialogue_id="test_dialogue.rtf",
                turn_index=0,
                score=0.9,
            ),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results, rrf_k=60)
        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
            )

        # RRF contribution from both sources: 1/(1+60) + 1/(1+60) = 2/61
        expected_combined = 1.0 / (1 + 60) + 1.0 / (1 + 60)
        assert abs(result[0].combined_score - expected_combined) < 1e-6


# ═══════════════════════════════════════════════════════════
# Test: FRIDA unavailable → fallback to morph
# ═══════════════════════════════════════════════════════════


class TestFridaFallback:
    """Test graceful degradation when FRIDA is unavailable."""

    @pytest.mark.asyncio
    async def test_frida_unavailable_fallback_to_morph(self) -> None:
        """FRIDA unavailable → morph-only search, source='morph'."""
        service = _make_hybrid_service(embedding_available=False)
        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
            )

        assert len(result) > 0
        assert result[0].morph_score > 0
        assert result[0].source == "morph"
        assert result[0].semantic_score == 0.0

    @pytest.mark.asyncio
    async def test_frida_unavailable_no_semantic_score(self) -> None:
        """FRIDA unavailable → semantic_score should be 0.0."""
        service = _make_hybrid_service(embedding_available=False)
        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
            )

        for r in result:
            assert r.semantic_score == 0.0


# ═══════════════════════════════════════════════════════════
# Test: RRF formula correctness
# ═══════════════════════════════════════════════════════════


class TestRRFFormula:
    """Test Reciprocal Rank Fusion formula correctness."""

    def test_rrf_single_morph_result(self) -> None:
        """Single morph result at rank 1: combined_score = 1/(1+k)."""
        service = _make_hybrid_service(rrf_k=60)

        morph_results = [
            _MorphResult(
                turn_index=0,
                text="test",
                speaker="Клиент",
                dialogue_id="d1",
            ),
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=morph_results,
            semantic_results=[],
        )

        expected = 1.0 / (1 + 60)
        assert abs(merged[0].combined_score - expected) < 1e-6

    def test_rrf_single_semantic_result(self) -> None:
        """Single semantic result at rank 1: combined_score = 1/(1+k)."""
        service = _make_hybrid_service(rrf_k=60)

        semantic_results = [
            _make_vector_search_result(
                dialogue_id="d1",
                turn_index=0,
                score=0.9,
            ),
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=[],
            semantic_results=semantic_results,
        )

        expected = 1.0 / (1 + 60)
        assert abs(merged[0].combined_score - expected) < 1e-6

    def test_rrf_same_doc_both_sources(self) -> None:
        """Same doc from morph (rank 1) + semantic (rank 1): 1/(1+60) + 1/(1+60)."""
        service = _make_hybrid_service(rrf_k=60)

        morph_results = [
            _MorphResult(
                turn_index=0,
                text="test",
                speaker="Клиент",
                dialogue_id="d1",
            ),
        ]
        semantic_results = [
            _make_vector_search_result(
                dialogue_id="d1",
                turn_index=0,
                score=0.9,
            ),
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=morph_results,
            semantic_results=semantic_results,
        )

        # Same (dialogue_id, turn_index) → one result with combined RRF
        expected = 1.0 / (1 + 60) + 1.0 / (1 + 60)
        assert len(merged) == 1
        assert abs(merged[0].combined_score - expected) < 1e-6
        assert merged[0].morph_score == 1.0
        assert merged[0].semantic_score == 0.9

    def test_rrf_different_ranks_different_contribution(self) -> None:
        """Higher rank → lower RRF contribution."""
        service = _make_hybrid_service(rrf_k=60)

        # Two semantic results: rank 1 and rank 2
        semantic_results = [
            _make_vector_search_result(
                dialogue_id="d1",
                turn_index=0,
                score=0.9,
            ),
            _make_vector_search_result(
                dialogue_id="d2",
                turn_index=0,
                score=0.7,
            ),
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=[],
            semantic_results=semantic_results,
        )

        assert len(merged) == 2
        # Rank 1: 1/(1+60), Rank 2: 1/(2+60)
        assert merged[0].combined_score > merged[1].combined_score

    def test_rrf_custom_k(self) -> None:
        """RRF with custom k parameter."""
        service = _make_hybrid_service(rrf_k=30)

        morph_results = [
            _MorphResult(
                turn_index=0,
                text="test",
                speaker="Клиент",
                dialogue_id="d1",
            ),
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=morph_results,
            semantic_results=[],
        )

        expected = 1.0 / (1 + 30)
        assert abs(merged[0].combined_score - expected) < 1e-6

    def test_rrf_empty_both(self) -> None:
        """RRF with both empty → empty list."""
        service = _make_hybrid_service()

        merged = service._reciprocal_rank_fusion(
            morph_results=[],
            semantic_results=[],
        )

        assert merged == []

    def test_rrf_many_results(self) -> None:
        """RRF with many results correctly assigns ranks."""
        service = _make_hybrid_service(rrf_k=60)

        morph_results = [
            _MorphResult(
                turn_index=i,
                text=f"turn {i}",
                speaker="Клиент",
                dialogue_id="d1",
            )
            for i in range(5)
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=morph_results,
            semantic_results=[],
        )

        assert len(merged) == 5
        # Rank 1 should have highest score
        scores = [r.combined_score for r in merged]
        assert scores[0] > scores[-1]

    def test_rrf_morph_and_semantic_mixed_ranks(self) -> None:
        """RRF correctly merges morph and semantic results with different docs."""
        service = _make_hybrid_service(rrf_k=60)

        morph_results = [
            _MorphResult(
                turn_index=0,
                text="morph0",
                speaker="Клиент",
                dialogue_id="d1",
            ),
            _MorphResult(
                turn_index=1,
                text="morph1",
                speaker="Сотрудник",
                dialogue_id="d1",
            ),
        ]
        semantic_results = [
            _make_vector_search_result(
                dialogue_id="d1",
                turn_index=0,
                score=0.9,
            ),
            _make_vector_search_result(
                dialogue_id="d2",
                turn_index=0,
                score=0.8,
            ),
        ]

        merged = service._reciprocal_rank_fusion(
            morph_results=morph_results,
            semantic_results=semantic_results,
        )

        # d1/0 appears in both → combined score
        # d1/1 only in morph
        # d2/0 only in semantic
        assert len(merged) == 3

        # d1/0 should have highest combined_score (from both sources)
        d1_0 = next(r for r in merged if r.dialogue_id == "d1" and r.turn_index == 0)
        assert d1_0.morph_score == 1.0
        assert d1_0.semantic_score == 0.9
        # RRF: morph rank 1 → 1/(1+60), semantic rank 1 → 1/(1+60)
        expected = 1.0 / (1 + 60) + 1.0 / (1 + 60)
        assert abs(d1_0.combined_score - expected) < 1e-6


# ═══════════════════════════════════════════════════════════
# Test: NER boost
# ═══════════════════════════════════════════════════════════


class TestNERBoost:
    """Test NER boost computation and application."""

    def test_compute_ner_boost_no_match(self) -> None:
        """No matching entities → boost = 0."""
        service = _make_hybrid_service(ner_boost_per_match=0.1)

        query_entities = [{"text": "Иванов", "type": "PER", "normal": "иванов"}]
        chunk_entities = [{"text": "Москва", "type": "LOC", "normal": "москва"}]

        boost, matched = service._compute_ner_boost(query_entities, chunk_entities)
        assert boost == 0.0
        assert matched == []

    def test_compute_ner_boost_per_match(self) -> None:
        """PER entity match → boost = 0.1 × 1.5 (per_weight)."""
        service = _make_hybrid_service(
            ner_boost_per_match=0.1,
            ner_per_weight=1.5,
        )

        query_entities = [{"text": "Иванов", "type": "PER", "normal": "иванов"}]
        chunk_entities = [{"text": "Иванов", "type": "PER", "normal": "иванов"}]

        boost, matched = service._compute_ner_boost(query_entities, chunk_entities)
        expected = 0.1 * 1.5  # PER weight
        assert abs(boost - expected) < 1e-6
        assert "Иванов" in matched

    def test_compute_ner_boost_loc_match(self) -> None:
        """LOC entity match → boost = 0.1 × 1.0 (no per_weight)."""
        service = _make_hybrid_service(
            ner_boost_per_match=0.1,
            ner_per_weight=1.5,
        )

        query_entities = [{"text": "Москва", "type": "LOC", "normal": "москва"}]
        chunk_entities = [{"text": "Москва", "type": "LOC", "normal": "москва"}]

        boost, matched = service._compute_ner_boost(query_entities, chunk_entities)
        expected = 0.1 * 1.0  # LOC: no per_weight
        assert abs(boost - expected) < 1e-6
        assert "Москва" in matched

    def test_compute_ner_boost_multiple_matches(self) -> None:
        """Multiple matching entities → sum of boosts."""
        service = _make_hybrid_service(
            ner_boost_per_match=0.1,
            ner_per_weight=1.5,
        )

        query_entities = [
            {"text": "Иванов", "type": "PER", "normal": "иванов"},
            {"text": "Москва", "type": "LOC", "normal": "москва"},
        ]
        chunk_entities = [
            {"text": "Иванов", "type": "PER", "normal": "иванов"},
            {"text": "Москва", "type": "LOC", "normal": "москва"},
        ]

        boost, matched = service._compute_ner_boost(query_entities, chunk_entities)
        expected = 0.1 * 1.5 + 0.1 * 1.0  # PER + LOC
        assert abs(boost - expected) < 1e-6
        assert len(matched) == 2

    def test_compute_ner_boost_case_insensitive(self) -> None:
        """NER match is case-insensitive."""
        service = _make_hybrid_service(ner_boost_per_match=0.1)

        query_entities = [{"text": "Иванов", "type": "PER"}]
        chunk_entities = [{"text": "иванов", "type": "PER"}]

        boost, matched = service._compute_ner_boost(query_entities, chunk_entities)
        assert boost > 0
        assert len(matched) > 0

    def test_compute_ner_boost_normal_form_match(self) -> None:
        """NER match via normal form."""
        service = _make_hybrid_service(ner_boost_per_match=0.1)

        query_entities = [{"text": "Иванову", "type": "PER", "normal": "иванов"}]
        chunk_entities = [{"text": "Иванов", "type": "PER", "normal": "иванов"}]

        boost, matched = service._compute_ner_boost(query_entities, chunk_entities)
        assert boost > 0

    def test_compute_ner_boost_empty_entities(self) -> None:
        """Empty entities list → no boost."""
        service = _make_hybrid_service(ner_boost_per_match=0.1)

        boost, matched = service._compute_ner_boost([], [])
        assert boost == 0.0
        assert matched == []

        boost2, matched2 = service._compute_ner_boost(
            [{"text": "Иванов", "type": "PER"}], [],
        )
        assert boost2 == 0.0

    def test_apply_ner_boost_updates_combined_score(self) -> None:
        """_apply_ner_boost adds ner_boost to combined_score."""
        service = _make_hybrid_service(
            ner_boost_per_match=0.1,
            ner_per_weight=1.5,
        )

        results = [
            HybridSearchResult(
                text="test",
                dialogue_id="d1",
                turn_index=0,
                speaker="Клиент",
                combined_score=0.03,
            ),
        ]

        # Set up vector store metadata with matching entity
        service.vector_store._metadata = [
            {
                "dialogue_id": "d1",
                "turn_index": 0,
                "entities": [{"text": "Иванов", "type": "PER", "normal": "иванов"}],
            },
        ]

        query_entities = [{"text": "Иванов", "type": "PER", "normal": "иванов"}]

        updated = service._apply_ner_boost(results, query_entities)

        assert updated[0].ner_boost > 0
        assert updated[0].matched_entities == ["Иванов"]
        assert updated[0].combined_score > 0.03  # original + boost

    def test_ner_boost_makes_matching_result_rank_higher(self) -> None:
        """NER boost should make results with matching entities rank higher."""
        service = _make_hybrid_service(
            ner_boost_per_match=0.1,
            ner_per_weight=1.5,
        )

        results = [
            HybridSearchResult(
                text="chunk without entity",
                dialogue_id="d1",
                turn_index=0,
                speaker="Клиент",
                combined_score=0.04,
            ),
            HybridSearchResult(
                text="chunk with entity",
                dialogue_id="d2",
                turn_index=0,
                speaker="Клиент",
                combined_score=0.03,
            ),
        ]

        # d2 has matching entity
        service.vector_store._metadata = [
            {
                "dialogue_id": "d1",
                "turn_index": 0,
                "entities": [],
            },
            {
                "dialogue_id": "d2",
                "turn_index": 0,
                "entities": [{"text": "Иванов", "type": "PER", "normal": "иванов"}],
            },
        ]

        query_entities = [{"text": "Иванов", "type": "PER", "normal": "иванов"}]

        updated = service._apply_ner_boost(results, query_entities)
        updated.sort(key=lambda r: r.combined_score, reverse=True)

        # d2 should now rank higher due to NER boost
        assert updated[0].dialogue_id == "d2"
        assert updated[0].ner_boost > 0


# ═══════════════════════════════════════════════════════════
# Test: Query NER extraction
# ═══════════════════════════════════════════════════════════


class TestQueryNERExtraction:
    """Test query entity extraction."""

    def test_extract_query_entities_no_ner(self) -> None:
        """No NER available → empty list."""
        service = _make_hybrid_service(has_ner=False)
        entities = service._extract_query_entities("Иванов позвонил")
        assert entities == []

    def test_extract_query_entities_with_ner_mock(self) -> None:
        """Query NER extracts entities via Natasha mock."""
        service = _make_hybrid_service(has_ner=True)

        # Mock Natasha Doc
        mock_span = MagicMock()
        mock_span.text = "Иванов"
        mock_span.type = "PER"
        mock_span.normal = "иванов"
        mock_span.normalize = MagicMock()

        mock_doc = MagicMock()
        mock_doc.spans = [mock_span]

        with patch("natasha.Doc", return_value=mock_doc):
            entities = service._extract_query_entities("Иванов позвонил")

        assert len(entities) == 1
        assert entities[0]["text"] == "Иванов"
        assert entities[0]["type"] == "PER"

    def test_extract_query_entities_failure_graceful(self) -> None:
        """NER extraction failure → empty list, no exception."""
        service = _make_hybrid_service(has_ner=True)

        with patch("natasha.Doc", side_effect=Exception("NER fail")):
            entities = service._extract_query_entities("test")

        assert entities == []

    def test_extract_entities_normal_form(self) -> None:
        """NER extraction includes normal form when available."""
        service = _make_hybrid_service(has_ner=True)

        mock_span = MagicMock()
        mock_span.text = "Иванову"
        mock_span.type = "PER"
        mock_span.normal = "иванов"
        mock_span.normalize = MagicMock()

        mock_doc = MagicMock()
        mock_doc.spans = [mock_span]

        with patch("natasha.Doc", return_value=mock_doc):
            entities = service._extract_query_entities("Иванову позвонил")

        assert entities[0]["normal"] == "иванов"


# ═══════════════════════════════════════════════════════════
# Test: Combined score validity
# ═══════════════════════════════════════════════════════════


class TestCombinedScoreValidity:
    """Test that combined_score is always valid."""

    @pytest.mark.asyncio
    async def test_combined_score_positive_for_valid_results(self) -> None:
        """Combined score > 0 for valid results."""
        vs_results = [
            _make_vector_search_result(score=0.8),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="test query")

        for r in result:
            assert r.combined_score > 0

    @pytest.mark.asyncio
    async def test_results_sorted_by_combined_score_desc(self) -> None:
        """Results are sorted by combined_score descending."""
        vs_results = [
            _make_vector_search_result(
                dialogue_id="d2",
                turn_index=0,
                score=0.7,
            ),
            _make_vector_search_result(
                dialogue_id="d1",
                turn_index=0,
                score=0.9,
            ),
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="test query", top_k=10)

        for i in range(len(result) - 1):
            assert result[i].combined_score >= result[i + 1].combined_score


# ═══════════════════════════════════════════════════════════
# Test: top_k clamping
# ═══════════════════════════════════════════════════════════


class TestTopKClamping:
    """Test top_k parameter clamping."""

    @pytest.mark.asyncio
    async def test_top_k_below_minimum_clamped_to_1(self) -> None:
        """top_k < 1 → clamped to 1."""
        vs_results = [_make_vector_search_result(score=0.8)]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="test", top_k=0)
        assert len(result) <= 1

    @pytest.mark.asyncio
    async def test_top_k_above_maximum_clamped_to_100(self) -> None:
        """top_k > 100 → clamped to 100."""
        service = _make_hybrid_service(vector_store_results=[])

        result = await service.search(query="test", top_k=200)
        assert len(result) <= 100

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self) -> None:
        """top_k correctly limits the number of results."""
        vs_results = [
            _make_vector_search_result(
                dialogue_id=f"d{i}",
                turn_index=0,
                score=0.9 - i * 0.05,
            )
            for i in range(10)
        ]
        service = _make_hybrid_service(vector_store_results=vs_results)

        result = await service.search(query="test", top_k=3)
        assert len(result) <= 3


# ═══════════════════════════════════════════════════════════
# Test: Graceful degradation (no NER)
# ═══════════════════════════════════════════════════════════


class TestGracefulDegradation:
    """Test graceful degradation when NER is unavailable."""

    @pytest.mark.asyncio
    async def test_no_ner_no_boost(self) -> None:
        """Natasha NER unavailable → no NER boost applied."""
        service = _make_hybrid_service(has_ner=False)
        vs_results = [_make_vector_search_result(score=0.8)]
        service.vector_store.search.return_value = vs_results

        result = await service.search(query="Иванов позвонил", use_ner=True)

        for r in result:
            assert r.ner_boost == 0.0
            assert r.matched_entities == []

    @pytest.mark.asyncio
    async def test_use_ner_false_skips_ner(self) -> None:
        """use_ner=False → no NER boost even if NER is available."""
        service = _make_hybrid_service(has_ner=True)
        vs_results = [_make_vector_search_result(score=0.8)]
        service.vector_store.search.return_value = vs_results

        result = await service.search(query="Иванов позвонил", use_ner=False)

        for r in result:
            assert r.ner_boost == 0.0


# ═══════════════════════════════════════════════════════════
# Test: Performance
# ═══════════════════════════════════════════════════════════


class TestPerformance:
    """Test performance benchmarks."""

    @pytest.mark.asyncio
    async def test_search_1000_vectors_under_200ms(self) -> None:
        """Hybrid search with 1000 vectors should complete under 200ms."""
        # Create 1000 mock results
        vs_results = [
            _make_vector_search_result(
                dialogue_id=f"d{i % 100}",
                turn_index=i % 10,
                score=0.9 - (i * 0.0005),
                text=f"text {i}",
            )
            for i in range(1000)
        ]
        service = _make_hybrid_service(vector_store_results=vs_results[:10])
        # Override to return 1000 results for the performance test
        service.vector_store.search.return_value = vs_results

        start = time.monotonic()
        result = await service.search(query="test query", top_k=10)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert len(result) <= 10
        # Performance target: < 200ms
        assert elapsed_ms < 200, f"Search took {elapsed_ms:.1f}ms (target: <200ms)"

    def test_rrf_merge_100_results_under_50ms(self) -> None:
        """RRF merge with 100 results should complete under 50ms."""
        service = _make_hybrid_service(rrf_k=60)

        morph_results = [
            _MorphResult(
                turn_index=i,
                text=f"morph text {i}",
                speaker="Клиент",
                dialogue_id=f"d{i % 50}",
            )
            for i in range(50)
        ]
        semantic_results = [
            _make_vector_search_result(
                dialogue_id=f"d{i % 50}",
                turn_index=i % 10,
                score=0.9 - (i * 0.005),
            )
            for i in range(50)
        ]

        start = time.monotonic()
        merged = service._reciprocal_rank_fusion(morph_results, semantic_results)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert len(merged) > 0
        # Performance target: < 50ms
        assert elapsed_ms < 50, f"RRF merge took {elapsed_ms:.1f}ms (target: <50ms)"


# ═══════════════════════════════════════════════════════════
# Test: get_stats
# ═══════════════════════════════════════════════════════════


class TestGetStats:
    """Test get_stats observability."""

    def test_get_stats_returns_configuration(self) -> None:
        """get_stats returns configuration values."""
        service = _make_hybrid_service(rrf_k=42, ner_boost_per_match=0.15, ner_per_weight=2.0)

        stats = service.get_stats()

        assert stats["rrf_k"] == 42
        assert stats["ner_boost_per_match"] == 0.15
        assert stats["ner_per_weight"] == 2.0
        assert "ner_available" in stats
        assert "vector_store_total_vectors" in stats


# ═══════════════════════════════════════════════════════════
# Test: HybridSearchResult model
# ═══════════════════════════════════════════════════════════


class TestHybridSearchResultModel:
    """Test HybridSearchResult Pydantic model."""

    def test_default_values(self) -> None:
        """HybridSearchResult has correct defaults."""
        result = HybridSearchResult(
            text="test",
            dialogue_id="d1",
            turn_index=0,
            speaker="Клиент",
        )
        assert result.morph_score == 0.0
        assert result.morph_match is None
        assert result.semantic_score == 0.0
        assert result.ner_boost == 0.0
        assert result.matched_entities == []
        assert result.combined_score == 0.0
        assert result.source == "hybrid"

    def test_all_fields_set(self) -> None:
        """HybridSearchResult with all fields set."""
        match = DictMatch(
            phrase_text="отказ",
            quarter="Dict1",
            turn_index=0,
            speaker="Клиент",
        )
        result = HybridSearchResult(
            text="отказ от услуги",
            dialogue_id="d1",
            turn_index=0,
            speaker="Клиент",
            morph_score=1.0,
            morph_match=match,
            semantic_score=0.85,
            ner_boost=0.15,
            matched_entities=["Иванов"],
            combined_score=0.05,
            source="ner_boost",
        )
        assert result.morph_score == 1.0
        assert result.semantic_score == 0.85
        assert result.ner_boost == 0.15
        assert result.combined_score == 0.05
        assert result.source == "ner_boost"
        assert result.morph_match is not None

    def test_serialization(self) -> None:
        """HybridSearchResult serializes to dict correctly."""
        result = HybridSearchResult(
            text="test",
            dialogue_id="d1",
            turn_index=0,
            speaker="Клиент",
            combined_score=0.05,
        )
        data = result.model_dump()
        assert data["text"] == "test"
        assert data["combined_score"] == 0.05
        assert data["source"] == "hybrid"


# ═══════════════════════════════════════════════════════════
# Test: Circuit breaker integration
# ═══════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Test graceful handling when FRIDA circuit breaker is open."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_fallback_to_morph(self) -> None:
        """Circuit breaker open → fallback to morphological search."""
        mock_embedding = _make_mock_embedding_service(available=False)
        mock_embedding.embed = AsyncMock(side_effect=ConnectionError("Circuit open"))

        mock_vs = _make_mock_vector_store()
        service = HybridSearchService(
            embedding_service=mock_embedding,
            vector_store=mock_vs,
        )

        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
            )

        assert len(result) > 0
        assert result[0].source == "morph"


# ═══════════════════════════════════════════════════════════
# Test: Full integration (both morph + semantic + NER)
# ═══════════════════════════════════════════════════════════


class TestFullIntegration:
    """Test full hybrid search integration with all signals."""

    @pytest.mark.asyncio
    async def test_full_hybrid_morph_semantic_ner(self) -> None:
        """Full hybrid with morph + semantic + NER boost."""
        vs_results = [
            _make_vector_search_result(
                text="Иванов позвонил и сказал отказаться",
                dialogue_id="test_dialogue.rtf",
                turn_index=2,
                score=0.92,
                entities=[{"text": "Иванов", "type": "PER", "normal": "иванов"}],
            ),
            _make_vector_search_result(
                text="Здравствуйте, я хочу отказаться от услуги",
                dialogue_id="test_dialogue.rtf",
                turn_index=0,
                score=0.80,
                entities=[],
            ),
        ]
        service = _make_hybrid_service(
            vector_store_results=vs_results,
            has_ner=True,
            ner_boost_per_match=0.1,
            ner_per_weight=1.5,
        )

        # Set up vector store metadata for NER lookup
        service.vector_store._metadata = [
            {
                "dialogue_id": "test_dialogue.rtf",
                "turn_index": 2,
                "entities": [{"text": "Иванов", "type": "PER", "normal": "иванов"}],
            },
            {
                "dialogue_id": "test_dialogue.rtf",
                "turn_index": 0,
                "entities": [],
            },
        ]

        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary(conditions=["отказ"])]

        mock_match = DictMatch(
            phrase_text="отказ",
            matched_text="отказаться",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )

        # Mock NER extraction
        mock_span = MagicMock()
        mock_span.text = "Иванов"
        mock_span.type = "PER"
        mock_span.normal = "иванов"
        mock_span.normalize = MagicMock()
        mock_doc = MagicMock()
        mock_doc.spans = [mock_span]

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search, patch(
            "natasha.Doc", return_value=mock_doc,
        ):
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=1,
                matches=[mock_match],
            )

            result = await service.search(
                query="Иванов отказ",
                dialogue=dialogue,
                dictionaries=dictionaries,
                use_ner=True,
            )

        assert len(result) > 0
        # All results should have combined_score > 0
        for r in result:
            assert r.combined_score > 0

        # Result with matching entity should have ner_boost > 0
        with_entity = [r for r in result if r.ner_boost > 0]
        assert len(with_entity) > 0, "At least one result should have NER boost"

    @pytest.mark.asyncio
    async def test_no_results_returns_empty(self) -> None:
        """No morph matches and no semantic results → empty list."""
        service = _make_hybrid_service(vector_store_results=[])
        service.embedding_service.is_available = AsyncMock(return_value=True)

        dialogue = _make_dialogue()
        dictionaries = [_make_dictionary()]

        with patch(
            "app.services.search.run_hierarchical_search",
            new_callable=AsyncMock,
        ) as mock_search:
            from app.models import SearchResult

            mock_search.return_value = SearchResult(
                segments=[],
                total_matches=0,
                matches=[],
            )

            result = await service.search(
                query="nonexistent",
                dialogue=dialogue,
                dictionaries=dictionaries,
            )

        assert result == []

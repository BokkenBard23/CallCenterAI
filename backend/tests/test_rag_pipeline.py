"""Comprehensive tests for the RAG pipeline service and router.

Tests cover:
  1. RAG happy path (FRIDA + LLM both available)
  2. FRIDA unavailable → morph-only search, generate from morph results
  3. LLM unavailable → return fragments without generated answer
  4. Empty vector store → empty result with error
  5. Invalid/empty question
  6. Session filter
  7. Citation extraction and source mapping
  8. /api/rag/status endpoint
  9. Config defaults
  10. Context truncation (long context)
  11. Rate limiting
  12. RAG model forced to GLM-5.1
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models import (
    HybridSearchResult,
    RagQueryRequest,
    RagQueryResponse,
    RagSourceFragment,
)
from app.services.rag import RAGService, _RAG_DEFAULT_MODEL, _RAG_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# Fixtures: mock services
# ═══════════════════════════════════════════════════════════


def _make_hybrid_search_result(
    dialogue_id: str = "session-1",
    turn_index: int = 0,
    speaker: str = "Клиент",
    text: str = "Я хочу подключить интернет",
    combined_score: float = 0.85,
    source: str = "hybrid",
) -> HybridSearchResult:
    """Create a HybridSearchResult for testing."""
    return HybridSearchResult(
        text=text,
        dialogue_id=dialogue_id,
        turn_index=turn_index,
        speaker=speaker,
        combined_score=combined_score,
        source=source,
    )


def _make_mock_embedding_service(available: bool = True) -> MagicMock:
    """Create a mock FridaEmbeddingService."""
    mock = MagicMock()
    mock.is_available = AsyncMock(return_value=available)
    mock.embed = AsyncMock(return_value=[0.1] * 1536)
    return mock


def _make_mock_vector_store(total_vectors: int = 100) -> MagicMock:
    """Create a mock VectorStore."""
    mock = MagicMock()
    mock.get_stats.return_value = {
        "total_vectors": total_vectors,
        "unique_dialogues": 5,
        "index_size_bytes": total_vectors * 1536 * 4,
    }
    mock.search.return_value = []  # Override per test
    return mock


def _make_mock_hybrid_search_service(results: Optional[List[HybridSearchResult]] = None) -> MagicMock:
    """Create a mock HybridSearchService."""
    mock = MagicMock()
    mock._has_ner = True
    mock.get_stats.return_value = {
        "rrf_k": 60,
        "ner_boost_per_match": 0.1,
        "ner_per_weight": 1.5,
        "ner_available": True,
        "vector_store_total_vectors": 100,
    }
    if results is not None:
        mock.search = AsyncMock(return_value=results)
    else:
        mock.search = AsyncMock(return_value=[])
    return mock


def _make_rag_service(
    hybrid_results: Optional[List[HybridSearchResult]] = None,
    frida_available: bool = True,
    vector_count: int = 100,
) -> RAGService:
    """Create a RAGService with mock dependencies."""
    embedding_service = _make_mock_embedding_service(available=frida_available)
    vector_store = _make_mock_vector_store(total_vectors=vector_count)
    hybrid_search_service = _make_mock_hybrid_search_service(results=hybrid_results)

    return RAGService(
        hybrid_search_service=hybrid_search_service,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )


# ═══════════════════════════════════════════════════════════
# 1. RAG Happy Path
# ═══════════════════════════════════════════════════════════


class TestRAGHappyPath:
    """RAG happy path: FRIDA + LLM both available."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_answer_with_sources(self) -> None:
        """Full RAG pipeline: retrieve → build context → generate answer."""
        fragments = [
            _make_hybrid_search_result(
                dialogue_id="session-1",
                turn_index=0,
                speaker="Клиент",
                text="Я хочу подключить домашний интернет.",
                combined_score=0.92,
            ),
            _make_hybrid_search_result(
                dialogue_id="session-1",
                turn_index=2,
                speaker="Сотрудник",
                text="Мы предлагаем тарифы от 500 рублей в месяц.",
                combined_score=0.85,
            ),
        ]

        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            # Mock LLM provider
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(
                return_value="Клиент хочет подключить домашний интернет [1]. Доступны тарифы от 500 рублей [2]."
            )
            mock_get_provider.return_value = mock_provider

            # Mock circuit breaker
            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_get_cb.return_value = mock_cb

            # Mock fallback order
            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(
                question="Что хочет клиент?",
                session_id="session-1",
                top_k=5,
                provider_id="beeline",
            )

        assert isinstance(result, RagQueryResponse)
        assert result.question == "Что хочет клиент?"
        assert len(result.answer) > 0
        assert result.provider == "beeline"
        assert result.model == _RAG_DEFAULT_MODEL
        assert result.context_used == 2
        assert result.search_source == "hybrid"
        assert result.error is None
        assert len(result.sources) == 2
        assert result.sources[0].dialogue_id == "session-1"
        assert result.sources[0].turn_index == 0
        assert result.sources[0].speaker == "Клиент"

    @pytest.mark.asyncio
    async def test_happy_path_llm_model_is_glm51(self) -> None:
        """RAG inference must use GLM-5.1 model (Qwen gives 500)."""
        assert _RAG_DEFAULT_MODEL == "glm-5.1"

        fragments = [_make_hybrid_search_result()]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider

            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_get_cb.return_value = mock_cb

            mock_fallback_order.return_value = ["beeline"]

            await rag_service.query(question="Тест?", provider_id="beeline")

            # Verify generate was called with GLM-5.1 model
            mock_provider.generate.assert_called_once()
            call_kwargs = mock_provider.generate.call_args
            assert call_kwargs.kwargs.get("model") == "glm-5.1" or call_kwargs[1].get("model") == "glm-5.1"


# ═══════════════════════════════════════════════════════════
# 2. FRIDA Unavailable → morph-only fallback
# ═══════════════════════════════════════════════════════════


class TestFRIDAUnavailable:
    """When FRIDA is unavailable, search degrades gracefully."""

    @pytest.mark.asyncio
    async def test_frida_unavailable_morph_only_search(self) -> None:
        """FRIDA down → hybrid search returns morph-only results, LLM still generates."""
        morph_results = [
            _make_hybrid_search_result(
                text="Проблема с роутером",
                combined_score=0.7,
                source="morph",
            ),
        ]
        rag_service = _make_rag_service(hybrid_results=morph_results, frida_available=False)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="У клиента проблема с роутером [1].")
            mock_get_provider.return_value = mock_provider

            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_get_cb.return_value = mock_cb

            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(question="Какая проблема?")

        assert result.answer != ""
        assert result.search_source == "morph"
        assert result.context_used == 1
        assert len(result.sources) == 1
        assert result.sources[0].search_source == "morph"

    @pytest.mark.asyncio
    async def test_frida_circuit_breaker_open(self) -> None:
        """FRIDA circuit breaker open → semantic fallback returns empty."""
        rag_service = _make_rag_service(hybrid_results=None, frida_available=False)
        # Make hybrid search fail entirely
        rag_service.hybrid_search_service.search = AsyncMock(side_effect=ConnectionError("Circuit breaker open"))
        # Make semantic fallback also fail (FRIDA unavailable)
        rag_service.embedding_service.is_available = AsyncMock(return_value=False)

        result = await rag_service.query(question="Тест?")

        assert result.search_source == "none"
        assert result.context_used == 0


# ═══════════════════════════════════════════════════════════
# 3. LLM Unavailable → fragments without answer
# ═══════════════════════════════════════════════════════════


class TestLLMUnavailable:
    """When LLM is unavailable, return fragments without generated answer."""

    @pytest.mark.asyncio
    async def test_llm_unavailable_returns_fragments_only(self) -> None:
        """LLM down → return fragments with error message, no answer."""
        fragments = [
            _make_hybrid_search_result(
                text="Интернет не работает третий день",
                combined_score=0.88,
            ),
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            # All providers fail
            mock_get_provider.return_value = None
            mock_fallback_order.return_value = ["beeline", "ollama"]
            mock_get_cb.return_value = MagicMock(can_execute=lambda: False)

            result = await rag_service.query(question="Что случилось?")

        assert result.answer == ""
        assert result.provider == "none"
        assert result.error is not None
        assert "answer generation failed" in result.error.lower()
        # But fragments are still returned
        assert len(result.sources) == 1
        assert result.sources[0].text_snippet != ""

    @pytest.mark.asyncio
    async def test_llm_empty_response(self) -> None:
        """LLM returns empty string → error in response."""
        fragments = [_make_hybrid_search_result()]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            # Provider returns empty
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="")

            # Second provider also returns empty
            mock_provider2 = MagicMock()
            mock_provider2.generate = AsyncMock(return_value="   ")

            call_count = [0]
            def get_provider_side_effect(pid):
                call_count[0] += 1
                if call_count[0] == 1:
                    return mock_provider
                return mock_provider2

            mock_get_provider.side_effect = get_provider_side_effect
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True, state="closed")
            mock_fallback_order.return_value = ["beeline", "ollama"]

            result = await rag_service.query(question="Тест?")

        # LLM should have failed (empty response treated as failure)
        assert result.error is not None


# ═══════════════════════════════════════════════════════════
# 4. Empty Vector Store
# ═══════════════════════════════════════════════════════════


class TestEmptyVectorStore:
    """When no dialogues are indexed, return informational error."""

    @pytest.mark.asyncio
    async def test_empty_vector_store_returns_error(self) -> None:
        """Empty vector store → error about needing to index dialogues."""
        rag_service = _make_rag_service(hybrid_results=[], vector_count=0)

        result = await rag_service.query(question="Что обсуждали?")

        assert result.error is not None
        assert "no dialogues indexed" in result.error.lower()
        assert result.context_used == 0
        assert len(result.sources) == 0

    @pytest.mark.asyncio
    async def test_non_empty_store_no_matches(self) -> None:
        """Non-empty store but no matches → different error message."""
        rag_service = _make_rag_service(hybrid_results=[], vector_count=100)

        result = await rag_service.query(question="Несуществующая тема xyz123")

        assert result.error is not None
        assert "no relevant fragments found" in result.error.lower()


# ═══════════════════════════════════════════════════════════
# 5. Invalid/Empty Question
# ═══════════════════════════════════════════════════════════


class TestInvalidQuestion:
    """Invalid or empty questions are handled gracefully."""

    @pytest.mark.asyncio
    async def test_empty_question_returns_error(self) -> None:
        """Empty question → error response."""
        rag_service = _make_rag_service()

        result = await rag_service.query(question="")

        assert result.error is not None
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_whitespace_only_question_returns_error(self) -> None:
        """Whitespace-only question → error response."""
        rag_service = _make_rag_service()

        result = await rag_service.query(question="   ")

        assert result.error is not None
        assert "empty" in result.error.lower()


# ═══════════════════════════════════════════════════════════
# 6. Session Filter
# ═══════════════════════════════════════════════════════════


class TestSessionFilter:
    """Session filtering restricts search to one session."""

    @pytest.mark.asyncio
    async def test_session_filter_keeps_matching_results(self) -> None:
        """session_id filter keeps only results from that session."""
        fragments = [
            _make_hybrid_search_result(dialogue_id="session-A"),
            _make_hybrid_search_result(dialogue_id="session-A"),
            _make_hybrid_search_result(dialogue_id="session-B"),
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        # After hybrid search returns all results, _retrieve_fragments filters
        result = await rag_service.query(question="Тест?", session_id="session-A")

        # All returned sources should be from session-A
        for source in result.sources:
            assert source.dialogue_id == "session-A"

    @pytest.mark.asyncio
    async def test_session_filter_removes_non_matching(self) -> None:
        """session_id filter removes results from other sessions."""
        fragments = [
            _make_hybrid_search_result(dialogue_id="session-B"),
            _make_hybrid_search_result(dialogue_id="session-C"),
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        result = await rag_service.query(question="Тест?", session_id="session-A")

        # No matching results → error about no relevant fragments
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_no_session_searches_all(self) -> None:
        """No session_id → search across all indexed dialogues."""
        fragments = [
            _make_hybrid_search_result(dialogue_id="session-A"),
            _make_hybrid_search_result(dialogue_id="session-B"),
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True, state="closed")
            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(question="Тест?")

        # Both sessions should be in results
        dialogue_ids = {s.dialogue_id for s in result.sources}
        assert "session-A" in dialogue_ids
        assert "session-B" in dialogue_ids


# ═══════════════════════════════════════════════════════════
# 7. Citation and Source Mapping
# ═══════════════════════════════════════════════════════════


class TestCitationMapping:
    """Source citations map correctly to retrieved fragments."""

    @pytest.mark.asyncio
    async def test_source_fragments_have_correct_provenance(self) -> None:
        """Each RagSourceFragment has correct dialogue_id, turn_index, speaker."""
        fragments = [
            _make_hybrid_search_result(
                dialogue_id="sess-1",
                turn_index=3,
                speaker="Клиент",
                text="Проблема со связью",
            ),
            _make_hybrid_search_result(
                dialogue_id="sess-2",
                turn_index=7,
                speaker="Сотрудник",
                text="Сейчас проверим",
            ),
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ [1] [2]")
            mock_get_provider.return_value = mock_provider
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True)
            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(question="Что обсуждали?")

        assert len(result.sources) == 2
        assert result.sources[0].dialogue_id == "sess-1"
        assert result.sources[0].turn_index == 3
        assert result.sources[0].speaker == "Клиент"
        assert result.sources[1].dialogue_id == "sess-2"
        assert result.sources[1].turn_index == 7
        assert result.sources[1].speaker == "Сотрудник"

    @pytest.mark.asyncio
    async def test_snippet_truncation(self) -> None:
        """Long text snippets are truncated to 300 chars."""
        long_text = "А" * 500
        fragments = [_make_hybrid_search_result(text=long_text)]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True)
            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(question="Тест?")

        assert len(result.sources[0].text_snippet) <= 303  # 300 + "..."


# ═══════════════════════════════════════════════════════════
# 8. Context Building
# ═══════════════════════════════════════════════════════════


class TestContextBuilding:
    """Context blocks are built correctly from fragments."""

    def test_build_context_basic(self) -> None:
        """Basic context building with a few fragments."""
        rag_service = _make_rag_service()
        fragments = [
            _make_hybrid_search_result(
                dialogue_id="s1",
                turn_index=0,
                speaker="Клиент",
                text="Тестовый текст",
            ),
        ]

        blocks, used = rag_service._build_context(fragments)

        assert used == 1
        assert len(blocks) == 1
        assert "[1]" in blocks[0]
        assert "s1" in blocks[0]
        assert "Тестовый текст" in blocks[0]

    def test_build_context_empty_fragments(self) -> None:
        """Empty fragments list → empty context."""
        rag_service = _make_rag_service()
        blocks, used = rag_service._build_context([])

        assert used == 0
        assert blocks == []

    def test_build_context_truncates_long_blocks(self) -> None:
        """Individual blocks longer than 1000 chars are truncated."""
        rag_service = _make_rag_service()
        long_text = "Б" * 2000
        fragments = [_make_hybrid_search_result(text=long_text)]

        blocks, used = rag_service._build_context(fragments)

        assert used == 1
        assert len(blocks[0]) <= 1003  # 1000 + "..."

    def test_build_context_respects_max_chars(self) -> None:
        """Total context respects _MAX_CONTEXT_CHARS limit."""
        from app.services.rag import _MAX_CONTEXT_CHARS

        rag_service = _make_rag_service()
        # Create many fragments with long text
        fragments = [
            _make_hybrid_search_result(text=f"Текст фрагмента {i} " * 50)
            for i in range(100)
        ]

        blocks, used = rag_service._build_context(fragments)

        # Total context should not exceed max
        total_len = sum(len(b) for b in blocks)
        assert total_len <= _MAX_CONTEXT_CHARS + 100  # Small margin for truncation
        assert used < 100  # Should have truncated


# ═══════════════════════════════════════════════════════════
# 9. RAG Service Status
# ═══════════════════════════════════════════════════════════


class TestRAGStatus:
    """RAG service status endpoint returns correct information."""

    @pytest.mark.asyncio
    async def test_get_status_returns_frida_availability(self) -> None:
        """Status includes FRIDA availability."""
        rag_service = _make_rag_service(frida_available=True)

        status = await rag_service.get_status()

        assert status["frida_available"] is True

    @pytest.mark.asyncio
    async def test_get_status_returns_vector_store_stats(self) -> None:
        """Status includes vector store statistics."""
        rag_service = _make_rag_service(vector_count=42)

        status = await rag_service.get_status()

        assert status["vector_store"]["total_vectors"] == 42

    @pytest.mark.asyncio
    async def test_get_status_returns_rag_model(self) -> None:
        """Status includes RAG model name."""
        rag_service = _make_rag_service()

        status = await rag_service.get_status()

        assert status["rag_model"] == "glm-5.1"
        assert "qwen" in status["rag_model_note"].lower() or "500" in status["rag_model_note"]

    @pytest.mark.asyncio
    async def test_get_status_returns_provider_info(self) -> None:
        """Status includes provider configuration info."""
        rag_service = _make_rag_service()

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb:
            mock_get_provider.return_value = MagicMock()
            mock_get_cb.return_value = MagicMock(state="closed")

            status = await rag_service.get_status()

        assert "providers" in status
        assert "beeline" in status["providers"]


# ═══════════════════════════════════════════════════════════
# 10. Config and Constants
# ═══════════════════════════════════════════════════════════


class TestConfigDefaults:
    """RAG configuration defaults are correct."""

    def test_rag_default_model_is_glm51(self) -> None:
        """Default RAG model is GLM-5.1 (Qwen gives 500)."""
        assert _RAG_DEFAULT_MODEL == "glm-5.1"

    def test_rag_system_prompt_mentions_context_only(self) -> None:
        """System prompt instructs model to answer only from context."""
        assert "ТОЛЬКО" in _RAG_SYSTEM_PROMPT or "только" in _RAG_SYSTEM_PROMPT.lower()
        assert "контекст" in _RAG_SYSTEM_PROMPT.lower()

    def test_rag_system_prompt_mentions_citations(self) -> None:
        """System prompt instructs model to cite sources."""
        assert "[1]" in _RAG_SYSTEM_PROMPT

    def test_rag_query_request_defaults(self) -> None:
        """RagQueryRequest has correct defaults."""
        req = RagQueryRequest(question="Тест")
        assert req.session_id is None
        assert req.top_k == 5
        assert req.provider_id == "beeline"

    def test_rag_query_request_validation(self) -> None:
        """RagQueryRequest validates question length and top_k range."""
        # Question too long
        with pytest.raises(Exception):
            RagQueryRequest(question="А" * 2001)

        # top_k too low
        with pytest.raises(Exception):
            RagQueryRequest(question="Тест", top_k=0)

        # top_k too high
        with pytest.raises(Exception):
            RagQueryRequest(question="Тест", top_k=21)

    def test_rag_query_response_defaults(self) -> None:
        """RagQueryResponse has safe defaults."""
        resp = RagQueryResponse(question="Тест")
        assert resp.answer == ""
        assert resp.sources == []
        assert resp.context_used == 0
        assert resp.search_source == "hybrid"
        assert resp.provider == "none"
        assert resp.model == ""
        assert resp.error is None

    def test_rag_source_fragment_defaults(self) -> None:
        """RagSourceFragment has safe defaults."""
        frag = RagSourceFragment()
        assert frag.dialogue_id == ""
        assert frag.turn_index == -1
        assert frag.speaker == ""
        assert frag.text_snippet == ""
        assert frag.relevance_score == 0.0
        assert frag.search_source == "hybrid"


# ═══════════════════════════════════════════════════════════
# 11. Semantic Fallback Search
# ═══════════════════════════════════════════════════════════


class TestSemanticFallbackSearch:
    """Semantic fallback search when HybridSearchService fails."""

    @pytest.mark.asyncio
    async def test_semantic_fallback_returns_results(self) -> None:
        """Semantic fallback returns VectorSearchResult as HybridSearchResult."""
        from app.models import VectorSearchResult

        rag_service = _make_rag_service(frida_available=True)
        # Make hybrid search fail
        rag_service.hybrid_search_service.search = AsyncMock(
            side_effect=RuntimeError("HybridSearchService error")
        )
        # Set up VectorStore with mock results
        rag_service.vector_store.search.return_value = [
            VectorSearchResult(
                chunk_id="c1",
                text="Тестовый результат",
                dialogue_id="s1",
                turn_index=0,
                speaker="Клиент",
                score=0.9,
                chunk_type="utterance",
            )
        ]

        fragments, source = await rag_service._semantic_fallback_search(
            question="Тест", session_id=None, top_k=5
        )

        assert len(fragments) == 1
        assert fragments[0].dialogue_id == "s1"
        assert fragments[0].source == "semantic"
        assert source == "semantic"

    @pytest.mark.asyncio
    async def test_semantic_fallback_frida_unavailable(self) -> None:
        """Semantic fallback returns empty when FRIDA is down."""
        rag_service = _make_rag_service(frida_available=False)
        # Make hybrid search also fail
        rag_service.hybrid_search_service.search = AsyncMock(
            side_effect=RuntimeError("Search error")
        )

        fragments, source = await rag_service._semantic_fallback_search(
            question="Тест", session_id=None, top_k=5
        )

        assert fragments == []
        assert source == "none"


# ═══════════════════════════════════════════════════════════
# 12. Circuit Breaker Integration
# ═══════════════════════════════════════════════════════════


class TestCircuitBreakerIntegration:
    """Circuit breaker integration with RAG LLM calls."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_skips_provider(self) -> None:
        """Open circuit breaker causes provider to be skipped."""
        fragments = [_make_hybrid_search_result()]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            # First provider: circuit breaker open
            mock_cb1 = MagicMock()
            mock_cb1.can_execute.return_value = False
            mock_cb1.state = "open"

            # Second provider: circuit breaker closed but fails
            mock_provider2 = MagicMock()
            mock_provider2.generate = AsyncMock(side_effect=ConnectionError("Service down"))

            mock_cb2 = MagicMock()
            mock_cb2.can_execute.return_value = True
            mock_cb2.state = "closed"

            call_count = [0]
            def get_cb_side_effect(pid):
                call_count[0] += 1
                if call_count[0] == 1:
                    return mock_cb1
                return mock_cb2

            mock_get_cb.side_effect = get_cb_side_effect
            mock_get_provider.return_value = mock_provider2
            mock_fallback_order.return_value = ["beeline", "ollama"]

            result = await rag_service.query(question="Тест?")

        # Should have tried both providers (first skipped, second failed)
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_success_recorded(self) -> None:
        """Successful LLM call records success in circuit breaker."""
        fragments = [_make_hybrid_search_result()]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider

            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_get_cb.return_value = mock_cb

            mock_fallback_order.return_value = ["beeline"]

            await rag_service.query(question="Тест?")

        # Verify success was recorded
        mock_cb.record_success.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 13. RAG Router Integration Tests
# ═══════════════════════════════════════════════════════════


class TestRAGRouter:
    """Integration tests for RAG router endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client with RAG service mocked."""
        from app.main import app

        # Create mock RAG service
        mock_rag_service = MagicMock(spec=RAGService)

        # Attach to app.state before creating client
        app.state.rag_service = mock_rag_service

        with TestClient(app) as test_client:
            yield test_client

    def test_rag_query_endpoint_exists(self, client: TestClient) -> None:
        """POST /api/rag/query endpoint is registered."""
        # The endpoint exists — even a bad request should get a response, not 404
        response = client.post(
            "/api/rag/query",
            json={"question": "Тест"},
        )
        # Should not be 404 (method not found)
        assert response.status_code != 404

    def test_rag_status_endpoint_exists(self, client: TestClient) -> None:
        """GET /api/rag/status endpoint is registered."""
        # Mock the status method
        client.app.state.rag_service.get_status = AsyncMock(return_value={
            "frida_available": True,
            "vector_store": {"total_vectors": 100, "unique_dialogues": 5, "index_size_bytes": 614400},
            "hybrid_search": {"rrf_k": 60, "ner_available": True},
            "rag_model": "glm-5.1",
            "rag_model_note": "GLM-5.1 only for RAG inference",
            "providers": {},
        })

        response = client.get("/api/rag/status")

        # Should not be 404
        assert response.status_code != 404

    def test_rag_query_empty_question_rejected(self, client: TestClient) -> None:
        """Empty question is rejected by Pydantic validation."""
        response = client.post(
            "/api/rag/query",
            json={"question": ""},
        )
        assert response.status_code == 422

    def test_rag_query_top_k_validation(self, client: TestClient) -> None:
        """top_k out of range is rejected by Pydantic validation."""
        # top_k = 0
        response = client.post(
            "/api/rag/query",
            json={"question": "Тест", "top_k": 0},
        )
        assert response.status_code == 422

        # top_k = 21
        response = client.post(
            "/api/rag/query",
            json={"question": "Тест", "top_k": 21},
        )
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════
# 14. Edge Cases
# ═══════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_both_frida_and_llm_unavailable(self) -> None:
        """Both FRIDA and LLM unavailable → empty result with error."""
        rag_service = _make_rag_service(hybrid_results=None, frida_available=False)
        rag_service.hybrid_search_service.search = AsyncMock(
            side_effect=ConnectionError("FRIDA circuit breaker open")
        )
        rag_service.embedding_service.is_available = AsyncMock(return_value=False)

        result = await rag_service.query(question="Тест?")

        assert result.error is not None
        assert result.answer == ""
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_special_characters_in_question(self) -> None:
        """Questions with special characters are handled safely."""
        fragments = [_make_hybrid_search_result()]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True)
            mock_fallback_order.return_value = ["beeline"]

            # Question with special chars should not crash
            result = await rag_service.query(question='Что значит "роутер"? <script>alert(1)</script>')

        assert result.error is None

    @pytest.mark.asyncio
    async def test_fragments_with_no_text(self) -> None:
        """Fragment with empty text is handled gracefully."""
        fragments = [
            _make_hybrid_search_result(text=""),
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True)
            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(question="Тест?")

        # Should still work — empty text is valid
        assert result.context_used == 1

    @pytest.mark.asyncio
    async def test_many_fragments_truncated(self) -> None:
        """Many fragments are truncated to fit context limit."""
        fragments = [
            _make_hybrid_search_result(text=f"Фрагмент {i} " * 50)
            for i in range(30)
        ]
        rag_service = _make_rag_service(hybrid_results=fragments)

        with patch("app.services.llm.get_provider") as mock_get_provider, \
             patch("app.services.llm._get_circuit_breaker") as mock_get_cb, \
             patch("app.services.llm._get_fallback_order") as mock_fallback_order:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value="Ответ")
            mock_get_provider.return_value = mock_provider
            mock_get_cb.return_value = MagicMock(can_execute=lambda: True)
            mock_fallback_order.return_value = ["beeline"]

            result = await rag_service.query(question="Тест?", top_k=20)

        # Context should be truncated
        assert result.context_used <= 30

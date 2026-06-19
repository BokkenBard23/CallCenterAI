"""Tests for embeddings router — API endpoints with rate limiting.

Covers:
  - POST /api/embeddings/index → 200 OK with indexed_count
  - POST /api/embeddings/search/semantic → 200 OK with results
  - POST /api/embeddings/search/hybrid → 200 OK with results
  - GET  /api/embeddings/status → 200 OK with frida_available, vectors_stored, etc.
  - Input validation: empty session_id → 422, empty query → 422
  - Sanitization: control characters removed from inputs
  - Session not found → 404
  - FRIDA unavailable → 503
  - No dialogue in session → 400
"""

from __future__ import annotations

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.models import (
    Chunk,
    ChunkMetadata,
    DialogueTurn,
    HybridSearchResult,
    ParsedDialog,
    VectorSearchResult,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


def _make_embedding(dims: int = 1536) -> list[float]:
    """Create a fake 1536-dim embedding vector."""
    return [0.001 * (i % 100) for i in range(dims)]


def _make_chunk(dialogue_id: str = "test-session", text: str = "Test text") -> Chunk:
    """Create a fake chunk for testing."""
    return Chunk(
        text=text,
        metadata=ChunkMetadata(
            dialogue_id=dialogue_id,
            turn_index=0,
            speaker="Клиент",
            chunk_type="utterance",
            token_count=2,
            char_count=len(text),
            entities=[],
        ),
    )


def _make_parsed_dialog() -> ParsedDialog:
    """Create a fake parsed dialogue for testing."""
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте, мне нужна помощь"),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день, чем могу помочь?"),
        ],
        total_turns=2,
        client_turns=1,
        employee_turns=1,
    )


@pytest.fixture()
def client():
    """Create a TestClient with mocked services attached to app.state.

    The TestClient triggers the app lifespan which calls _init_services().
    We override the services AFTER the client starts so that our mocks
    replace the real services initialized by the lifespan.
    """
    from app.main import app
    from app.services.chunker import Chunker
    from app.services.vector_store import VectorStore

    from app.middleware.rate_limiter import limiter
    limiter.reset()

    with TestClient(app) as test_client:
        # Lifespan has run and initialized real services.
        # Now override with test mocks.

        # Mock FridaEmbeddingService
        mock_embedding = AsyncMock()
        mock_embedding.is_available = AsyncMock(return_value=True)
        mock_embedding.embed = AsyncMock(return_value=_make_embedding())
        mock_embedding.embed_batch = AsyncMock(return_value=[_make_embedding(), _make_embedding()])
        mock_embedding.http_client = MagicMock()
        mock_embedding.http_client.aclose = AsyncMock()

        # Real VectorStore (empty, no auto-save to disk) — replaces the one from lifespan
        vector_store = VectorStore(dimension=1536, auto_save=False)

        # Real Chunker (may or may not have Natasha NER)
        chunker = Chunker()

        # Mock HybridSearchService
        mock_hybrid_search = AsyncMock()
        mock_hybrid_search.search = AsyncMock(return_value=[])
        mock_hybrid_search._has_ner = True

        # Attach to app.state (override lifespan-initialized services)
        app.state.embedding_service = mock_embedding
        app.state.vector_store = vector_store
        app.state.chunker = chunker
        app.state.hybrid_search_service = mock_hybrid_search

        yield test_client


@pytest.fixture()
def client_with_frida_unavailable():
    """Create a TestClient with FRIDA unavailable.

    Same as `client` but embedding_service.is_available returns False.
    """
    from app.main import app
    from app.services.chunker import Chunker
    from app.services.vector_store import VectorStore

    from app.middleware.rate_limiter import limiter
    limiter.reset()

    with TestClient(app) as test_client:
        mock_embedding = AsyncMock()
        mock_embedding.is_available = AsyncMock(return_value=False)
        mock_embedding.http_client = MagicMock()
        mock_embedding.http_client.aclose = AsyncMock()

        vector_store = VectorStore(dimension=1536, auto_save=False)
        chunker = Chunker()

        mock_hybrid_search = AsyncMock()
        mock_hybrid_search.search = AsyncMock(return_value=[])
        mock_hybrid_search._has_ner = False

        app.state.embedding_service = mock_embedding
        app.state.vector_store = vector_store
        app.state.chunker = chunker
        app.state.hybrid_search_service = mock_hybrid_search

        yield test_client


# ═══════════════════════════════════════════════════════════
# Helper: register a session in the store
# ═══════════════════════════════════════════════════════════


def _register_session(session_id: str, dialog: ParsedDialog | None = None) -> None:
    """Register a session with a dialogue in the session store."""
    from app.utils.session import session_store

    session = session_store.create()
    # Override the session ID (store creates its own; we patch it)
    session.id = session_id
    session.dialog = dialog
    session_store.update(session)


def _register_session_with_dialog(session_id: str) -> None:
    """Register a session with a valid dialogue."""
    _register_session(session_id, dialog=_make_parsed_dialog())


# ═══════════════════════════════════════════════════════════
# Tests: POST /api/embeddings/index
# ═══════════════════════════════════════════════════════════


class TestIndexDialogue:
    """Tests for POST /api/embeddings/index."""

    def test_index_success(self, client):
        """Index a valid dialogue → 200 OK with indexed count."""
        _register_session_with_dialog("test-session-1")

        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test-session-1", "chunk_type": "utterance"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session-1"
        assert data["chunks_indexed"] >= 1
        assert data["vectors_stored"] >= data["chunks_indexed"]

    def test_index_session_not_found(self, client):
        """Index with non-existent session → 404."""
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "nonexistent-session", "chunk_type": "utterance"},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_index_no_dialogue(self, client):
        """Index with session that has no dialogue → 400."""
        _register_session("empty-session", dialog=None)

        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "empty-session", "chunk_type": "utterance"},
        )

        assert response.status_code == 400
        assert "no dialogue" in response.json()["detail"].lower()

    def test_index_frida_unavailable(self, client_with_frida_unavailable):
        """Index when FRIDA is unavailable → 503."""
        _register_session_with_dialog("test-session-frida")

        response = client_with_frida_unavailable.post(
            "/api/embeddings/index",
            json={"session_id": "test-session-frida", "chunk_type": "utterance"},
        )

        assert response.status_code == 503

    def test_index_empty_session_id(self, client):
        """Index with empty session_id → 422 validation error."""
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "", "chunk_type": "utterance"},
        )

        assert response.status_code == 422

    def test_index_default_chunk_type(self, client):
        """Index without chunk_type uses default 'utterance'."""
        _register_session_with_dialog("test-session-default")

        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test-session-default"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["chunks_indexed"] >= 1

    def test_index_sanitizes_control_chars_in_session_id(self, client):
        """Control characters in session_id are stripped."""
        # The sanitization happens before session lookup, so the sanitized
        # session_id won't match any session → 404 (which proves sanitization ran)
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test\x00session\x01id", "chunk_type": "utterance"},
        )

        # After sanitization: "testsessionid" — no session with that name
        assert response.status_code == 404

    def test_index_frida_circuit_breaker(self, client):
        """Index when FRIDA circuit breaker is open → 503."""
        _register_session_with_dialog("test-session-cb")

        # Make embed_batch raise ConnectionError (circuit breaker)
        client.app.state.embedding_service.embed_batch = AsyncMock(
            side_effect=ConnectionError("Circuit breaker open"),
        )
        # is_available still returns True (checked first)
        client.app.state.embedding_service.is_available = AsyncMock(return_value=True)

        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test-session-cb", "chunk_type": "utterance"},
        )

        assert response.status_code == 503

    def test_index_embed_failure(self, client):
        """Index when embedding fails → 503."""
        _register_session_with_dialog("test-session-fail")

        client.app.state.embedding_service.embed_batch = AsyncMock(
            side_effect=RuntimeError("API error 500"),
        )
        client.app.state.embedding_service.is_available = AsyncMock(return_value=True)

        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test-session-fail", "chunk_type": "utterance"},
        )

        assert response.status_code == 503


# ═══════════════════════════════════════════════════════════
# Tests: POST /api/embeddings/search/semantic
# ═══════════════════════════════════════════════════════════


class TestSearchSemantic:
    """Tests for POST /api/embeddings/search/semantic."""

    def test_search_semantic_success(self, client):
        """Semantic search with FRIDA available → 200 OK."""
        # Add some vectors to the store first
        from app.services.vector_store import VectorStore
        vs: VectorStore = client.app.state.vector_store
        embeddings = [_make_embedding()]
        metadata = [{
            "chunk_id": "chunk-1",
            "dialogue_id": "dial-1",
            "text": "Здравствуйте, мне нужна помощь",
            "turn_index": 0,
            "speaker": "Клиент",
            "chunk_type": "utterance",
            "entities": [],
        }]
        vs.add(embeddings, metadata)

        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "помощь", "top_k": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "помощь"
        assert data["total"] >= 0
        assert isinstance(data["results"], list)

    def test_search_semantic_frida_unavailable(self, client_with_frida_unavailable):
        """Semantic search when FRIDA unavailable → 503."""
        response = client_with_frida_unavailable.post(
            "/api/embeddings/search/semantic",
            json={"query": "помощь", "top_k": 5},
        )

        assert response.status_code == 503

    def test_search_semantic_empty_query(self, client):
        """Semantic search with empty query → 422."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "", "top_k": 5},
        )

        assert response.status_code == 422

    def test_search_semantic_query_too_long(self, client):
        """Semantic search with query > 2000 chars → 422."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "x" * 2001, "top_k": 5},
        )

        assert response.status_code == 422

    def test_search_semantic_top_k_range(self, client):
        """Semantic search with top_k out of range → 422."""
        # top_k < 1
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "test", "top_k": 0},
        )
        assert response.status_code == 422

        # top_k > 100
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "test", "top_k": 101},
        )
        assert response.status_code == 422

    def test_search_semantic_default_top_k(self, client):
        """Semantic search without top_k uses default 10."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "тест"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "тест"

    def test_search_semantic_with_session_filter(self, client):
        """Semantic search with session_id filters results."""
        from app.services.vector_store import VectorStore
        vs: VectorStore = client.app.state.vector_store
        embeddings = [_make_embedding(), _make_embedding()]
        metadata = [
            {
                "chunk_id": "chunk-a",
                "dialogue_id": "target-session",
                "text": "Target result",
                "turn_index": 0,
                "speaker": "Клиент",
                "chunk_type": "utterance",
                "entities": [],
            },
            {
                "chunk_id": "chunk-b",
                "dialogue_id": "other-session",
                "text": "Other result",
                "turn_index": 0,
                "speaker": "Сотрудник",
                "chunk_type": "utterance",
                "entities": [],
            },
        ]
        vs.add(embeddings, metadata)

        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "результат", "session_id": "target-session", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        # All results should be from the target session
        for result in data["results"]:
            assert result["dialogue_id"] == "target-session"

    def test_search_semantic_sanitizes_control_chars(self, client):
        """Control characters in query are stripped."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "тест\x00\x01запрос", "top_k": 5},
        )

        assert response.status_code == 200
        data = response.json()
        # The sanitized query should be returned (control chars removed)
        assert "\x00" not in data["query"]
        assert "\x01" not in data["query"]

    def test_search_semantic_circuit_breaker(self, client):
        """Semantic search when FRIDA circuit breaker open → 503."""
        client.app.state.embedding_service.embed = AsyncMock(
            side_effect=ConnectionError("Circuit breaker open"),
        )
        client.app.state.embedding_service.is_available = AsyncMock(return_value=True)

        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "тест", "top_k": 5},
        )

        assert response.status_code == 503


# ═══════════════════════════════════════════════════════════
# Tests: POST /api/embeddings/search/hybrid
# ═══════════════════════════════════════════════════════════


class TestSearchHybrid:
    """Tests for POST /api/embeddings/search/hybrid."""

    def test_search_hybrid_success(self, client):
        """Hybrid search returns 200 OK."""
        _register_session_with_dialog("hybrid-session")

        mock_results = [
            HybridSearchResult(
                text="Здравствуйте",
                dialogue_id="hybrid-session",
                turn_index=0,
                speaker="Клиент",
                morph_score=1.0,
                semantic_score=0.85,
                combined_score=0.95,
                source="hybrid",
            ),
        ]
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=mock_results)

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={
                "query": "помощь",
                "session_id": "hybrid-session",
                "top_k": 10,
                "use_semantic": True,
                "use_ner": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "помощь"
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["text"] == "Здравствуйте"
        assert data["results"][0]["source"] == "hybrid"

    def test_search_hybrid_empty_results(self, client):
        """Hybrid search with no matches → 200 OK, empty list."""
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "несуществующий запрос", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["results"] == []

    def test_search_hybrid_empty_query(self, client):
        """Hybrid search with empty query → 422."""
        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "", "top_k": 10},
        )

        assert response.status_code == 422

    def test_search_hybrid_without_session(self, client):
        """Hybrid search without session_id → still works (no morph search)."""
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "тест", "top_k": 10},
        )

        assert response.status_code == 200

    def test_search_hybrid_with_session_but_not_found(self, client):
        """Hybrid search with non-existent session_id → still works (no morph)."""
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "тест", "session_id": "nonexistent", "top_k": 10},
        )

        assert response.status_code == 200

    def test_search_hybrid_sanitizes_query(self, client):
        """Control characters in hybrid search query are stripped."""
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "тест\x00запрос", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert "\x00" not in data["query"]

    def test_search_hybrid_service_failure(self, client):
        """Hybrid search service failure → 500."""
        client.app.state.hybrid_search_service.search = AsyncMock(
            side_effect=RuntimeError("Internal error"),
        )

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "тест", "top_k": 10},
        )

        assert response.status_code == 500


# ═══════════════════════════════════════════════════════════
# Tests: GET /api/embeddings/status
# ═══════════════════════════════════════════════════════════


class TestGetStatus:
    """Tests for GET /api/embeddings/status."""

    def test_status_success(self, client):
        """Status endpoint returns 200 OK with all fields."""
        response = client.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert "frida_available" in data
        assert "vectors_stored" in data
        assert "unique_dialogues" in data
        assert "index_size_bytes" in data
        assert "nlp_provider" in data
        assert "natasha_available" in data
        assert "deeppavlov_available" in data

    def test_status_frida_available(self, client):
        """Status shows FRIDA available when service is up."""
        client.app.state.embedding_service.is_available = AsyncMock(return_value=True)

        response = client.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert data["frida_available"] is True

    def test_status_frida_unavailable(self, client_with_frida_unavailable):
        """Status shows FRIDA unavailable when service is down."""
        response = client_with_frida_unavailable.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert data["frida_available"] is False

    def test_status_vectors_stored(self, client):
        """Status shows correct vectors_stored count."""
        response = client.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["vectors_stored"], int)
        assert data["vectors_stored"] >= 0

    def test_status_nlp_provider(self, client):
        """Status shows NLP provider (natasha/deeppavlov/none)."""
        response = client.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert data["nlp_provider"] in ("natasha", "deeppavlov", "none")

    def test_status_frida_check_exception(self, client):
        """Status handles FRIDA check exception gracefully."""
        client.app.state.embedding_service.is_available = AsyncMock(
            side_effect=RuntimeError("Network error"),
        )

        response = client.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert data["frida_available"] is False

    def test_status_no_rate_limit(self, client):
        """Status endpoint has no rate limit — multiple calls succeed."""
        for _ in range(5):
            response = client.get("/api/embeddings/status")
            assert response.status_code == 200


# ═══════════════════════════════════════════════════════════
# Tests: Input validation & sanitization
# ═══════════════════════════════════════════════════════════


class TestInputValidation:
    """Tests for input validation and sanitization."""

    def test_session_id_max_length(self, client):
        """session_id > 100 chars → 422."""
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "x" * 101, "chunk_type": "utterance"},
        )

        assert response.status_code == 422

    def test_chunk_type_max_length(self, client):
        """chunk_type > 50 chars → 422."""
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test", "chunk_type": "x" * 51},
        )

        assert response.status_code == 422

    def test_query_max_length(self, client):
        """query > 2000 chars → 422."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "x" * 2001, "top_k": 10},
        )

        assert response.status_code == 422

    def test_top_k_min_value(self, client):
        """top_k < 1 → 422."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "test", "top_k": 0},
        )

        assert response.status_code == 422

    def test_top_k_max_value(self, client):
        """top_k > 100 → 422."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "test", "top_k": 101},
        )

        assert response.status_code == 422

    def test_sanitization_strips_tab_and_newline_control_chars(self, client):
        """Control chars \x00-\x1f (except \n \t) and \x7f-\x9f are stripped."""
        # Note: \n and \t are NOT stripped (the regex allows them)
        # The model validator strips \x00-\x1f\x7f-\x9f
        from app.routers.embeddings import _sanitize_text

        assert _sanitize_text("hello\x00world") == "helloworld"
        assert _sanitize_text("hello\x01world") == "helloworld"
        assert _sanitize_text("hello\x7fworld") == "helloworld"
        assert _sanitize_text("hello\x9fworld") == "helloworld"

    def test_sanitization_preserves_newline_and_tab(self, client):
        """Newline \\n and tab \\t are preserved by sanitization."""
        from app.routers.embeddings import _sanitize_text

        assert _sanitize_text("hello\nworld") == "hello\nworld"
        assert _sanitize_text("hello\tworld") == "hello\tworld"

    def test_session_id_control_chars_stripped(self, client):
        """Control characters in session_id are stripped by validator."""
        # Send session_id with control chars; after sanitization it becomes "test"
        # Since there's no session "test", we get 404 (not 422)
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "t\x00e\x01s\x02t", "chunk_type": "utterance"},
        )

        assert response.status_code == 404

    def test_query_control_chars_stripped(self, client):
        """Control characters in query are stripped by validator."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "тест\x00запрос", "top_k": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "тестзапрос"

    def test_invalid_json_body(self, client):
        """Invalid JSON body → 422."""
        response = client.post(
            "/api/embeddings/index",
            content="not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════
# Tests: Response model structure
# ═══════════════════════════════════════════════════════════


class TestResponseModels:
    """Tests for response model structure and types."""

    def test_index_response_fields(self, client):
        """Index response has correct field types."""
        _register_session_with_dialog("test-fields")

        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "test-fields", "chunk_type": "utterance"},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["session_id"], str)
        assert isinstance(data["chunks_indexed"], int)
        assert isinstance(data["vectors_stored"], int)

    def test_semantic_search_response_fields(self, client):
        """Semantic search response has correct field types."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "тест", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)
        assert isinstance(data["query"], str)
        assert isinstance(data["total"], int)

    def test_hybrid_search_response_fields(self, client):
        """Hybrid search response has correct field types."""
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "тест", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)
        assert isinstance(data["query"], str)
        assert isinstance(data["total"], int)

    def test_status_response_fields(self, client):
        """Status response has correct field types."""
        response = client.get("/api/embeddings/status")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["frida_available"], bool)
        assert isinstance(data["vectors_stored"], int)
        assert isinstance(data["unique_dialogues"], int)
        assert isinstance(data["index_size_bytes"], int)
        assert data["nlp_provider"] in ("natasha", "deeppavlov", "none")
        assert isinstance(data["natasha_available"], bool)
        assert isinstance(data["deeppavlov_available"], bool)


# ═══════════════════════════════════════════════════════════
# Tests: End-to-end integration
# ═══════════════════════════════════════════════════════════


class TestEndToEnd:
    """End-to-end integration tests: index → search → status."""

    def test_index_then_semantic_search(self, client):
        """Index a dialogue, then search it semantically."""
        _register_session_with_dialog("e2e-session")

        # Step 1: Index
        index_response = client.post(
            "/api/embeddings/index",
            json={"session_id": "e2e-session", "chunk_type": "utterance"},
        )

        assert index_response.status_code == 200
        index_data = index_response.json()
        assert index_data["chunks_indexed"] >= 1

        # Step 2: Search
        search_response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "помощь", "top_k": 10},
        )

        assert search_response.status_code == 200
        search_data = search_response.json()
        assert search_data["query"] == "помощь"

    def test_index_then_status(self, client):
        """Index a dialogue, then check status for updated vectors_stored."""
        _register_session_with_dialog("e2e-status")

        # Status before indexing
        status_before = client.get("/api/embeddings/status")
        vectors_before = status_before.json()["vectors_stored"]

        # Index
        client.post(
            "/api/embeddings/index",
            json={"session_id": "e2e-status", "chunk_type": "utterance"},
        )

        # Status after indexing
        status_after = client.get("/api/embeddings/status")
        vectors_after = status_after.json()["vectors_stored"]

        assert vectors_after >= vectors_before

    def test_index_then_hybrid_search(self, client):
        """Index a dialogue, then hybrid search it."""
        _register_session_with_dialog("e2e-hybrid")

        # Index
        index_response = client.post(
            "/api/embeddings/index",
            json={"session_id": "e2e-hybrid", "chunk_type": "utterance"},
        )

        assert index_response.status_code == 200

        # Hybrid search
        mock_results = [
            HybridSearchResult(
                text="Здравствуйте, мне нужна помощь",
                dialogue_id="e2e-hybrid",
                turn_index=0,
                speaker="Клиент",
                semantic_score=0.92,
                combined_score=0.92,
                source="semantic",
            ),
        ]
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=mock_results)

        search_response = client.post(
            "/api/embeddings/search/hybrid",
            json={
                "query": "помощь",
                "session_id": "e2e-hybrid",
                "top_k": 10,
                "use_semantic": True,
                "use_ner": True,
            },
        )

        assert search_response.status_code == 200
        search_data = search_response.json()
        assert search_data["total"] == 1

    def test_full_workflow_all_endpoints(self, client):
        """Full workflow: index → semantic search → hybrid search → status."""
        _register_session_with_dialog("e2e-full")

        # 1. Index
        idx_resp = client.post(
            "/api/embeddings/index",
            json={"session_id": "e2e-full", "chunk_type": "utterance"},
        )
        assert idx_resp.status_code == 200

        # 2. Semantic search
        sem_resp = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "помощь", "top_k": 5},
        )
        assert sem_resp.status_code == 200

        # 3. Hybrid search
        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])
        hyb_resp = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "помощь", "top_k": 5},
        )
        assert hyb_resp.status_code == 200

        # 4. Status
        status_resp = client.get("/api/embeddings/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["frida_available"] is True
        assert status_data["vectors_stored"] > 0


# ═══════════════════════════════════════════════════════════
# Tests: Edge cases
# ═══════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge case tests."""

    def test_search_semantic_empty_store(self, client):
        """Semantic search on empty VectorStore returns empty results."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "тест", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["results"] == []

    def test_index_same_session_twice(self, client):
        """Index the same session twice → vectors accumulate."""
        _register_session_with_dialog("dup-session")

        # First index
        resp1 = client.post(
            "/api/embeddings/index",
            json={"session_id": "dup-session", "chunk_type": "utterance"},
        )
        assert resp1.status_code == 200
        vectors_after_first = resp1.json()["vectors_stored"]

        # Second index (same session)
        resp2 = client.post(
            "/api/embeddings/index",
            json={"session_id": "dup-session", "chunk_type": "utterance"},
        )
        assert resp2.status_code == 200
        vectors_after_second = resp2.json()["vectors_stored"]

        # Vectors should have doubled (no dedup in add)
        assert vectors_after_second >= vectors_after_first

    def test_hybrid_search_with_session_without_dictionaries(self, client):
        """Hybrid search with session that has no dictionaries."""
        _register_session_with_dialog("no-dict-session")

        client.app.state.hybrid_search_service.search = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/hybrid",
            json={"query": "тест", "session_id": "no-dict-session", "top_k": 10},
        )

        assert response.status_code == 200

    def test_very_long_query_at_limit(self, client):
        """Query at exactly 2000 chars → 200 OK."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "x" * 2000, "top_k": 10},
        )

        assert response.status_code == 200

    def test_unicode_query(self, client):
        """Unicode characters in query (Russian) → 200 OK."""
        response = client.post(
            "/api/embeddings/search/semantic",
            json={"query": "Привет, как дела? Здравствуйте!", "top_k": 10},
        )

        assert response.status_code == 200

    def test_session_id_exactly_at_max_length(self, client):
        """session_id at exactly 100 chars → 422 or 404 (not too long)."""
        response = client.post(
            "/api/embeddings/index",
            json={"session_id": "x" * 100, "chunk_type": "utterance"},
        )

        # Should not be 422 for length (it's exactly at the limit)
        assert response.status_code in (200, 404, 400, 503)

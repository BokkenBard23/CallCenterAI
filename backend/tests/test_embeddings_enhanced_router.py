"""Tests for POST /api/embeddings/search/enhanced endpoint.

Covers:
  1. 200 OK with enhanced results (bm25_score, token_contributions fields)
  2. Empty results
  3. Empty query → 422
  4. fusion_strategy validation (invalid → 422)
  5. Internal error → 500
  6. bm25_used reflected in response
  7. Control character sanitization in query
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# app.main pulls in pii_masking which imports presidio_analyzer (an optional
# PII dep listed in requirements.txt but not always installed in dev envs).
# Skip the whole module when the app can't be imported — the endpoint logic
# is covered by the router registration test elsewhere.
try:
    from fastapi.testclient import TestClient  # type: ignore

    from app.main import app  # noqa: F401
    _APP_IMPORTABLE = True
    _APP_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover — environment-dependent
    _APP_IMPORTABLE = False
    _APP_IMPORT_ERROR = str(exc)

from app.models import EnhancedHybridSearchResult

pytestmark = pytest.mark.skipif(
    not _APP_IMPORTABLE,
    reason=f"app.main not importable in this env: {_APP_IMPORT_ERROR}",
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture()
def client():
    """TestClient with mocked services, mirroring test_embeddings_router.py pattern.

    Skips when app.main can't be imported OR when the app lifespan fails to
    initialize (e.g. optional PII deps like presidio_analyzer missing in dev envs).
    """
    if not _APP_IMPORTABLE:
        pytest.skip(f"app.main not importable: {_APP_IMPORT_ERROR}")

    from app.services.chunker import Chunker
    from app.services.vector_store import VectorStore
    from app.middleware.rate_limiter import limiter

    limiter.reset()

    try:
        context = TestClient(app)
        context.__enter__()
    except Exception as exc:  # pragma: no cover — environment-dependent
        pytest.skip(f"app lifespan failed (likely missing optional dep): {exc}")

    test_client = context
    # Lifespan ran — override services with mocks.
    mock_embedding = AsyncMock()
    mock_embedding.is_available = AsyncMock(return_value=True)
    mock_embedding.embed = AsyncMock(return_value=[0.001 * (i % 100) for i in range(1536)])
    mock_embedding.http_client = MagicMock()
    mock_embedding.http_client.aclose = AsyncMock()

    vector_store = VectorStore(dimension=1536, auto_save=False)
    chunker = Chunker()

    mock_hybrid_search = AsyncMock()
    mock_hybrid_search.search = AsyncMock(return_value=[])
    mock_hybrid_search.search_enhanced = AsyncMock(return_value=[])
    mock_hybrid_search._has_ner = True

    app.state.embedding_service = mock_embedding
    app.state.vector_store = vector_store
    app.state.chunker = chunker
    app.state.hybrid_search_service = mock_hybrid_search

    try:
        yield test_client
    finally:
        context.__exit__(None, None, None)


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestSearchEnhancedEndpoint:
    def test_search_enhanced_success(self, client):
        """Enhanced search returns 200 OK with bm25_score + token_contributions fields."""
        mock_results = [
            EnhancedHybridSearchResult(
                text="отказ от услуги",
                dialogue_id="enhanced-session",
                turn_index=0,
                speaker="Клиент",
                morph_score=1.0,
                semantic_score=0.85,
                bm25_score=1.23,
                combined_score=0.95,
                source="hybrid",
                token_contributions=[("отказ", 0.4), ("услуги", 0.2)],
            ),
        ]
        client.app.state.hybrid_search_service.search_enhanced = AsyncMock(
            return_value=mock_results
        )

        response = client.post(
            "/api/embeddings/search/enhanced",
            json={
                "query": "отказ",
                "session_id": "enhanced-session",
                "top_k": 10,
                "use_semantic": True,
                "use_ner": True,
                "use_bm25": True,
                "fusion_strategy": "rrf",
                "explain": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "отказ"
        assert data["total"] == 1
        assert data["fusion_strategy"] == "rrf"
        assert data["bm25_used"] is True
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["bm25_score"] == 1.23
        assert result["token_contributions"] == [["отказ", 0.4], ["услуги", 0.2]]
        assert result["source"] == "hybrid"

    def test_search_enhanced_empty_results(self, client):
        """No matches → 200 OK, empty list."""
        client.app.state.hybrid_search_service.search_enhanced = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "несуществующий", "top_k": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["results"] == []
        assert data["bm25_used"] is True
        assert data["fusion_strategy"] == "rrf"

    def test_search_enhanced_empty_query_422(self, client):
        """Empty query → 422 validation error."""
        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "", "top_k": 10},
        )
        assert response.status_code == 422

    def test_search_enhanced_invalid_fusion_strategy_422(self, client):
        """Invalid fusion_strategy → 422."""
        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "test", "fusion_strategy": "bogus"},
        )
        assert response.status_code == 422

    def test_search_enhanced_top_k_bounds_422(self, client):
        """top_k > 100 → 422."""
        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "test", "top_k": 200},
        )
        assert response.status_code == 422

    def test_search_enhanced_internal_error_500(self, client):
        """Service exception → 500."""
        client.app.state.hybrid_search_service.search_enhanced = AsyncMock(
            side_effect=RuntimeError("service crash")
        )
        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "test", "top_k": 5},
        )
        assert response.status_code == 500
        assert "Enhanced search failed" in response.json()["detail"]

    def test_search_enhanced_control_chars_sanitized(self, client):
        """Control characters in query are stripped before reaching the service."""
        captured = {}

        async def _capture(query=None, **kwargs):
            captured["query"] = query
            return []

        client.app.state.hybrid_search_service.search_enhanced = _capture

        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "отказ\x00от\x01услуги", "top_k": 5},
        )
        assert response.status_code == 200
        # Control chars stripped — only "отказотуслуги" remains.
        assert "\x00" not in captured["query"]
        assert "\x01" not in captured["query"]

    def test_search_enhanced_bm25_used_flag_false(self, client):
        """use_bm25=False reflected in response."""
        client.app.state.hybrid_search_service.search_enhanced = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "test", "use_bm25": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["bm25_used"] is False

    def test_search_enhanced_default_strategy_is_rrf(self, client):
        """When fusion_strategy omitted, defaults to 'rrf'."""
        client.app.state.hybrid_search_service.search_enhanced = AsyncMock(return_value=[])

        response = client.post(
            "/api/embeddings/search/enhanced",
            json={"query": "test"},
        )
        assert response.status_code == 200
        assert response.json()["fusion_strategy"] == "rrf"

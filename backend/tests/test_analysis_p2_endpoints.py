"""Tests for P2 analysis endpoints — /search (Phase 1) and /llm (Phase 2).

Verifies the P2 fix:
  - POST /api/analysis/search returns analysis_id + search_result, no LLM.
  - POST /api/analysis/llm updates the SAME analysis_id with llm_result.
  - After Phase 2, GET /api/analysis/results/{id} returns BOTH search_result
    AND llm_result — fixing the History reload bug.
  - SearchCache returns cache_hit=True on the second identical /search call.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    AnalysisResponse,
    DialogueTurn,
    LLMResult,
    ParsedDialog,
    SearchResult,
)
from app.services.search_cache import SearchCache


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def app_with_cache():
    """Build a FastAPI app with a fresh SearchCache attached to app.state."""
    from fastapi import FastAPI
    from app.routers import analysis
    from app.services.session_store_memory import MemorySessionStore
    from app.utils.session import session_store as _global_store

    # Use a fresh in-memory session store + cache
    fresh_store = MemorySessionStore()
    cache = SearchCache(max_entries=10, ttl_seconds=60)

    app = FastAPI()
    app.state.search_cache = cache
    app.state.session_store = fresh_store
    app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])

    # Monkey-patch the global session_store used by the analysis router.
    # The router imports `session_store` from app.utils.session at module level.
    # We patch it via the module attribute so the endpoints see the fresh store.
    from app.routers import analysis as analysis_module
    original_store = analysis_module.session_store
    analysis_module.session_store = fresh_store

    # Attach a method to register a session for tests
    def _register(session_id: str, dialog: ParsedDialog, dict_names: list[str] | None = None):
        from app.models import DictionaryCondition, DictionaryNode
        fresh_store.create(session_id)
        session = fresh_store.get(session_id)
        assert session is not None
        session.dialog = dialog
        if dict_names:
            for i, name in enumerate(dict_names):
                session.dictionaries[name] = DictionaryNode(
                    id=f"dict-{i}",
                    name=name,
                    conditions=[
                        DictionaryCondition(text="test phrase"),
                    ],
                    condition_count=1,
                )
        fresh_store.update(session)
        return session

    app._register = _register  # type: ignore[attr-defined]

    yield app, cache, fresh_store, _register

    # Restore
    analysis_module.session_store = original_store


@pytest.fixture
def client(app_with_cache):
    """TestClient for the app_with_cache fixture."""
    from fastapi.testclient import TestClient
    app, _cache, _store, _register = app_with_cache
    return TestClient(app)


def _make_dialog() -> ParsedDialog:
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(
                speaker="operator", text="Здравствуйте", turn_index=0,
                start_ms=0, end_ms=500,
            ),
            DialogueTurn(
                speaker="client", text="Здравствуйте, у меня вопрос", turn_index=1,
                start_ms=600, end_ms=1500,
            ),
        ],
    )


# ── Tests: /search (Phase 1) ─────────────────────────────────


class TestSearchEndpoint:
    def test_search_returns_analysis_id_and_search_result(self, client, app_with_cache):
        """POST /api/analysis/search returns analysis_id + search_result, no LLM."""
        app, _cache, _store, _register = app_with_cache
        _register("sess-1", _make_dialog(), dict_names=["dict-A"])

        # Mock run_hierarchical_search to return a known result
        fake_result = SearchResult(
            segments=[], total_matches=3, matches=[], matches_by_level={"1": 3},
        )
        with patch(
            "app.routers.analysis.run_hierarchical_search",
            new=AsyncMock(return_value=fake_result),
        ):
            response = client.post(
                "/api/analysis/search",
                json={"session_id": "sess-1", "dictionary_ids": ["dict-A"]},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert "analysis_id" in data
        assert len(data["analysis_id"]) > 0
        assert data["session_id"] == "sess-1"
        assert data["status"] == "completed"
        assert data["search_result"]["total_matches"] == 3
        assert data["cache_hit"] is False

    def test_search_returns_404_on_missing_session(self, client):
        response = client.post(
            "/api/analysis/search",
            json={"session_id": "nonexistent"},
        )
        assert response.status_code == 404

    def test_search_returns_400_on_missing_dialogue(self, client, app_with_cache):
        app, _cache, _store, _register = app_with_cache
        _register("sess-empty", None, dict_names=["dict-A"])

        response = client.post(
            "/api/analysis/search",
            json={"session_id": "sess-empty"},
        )
        assert response.status_code == 400

    def test_search_returns_400_on_missing_dictionaries(self, client, app_with_cache):
        app, _cache, _store, _register = app_with_cache
        _register("sess-no-dict", _make_dialog(), dict_names=None)

        response = client.post(
            "/api/analysis/search",
            json={"session_id": "sess-no-dict"},
        )
        assert response.status_code == 400

    def test_search_caches_result_on_second_call(self, client, app_with_cache):
        """Second identical /search call returns cache_hit=True and does NOT
        call run_hierarchical_search again."""
        app, _cache, _store, _register = app_with_cache
        _register("sess-cache", _make_dialog(), dict_names=["dict-A"])

        fake_result = SearchResult(
            segments=[], total_matches=2, matches=[], matches_by_level={"1": 2},
        )
        mock_search = AsyncMock(return_value=fake_result)
        with patch("app.routers.analysis.run_hierarchical_search", new=mock_search):
            # First call: cache miss
            r1 = client.post(
                "/api/analysis/search",
                json={"session_id": "sess-cache", "dictionary_ids": ["dict-A"]},
            )
            assert r1.status_code == 200
            assert r1.json()["cache_hit"] is False

            # Second call: cache hit
            r2 = client.post(
                "/api/analysis/search",
                json={"session_id": "sess-cache", "dictionary_ids": ["dict-A"]},
            )
            assert r2.status_code == 200
            assert r2.json()["cache_hit"] is True

        # run_hierarchical_search was called exactly ONCE
        assert mock_search.call_count == 1


# ── Tests: /llm (Phase 2) ───────────────────────────────────


class TestLLMEndpoint:
    def test_llm_updates_existing_analysis_with_llm_result(self, client, app_with_cache):
        """POST /api/analysis/llm attaches llm_result to the SAME analysis_id."""
        app, _cache, _store, _register = app_with_cache
        _register("sess-llm", _make_dialog(), dict_names=["dict-A"])

        # Phase 1: search
        fake_search = SearchResult(
            segments=[], total_matches=1, matches=[], matches_by_level={"1": 1},
        )
        with patch(
            "app.routers.analysis.run_hierarchical_search",
            new=AsyncMock(return_value=fake_search),
        ):
            r1 = client.post(
                "/api/analysis/search",
                json={"session_id": "sess-llm"},
            )
        analysis_id = r1.json()["analysis_id"]

        # Confirm Phase 1 has no llm_result yet
        r_get = client.get(f"/api/analysis/results/{analysis_id}")
        assert r_get.status_code == 200
        assert r_get.json()["llm_result"] is None

        # Phase 2: LLM — attach llm_result to the SAME analysis_id
        fake_llm = LLMResult(
            provider="beeline",
            model="test-model",
            summary="Это тестовая сводка диалога",
            restructured_dialogue="",
        )
        with patch(
            "app.routers.analysis.analyze_dialogue",
            new=AsyncMock(return_value=fake_llm),
        ):
            r2 = client.post(
                "/api/analysis/llm",
                json={
                    "analysis_id": analysis_id,
                    "llm_provider": "beeline",
                    "include_summary": True,
                },
            )

        assert r2.status_code == 200, r2.text
        llm_data = r2.json()
        # SAME analysis_id
        assert llm_data["analysis_id"] == analysis_id
        # llm_result is now attached
        assert llm_data["llm_result"] is not None
        assert llm_data["llm_result"]["summary"] == "Это тестовая сводка диалога"

        # Verify GET /results returns BOTH search_result AND llm_result now
        r_get2 = client.get(f"/api/analysis/results/{analysis_id}")
        assert r_get2.status_code == 200
        body = r_get2.json()
        assert body["search_result"]["total_matches"] == 1
        assert body["llm_result"]["summary"] == "Это тестовая сводка диалога"

    def test_llm_returns_404_on_missing_analysis(self, client):
        response = client.post(
            "/api/analysis/llm",
            json={
                "analysis_id": "nonexistent-id",
                "llm_provider": "beeline",
            },
        )
        assert response.status_code == 404

    def test_llm_status_endpoint_returns_analysis_state(self, client, app_with_cache):
        """GET /api/analysis/llm/{id}/status returns the current analysis state."""
        app, _cache, _store, _register = app_with_cache
        _register("sess-status", _make_dialog(), dict_names=["dict-A"])

        # Phase 1
        with patch(
            "app.routers.analysis.run_hierarchical_search",
            new=AsyncMock(return_value=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
            )),
        ):
            r1 = client.post(
                "/api/analysis/search",
                json={"session_id": "sess-status"},
            )
        analysis_id = r1.json()["analysis_id"]

        # Poll status before LLM
        r_status = client.get(f"/api/analysis/llm/{analysis_id}/status")
        assert r_status.status_code == 200
        status_body = r_status.json()
        assert status_body["analysis_id"] == analysis_id
        assert status_body["llm_result"] is None  # no LLM yet

    def test_llm_warning_on_provider_failure(self, client, app_with_cache):
        """If all LLM providers fail, status=partial and warning is set."""
        app, _cache, _store, _register = app_with_cache
        _register("sess-fail", _make_dialog(), dict_names=["dict-A"])

        with patch(
            "app.routers.analysis.run_hierarchical_search",
            new=AsyncMock(return_value=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
            )),
        ):
            r1 = client.post("/api/analysis/search", json={"session_id": "sess-fail"})
        analysis_id = r1.json()["analysis_id"]

        # LLM that returns provider='none' (all providers failed)
        degraded_llm = LLMResult(
            provider="none", model="", summary="", restructured_dialogue="",
        )
        with patch(
            "app.routers.analysis.analyze_dialogue",
            new=AsyncMock(return_value=degraded_llm),
        ):
            r2 = client.post(
                "/api/analysis/llm",
                json={
                    "analysis_id": analysis_id,
                    "llm_provider": "beeline",
                    "include_summary": True,
                },
            )
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"] == "partial"
        assert "LLM unavailable" in (body["warning"] or "")

    def test_llm_handles_analyze_dialogue_exception(self, client, app_with_cache):
        """If analyze_dialogue raises, /llm returns status=partial + warning."""
        app, _cache, _store, _register = app_with_cache
        _register("sess-exc", _make_dialog(), dict_names=["dict-A"])

        with patch(
            "app.routers.analysis.run_hierarchical_search",
            new=AsyncMock(return_value=SearchResult(
                segments=[], total_matches=0, matches=[], matches_by_level={},
            )),
        ):
            r1 = client.post("/api/analysis/search", json={"session_id": "sess-exc"})
        analysis_id = r1.json()["analysis_id"]

        with patch(
            "app.routers.analysis.analyze_dialogue",
            new=AsyncMock(side_effect=RuntimeError("LLM exploded")),
        ):
            r2 = client.post(
                "/api/analysis/llm",
                json={
                    "analysis_id": analysis_id,
                    "llm_provider": "beeline",
                    "include_summary": True,
                },
            )
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"] == "partial"
        assert "LLM analysis error" in (body["warning"] or "")


# ── Tests: update_analysis_llm() on session_store ────────────


class TestUpdateAnalysisLLM:
    def test_update_attaches_llm_to_existing_analysis(self, app_with_cache):
        """update_analysis_llm mutates the existing analysis record in-place."""
        _app, _cache, store, _register = app_with_cache
        _register("sess-update", _make_dialog(), dict_names=["dict-A"])

        # Insert an analysis with no LLM
        from app.models import AnalysisResponse
        original = AnalysisResponse(
            analysis_id="update-me",
            session_id="sess-update",
            status="completed",
            search_result=SearchResult(
                segments=[], total_matches=2, matches=[], matches_by_level={"1": 2},
            ),
            llm_result=None,
        )
        store.add_analysis("sess-update", original)

        new_llm = LLMResult(
            provider="beeline", model="m1",
            summary="updated summary", restructured_dialogue="",
        )
        updated = store.update_analysis_llm(
            analysis_id="update-me",
            llm_result=new_llm,
            status="completed",
        )

        assert updated is not None
        assert updated.analysis_id == "update-me"
        assert updated.llm_result is not None
        assert updated.llm_result.summary == "updated summary"

        # Verify via get_analysis that the same id now has llm_result
        reloaded = store.get_analysis("update-me")
        assert reloaded is not None
        assert reloaded.llm_result is not None
        assert reloaded.llm_result.summary == "updated summary"
        # And the original search_result is preserved
        assert reloaded.search_result is not None
        assert reloaded.search_result.total_matches == 2

    def test_update_returns_none_for_missing_analysis(self, app_with_cache):
        _app, _cache, store, _register = app_with_cache
        result = store.update_analysis_llm(
            analysis_id="does-not-exist",
            llm_result=None,
        )
        assert result is None

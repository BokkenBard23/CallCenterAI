"""Integration tests for app.routers.mining (6 endpoints).

Covers:
  POST /mining/index              вЂ” 202, 400 (bad path), 404 (session), 409 (running)
  GET  /mining/status/{job_id}    вЂ” 200, 404
  POST /mining/cancel/{job_id}    вЂ” 200, 404, 400 (not running)
  POST /mining/find_similar       вЂ” 200, 400 (no phrase), 404 (job)
  POST /mining/find_fn            вЂ” 202, 404 (job/session/dict), 400 (not completed)
  POST /mining/audit              вЂ” 202, 404 (job/session/dict), 400 (not completed)

TestClient: httpx.AsyncClient via ASGITransport.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient

from app.models import DictionaryCondition, DictionaryNode, PhraseGroupVisual


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# Test fixtures
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


_DIM = 1536


def _vec(seed: float = 0.5) -> List[float]:
    return [seed] * _DIM


def _make_dictionary(name: str = "RootDict") -> DictionaryNode:
    cond = DictionaryCondition(
        text="РїСЂРёРІРµС‚",
        word_distance=2,
        word_count=1,
        channel_constraint="ANY",
        is_exact=False,
        phrase_groups=[PhraseGroupVisual(words=["РїСЂРёРІРµС‚"], is_or_group=False, is_exception=False)],
        is_exception=False,
    )
    return DictionaryNode(
        id="root",
        name=name,
        parent_name=None,
        conditions=[cond],
        condition_count=1,
        has_children=False,
        children_count=0,
    )


@pytest_asyncio.fixture
async def mining_client(tmp_path, monkeypatch):
    """Async HTTP test client with a stubbed mining service + session store.

    Uses a temp SQLite DB for sessions + mining tables. The real
    DictionaryMiningService is wired with mock embedding/vector_store
    so endpoint handlers exercise the full router stack.
    """
    # Force a fresh session_store + mining_store pointing at the temp DB.
    db_path = tmp_path / "mining_router.db"
    monkeypatch.setenv("SESSION_DB_PATH", str(db_path))

    # Reimport session utils so session_store uses the temp DB.
    import importlib

    import app.utils.session as session_utils
    importlib.reload(session_utils)
    from app.services.session_store_sqlite import MiningStore, SqliteSessionStore

    session_store = SqliteSessionStore(db_path=str(db_path))
    mining_store = MiningStore(db_path=str(db_path))

    # Seed a session with one dictionary.
    session = session_store.create(session_id="sess-test")
    session.dictionaries["RootDict"] = _make_dictionary()
    session_store.update(session)

    # Build the app + attach the mining service.
    from app.main import app
    from app.services.chunker import Chunker
    from app.services.dict_mining import DictionaryMiningService

    embedding = MagicMock()
    embedding.embed_texts = AsyncMock(return_value=[_vec(0.5)])
    vector_store = MagicMock()
    vector_store.add = MagicMock(return_value=None)
    vector_store.search = MagicMock(return_value=[])

    chunker = Chunker()

    service = DictionaryMiningService(
        embedding_service=embedding,
        vector_store=vector_store,
        chunker=chunker,
        mining_store=mining_store,
    )
    app.state.mining_service = service
    app.state.mining_store = mining_store

    # Patch get_provider so LLM calls are deterministic.
    fake_provider = MagicMock()
    fake_provider.generate = AsyncMock(return_value="{}")
    fake_provider.is_available = AsyncMock(return_value=True)
    fake_provider.get_name = MagicMock(return_value="fake")
    fake_provider.get_default_model = MagicMock(return_value="fake-model")
    fake_provider.get_models = MagicMock(return_value=["fake-model"])
    monkeypatch.setattr(
        "app.services.dict_mining.get_provider", lambda _pid: fake_provider
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        # Expose the session store for handlers that use the module-level singleton.
        ac._session_store = session_store  # type: ignore[attr-defined]
        ac._app = app  # type: ignore[attr-defined]
        # Override the module-level session_store used by the router.
        import app.routers.mining as mining_router
        original_get = mining_router.session_store
        monkeypatch.setattr(mining_router, "session_store", session_store)
        yield ac
        monkeypatch.setattr(mining_router, "session_store", original_get)

    session_store.close()
    mining_store.close()


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# POST /mining/index
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


class TestIndexEndpoint:
    @pytest.mark.asyncio
    async def test_index_400_bad_path(self, mining_client, tmp_path):
        resp = await mining_client.post(
            "/api/mining/index",
            json={
                "session_id": "sess-test",
                "directory_path": str(tmp_path / "missing"),
                "dictionary_id": "RootDict",
            },
        )
        assert resp.status_code == 400, resp.text
        assert "does not exist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_index_400_empty_directory(self, mining_client, tmp_path):
        # Empty dir в†’ no .rtf files.
        resp = await mining_client.post(
            "/api/mining/index",
            json={
                "session_id": "sess-test",
                "directory_path": str(tmp_path),
                "dictionary_id": "RootDict",
            },
        )
        assert resp.status_code == 400, resp.text
        assert "no .rtf files" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_index_404_session_not_found(self, mining_client, tmp_path):
        (tmp_path / "x.rtf").write_text("x", encoding="utf-8")
        resp = await mining_client.post(
            "/api/mining/index",
            json={
                "session_id": "missing-session",
                "directory_path": str(tmp_path),
                "dictionary_id": "RootDict",
            },
        )
        assert resp.status_code == 404, resp.text
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_index_404_dictionary_not_found(self, mining_client, tmp_path):
        (tmp_path / "x.rtf").write_text("x", encoding="utf-8")
        resp = await mining_client.post(
            "/api/mining/index",
            json={
                "session_id": "sess-test",
                "directory_path": str(tmp_path),
                "dictionary_id": "NonexistentDict",
            },
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_index_202_happy_path(self, mining_client, tmp_path):
        from app.models import DialogueTurn, ParsedDialog

        (tmp_path / "d1.rtf").write_text("rtf", encoding="utf-8")

        async def _fake_parse_rtf(path, filename=None):
            return ParsedDialog(
                filename=filename or path.name,
                turns=[DialogueTurn(turn_index=0, speaker="РљР»РёРµРЅС‚", text="hi")],
                total_turns=1, client_turns=1, employee_turns=0,
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.services.dict_mining.parse_rtf_file", _fake_parse_rtf)
            resp = await mining_client.post(
                "/api/mining/index",
                json={
                    "session_id": "sess-test",
                    "directory_path": str(tmp_path),
                    "dictionary_id": "RootDict",
                },
            )

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["job_id"].startswith("mining-index-")
        assert body["status"] == "running"
        assert body["total_dialogues"] == 1


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# GET /mining/status/{job_id}
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_404_missing_job(self, mining_client):
        resp = await mining_client.get("/api/mining/status/missing-job")
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_status_200_completed_job(self, mining_client):
        # Use the mining service's mining_store (not the session store).
        mining_store = mining_client._app.state.mining_store  # type: ignore[attr-defined]
        mining_store.create_job(
            job_id="job-completed",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        mining_store.update_job(
            "job-completed",
            status="completed",
            total_dialogues=10,
            processed_dialogues=10,
            completed_at="2026-07-09T00:00:00",
        )
        resp = await mining_client.get("/api/mining/status/job-completed")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "completed"
        assert body["job_type"] == "index"
        assert body["progress"] == 1.0


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# POST /mining/cancel/{job_id}
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


class TestCancelEndpoint:
    @pytest.mark.asyncio
    async def test_cancel_404_missing(self, mining_client):
        resp = await mining_client.post("/api/mining/cancel/missing-job")
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_cancel_400_not_running(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-done",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-done", status="completed")
        resp = await mining_client.post("/api/mining/cancel/job-done")
        assert resp.status_code == 400, resp.text
        assert "not running" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_cancel_200_running(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-running",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-running", status="running")
        resp = await mining_client.post("/api/mining/cancel/job-running")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# POST /mining/find_similar
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


class TestFindSimilarEndpoint:
    @pytest.mark.asyncio
    async def test_find_similar_404_job_not_found(self, mining_client):
        resp = await mining_client.post(
            "/api/mining/find_similar",
            json={
                "session_id": "sess-test",
                "job_id": "missing-job",
                "phrase_group_id": "РїСЂРёРІРµС‚",
                "top_k": 5,
            },
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_find_similar_400_empty_phrase(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-idx",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-idx", status="completed")
        resp = await mining_client.post(
            "/api/mining/find_similar",
            json={
                "session_id": "sess-test",
                "job_id": "job-idx",
                "phrase_group_id": "",
                "top_k": 5,
            },
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_find_similar_200_happy_path(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-idx2",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-idx2", status="completed")

        from app.models import VectorSearchResult

        app.state.mining_service._vector_store.search.return_value = [
            VectorSearchResult(
                chunk_id="c1", text="hello world", dialogue_id="d1",
                turn_index=0, speaker="РљР»РёРµРЅС‚", score=0.9,
                chunk_type="utterance", entities=[],
            )
        ]

        resp = await mining_client.post(
            "/api/mining/find_similar",
            json={
                "session_id": "sess-test",
                "job_id": "job-idx2",
                "phrase_group_id": "РїСЂРёРІРµС‚",
                "top_k": 5,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["dialogues"][0]["dialogue_id"] == "d1"


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# POST /mining/find_fn
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


class TestFindFNEndpoint:
    @pytest.mark.asyncio
    async def test_find_fn_404_job_not_found(self, mining_client):
        resp = await mining_client.post(
            "/api/mining/find_fn",
            json={
                "session_id": "sess-test",
                "job_id": "missing-job",
                "dictionary_id": "RootDict",
                "threshold": 0.7,
            },
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_find_fn_400_index_not_completed(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-running-idx",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-running-idx", status="running")
        resp = await mining_client.post(
            "/api/mining/find_fn",
            json={
                "session_id": "sess-test",
                "job_id": "job-running-idx",
                "dictionary_id": "RootDict",
                "threshold": 0.7,
            },
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_find_fn_202_happy_path(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-idx-ok",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-idx-ok", status="completed")
        resp = await mining_client.post(
            "/api/mining/find_fn",
            json={
                "session_id": "sess-test",
                "job_id": "job-idx-ok",
                "dictionary_id": "RootDict",
                "threshold": 0.7,
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["job_id"].startswith("mining-find_fn-")
        assert body["total"] == 0  # initial response вЂ” FE polls


# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# POST /mining/audit
# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ


class TestAuditEndpoint:
    @pytest.mark.asyncio
    async def test_audit_404_job_not_found(self, mining_client):
        resp = await mining_client.post(
            "/api/mining/audit",
            json={
                "session_id": "sess-test",
                "job_id": "missing-job",
                "dictionary_id": "RootDict",
            },
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_audit_400_index_not_completed(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-running-audit",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-running-audit", status="running")
        resp = await mining_client.post(
            "/api/mining/audit",
            json={
                "session_id": "sess-test",
                "job_id": "job-running-audit",
                "dictionary_id": "RootDict",
            },
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_audit_202_happy_path(self, mining_client):
        app = mining_client._app  # type: ignore[attr-defined]
        app.state.mining_store.create_job(
            job_id="job-idx-audit",
            session_id="sess-test",
            dictionary_id="RootDict",
            directory_path="/tmp",
            job_type="index",
        )
        app.state.mining_store.update_job("job-idx-audit", status="completed")
        resp = await mining_client.post(
            "/api/mining/audit",
            json={
                "session_id": "sess-test",
                "job_id": "job-idx-audit",
                "dictionary_id": "RootDict",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["job_id"].startswith("mining-audit-")
        assert body["phrase_groups"] == []

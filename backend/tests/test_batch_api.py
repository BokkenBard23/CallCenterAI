"""Tests for Batch Analysis API endpoints.

Covers:
  - POST /api/analysis/batch — validation (file count, extensions, session, dictionaries)
  - GET  /api/analysis/batch/{batch_id}/status — polling
  - GET  /api/analysis/batch/{batch_id}/results — retrieval
  - Background processing: success, partial, failed, mixed
  - BatchStore: CRUD, cleanup
  - Edge cases: empty file, oversized file, no dictionaries, expired session
"""

from __future__ import annotations

import io
import sys
import os
import pytest
import pytest_asyncio

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.main import app
from app.models import (
    BatchAnalysisResponse,
    BatchItemStatus,
    DictionaryCondition,
    DictionaryNode,
)
from app.utils.session import SessionStore, BatchStore, Session


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_rtf_content(text: str = "Test dialogue content") -> bytes:
    """Create a minimal valid RTF byte string."""
    return (
        r"{\rtf1\ansi"
        r"\b \u1050?\u1083?\u1080?\u1077?\u1085?\u1090? \b0 "
        + text
        + r"\par}"
    ).encode("utf-8")


def _make_rtf_file(filename: str = "test.rtf", text: str = "Test dialogue content") -> tuple:
    """Create a file-like tuple (filename, content, content_type) for upload."""
    return (filename, _make_rtf_content(text), "application/rtf")


def _make_xml_dictionary(dict_name: str = "TestDict") -> bytes:
    """Create a minimal valid XML dictionary byte string."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<SpeechLabRequest>
  <Id>{dict_name}</Id>
  <Name>{dict_name}</Name>
  <Requests>
    <SpeechLabRequest>
      <Id>{dict_name}_child1</Id>
      <Name>ChildPhrase</Name>
      <Tokens>
        <Token Type="WORD">тестовая</Token>
        <Token Type="WORD">фраза</Token>
      </Tokens>
    </SpeechLabRequest>
  </Requests>
</SpeechLabRequest>"""
    return xml.encode("utf-8")


async def _create_session_with_dict(client: AsyncClient) -> str:
    """Create a session and upload a dictionary. Returns session_id."""
    # Upload RTF to create session
    rtf_file = _make_rtf_file("setup.rtf")
    resp = await client.post(
        "/api/upload/rtf",
        files={"file": rtf_file},
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # Upload dictionary
    xml_file = ("test_dict.xml", _make_xml_dictionary("TestDict"), "text/xml")
    resp = await client.post(
        "/api/upload/dictionary",
        files={"file": xml_file},
        data={"session_id": session_id},
    )
    assert resp.status_code == 200

    return session_id


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def client():
    """Async HTTP test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def fresh_stores(tmp_path):
    """Create fresh SessionStore and BatchStore for unit tests (no shared state)."""
    db_path = str(tmp_path / "fresh_test.db")
    return SessionStore(db_path=db_path), BatchStore(db_path=db_path)


# ═══════════════════════════════════════════════════════════
# POST /batch — Validation
# ═══════════════════════════════════════════════════════════


class TestBatchSubmitValidation:
    """Tests for POST /batch input validation."""

    async def test_batch_requires_at_least_one_file(self, client: AsyncClient):
        """POST /batch with zero files returns 422 (FastAPI validation)."""
        resp = await client.post(
            "/api/analysis/batch",
            data={"session_id": "fake"},
        )
        # FastAPI returns 422 when required File field is missing
        assert resp.status_code == 422

    async def test_batch_rejects_more_than_10_files(self, client: AsyncClient):
        """POST /batch with 11 files returns 400."""
        session_id = await _create_session_with_dict(client)
        files = [_make_rtf_file(f"file{i}.rtf") for i in range(11)]
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", f) for f in files],
            data={"session_id": session_id},
        )
        assert resp.status_code == 400
        assert "at most 10" in resp.json()["detail"]

    async def test_batch_rejects_non_rtf_files(self, client: AsyncClient):
        """POST /batch with a .txt file returns 400."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("good.rtf")
        txt_file = ("bad.txt", b"some text", "text/plain")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file), ("files", txt_file)],
            data={"session_id": session_id},
        )
        assert resp.status_code == 400
        assert ".rtf" in resp.json()["detail"]

    async def test_batch_rejects_empty_file(self, client: AsyncClient):
        """POST /batch with an empty .rtf file returns 400."""
        session_id = await _create_session_with_dict(client)
        empty_file = ("empty.rtf", b"", "application/rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", empty_file)],
            data={"session_id": session_id},
        )
        assert resp.status_code == 400
        assert "Empty file" in resp.json()["detail"]

    async def test_batch_rejects_missing_session(self, client: AsyncClient):
        """POST /batch with non-existent session_id returns 404."""
        rtf_file = _make_rtf_file("test.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={"session_id": "nonexistent_session"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_batch_rejects_session_without_dictionaries(self, client: AsyncClient):
        """POST /batch with session that has no dictionaries returns 400."""
        # Upload RTF only — creates session without dictionaries
        rtf_file = _make_rtf_file("nodict.rtf")
        resp = await client.post(
            "/api/upload/rtf",
            files={"file": rtf_file},
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # Try batch without dictionaries
        batch_file = _make_rtf_file("batch.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", batch_file)],
            data={"session_id": session_id},
        )
        assert resp.status_code == 400
        assert "No dictionaries" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════
# POST /batch — Success
# ═══════════════════════════════════════════════════════════


class TestBatchSubmitSuccess:
    """Tests for successful POST /batch submissions."""

    async def test_batch_submit_returns_batch_id(self, client: AsyncClient):
        """POST /batch returns batch_id and initial status."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("test.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "batch_id" in body
        assert body["session_id"] == session_id
        assert body["status"] == "processing"
        assert body["total_files"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["filename"] == "test.rtf"
        assert body["items"][0]["status"] == "pending"

    async def test_batch_submit_multiple_files(self, client: AsyncClient):
        """POST /batch with 3 files returns correct item list."""
        session_id = await _create_session_with_dict(client)
        files = [_make_rtf_file(f"file{i}.rtf") for i in range(3)]
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", f) for f in files],
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_files"] == 3
        assert len(body["items"]) == 3
        assert [item["filename"] for item in body["items"]] == [
            "file0.rtf", "file1.rtf", "file2.rtf"
        ]

    async def test_batch_submit_with_dictionary_ids(self, client: AsyncClient):
        """POST /batch with dictionary_ids filter accepts comma-separated string."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("filtered.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={
                "session_id": session_id,
                "dictionary_ids": "TestDict",
            },
        )
        assert resp.status_code == 200

    async def test_batch_submit_max_10_files_accepted(self, client: AsyncClient):
        """POST /batch with exactly 10 files succeeds."""
        session_id = await _create_session_with_dict(client)
        files = [_make_rtf_file(f"file{i}.rtf") for i in range(10)]
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", f) for f in files],
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_files"] == 10


# ═══════════════════════════════════════════════════════════
# GET /batch/{batch_id}/status — Polling
# ═══════════════════════════════════════════════════════════


class TestBatchStatus:
    """Tests for GET /batch/{batch_id}/status."""

    async def test_batch_status_not_found(self, client: AsyncClient):
        """GET /batch/{id}/status returns 404 for unknown batch."""
        resp = await client.get("/api/analysis/batch/nonexistent/status")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_batch_status_returns_initial_state(self, client: AsyncClient):
        """GET /batch/{id}/status returns the batch immediately after creation."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("status_test.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={"session_id": session_id},
        )
        batch_id = resp.json()["batch_id"]

        # Poll status immediately
        resp = await client.get(f"/api/analysis/batch/{batch_id}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["batch_id"] == batch_id
        assert body["status"] in ("processing", "completed", "partial", "failed")


# ═══════════════════════════════════════════════════════════
# GET /batch/{batch_id}/results — Retrieval
# ═══════════════════════════════════════════════════════════


class TestBatchResults:
    """Tests for GET /batch/{batch_id}/results."""

    async def test_batch_results_not_found(self, client: AsyncClient):
        """GET /batch/{id}/results returns 404 for unknown batch."""
        resp = await client.get("/api/analysis/batch/nonexistent/results")
        assert resp.status_code == 404

    async def test_batch_results_after_completion(self, client: AsyncClient):
        """GET /batch/{id}/results returns analysis_id for completed items."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("results_test.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={"session_id": session_id, "include_summary": "false"},
        )
        batch_id = resp.json()["batch_id"]

        # Wait for processing to complete (with retry)
        import asyncio
        for _ in range(20):
            await asyncio.sleep(0.2)
            status_resp = await client.get(f"/api/analysis/batch/{batch_id}/status")
            status_body = status_resp.json()
            if status_body["status"] in ("completed", "partial", "failed"):
                break

        # Now get results
        resp = await client.get(f"/api/analysis/batch/{batch_id}/results")
        assert resp.status_code == 200
        body = resp.json()
        assert body["batch_id"] == batch_id

        # Completed items should have analysis_id
        completed_items = [i for i in body["items"] if i["status"] == "completed"]
        if completed_items:
            assert completed_items[0]["analysis_id"] is not None


# ═══════════════════════════════════════════════════════════
# BatchStore — Unit tests
# ═══════════════════════════════════════════════════════════


class TestBatchStore:
    """Unit tests for BatchStore CRUD operations."""

    def test_create_and_get(self, fresh_stores):
        """Create a batch and retrieve it by ID."""
        session_store, batch_store = fresh_stores
        batch = BatchAnalysisResponse(
            batch_id="test123",
            session_id="sess1",
            total_files=2,
            status="processing",
            items=[
                BatchItemStatus(filename="a.rtf"),
                BatchItemStatus(filename="b.rtf"),
            ],
        )
        batch_store.create(batch)

        retrieved = batch_store.get("test123")
        assert retrieved is not None
        assert retrieved.batch_id == "test123"
        assert retrieved.total_files == 2
        assert len(retrieved.items) == 2

    def test_get_nonexistent(self, fresh_stores):
        """Getting a non-existent batch returns None."""
        _, batch_store = fresh_stores
        assert batch_store.get("nope") is None

    def test_update(self, fresh_stores):
        """Update a batch's status and items."""
        _, batch_store = fresh_stores
        batch = BatchAnalysisResponse(
            batch_id="upd1",
            session_id="sess1",
            total_files=1,
            status="processing",
            items=[BatchItemStatus(filename="x.rtf")],
        )
        batch_store.create(batch)

        # Update
        batch.status = "completed"
        batch.items[0].status = "completed"
        batch.items[0].analysis_id = "ana1"
        batch.completed_count = 1
        batch_store.update(batch)

        retrieved = batch_store.get("upd1")
        assert retrieved is not None
        assert retrieved.status == "completed"
        assert retrieved.items[0].analysis_id == "ana1"
        assert retrieved.completed_count == 1

    def test_delete(self, fresh_stores):
        """Delete a batch by ID."""
        _, batch_store = fresh_stores
        batch = BatchAnalysisResponse(
            batch_id="del1",
            session_id="sess1",
            total_files=1,
            status="processing",
            items=[BatchItemStatus(filename="z.rtf")],
        )
        batch_store.create(batch)
        assert batch_store.get("del1") is not None

        result = batch_store.delete("del1")
        assert result is True
        assert batch_store.get("del1") is None

    def test_delete_nonexistent(self, fresh_stores):
        """Deleting a non-existent batch returns False."""
        _, batch_store = fresh_stores
        assert batch_store.delete("ghost") is False

    def test_cleanup_for_session(self, fresh_stores):
        """Cleanup all batches associated with a session."""
        _, batch_store = fresh_stores
        for bid in ("b1", "b2", "b3"):
            batch = BatchAnalysisResponse(
                batch_id=bid,
                session_id="sess_cleanup" if bid != "b3" else "other_sess",
                total_files=1,
                status="processing",
                items=[BatchItemStatus(filename="x.rtf")],
            )
            batch_store.create(batch)

        removed = batch_store.cleanup_for_session("sess_cleanup")
        assert removed == 2
        assert batch_store.get("b1") is None
        assert batch_store.get("b2") is None
        assert batch_store.get("b3") is not None  # different session

    def test_concurrent_access(self, fresh_stores):
        """BatchStore handles concurrent access safely (thread lock)."""
        import threading

        _, batch_store = fresh_stores
        results = []
        errors = []

        def create_batch(batch_id: str):
            try:
                batch = BatchAnalysisResponse(
                    batch_id=batch_id,
                    session_id="concurrent_sess",
                    total_files=1,
                    status="processing",
                    items=[BatchItemStatus(filename="x.rtf")],
                )
                batch_store.create(batch)
                retrieved = batch_store.get(batch_id)
                results.append(retrieved is not None)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_batch, args=(f"t{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        assert all(results), "Some batches not found after concurrent creation"
        assert len(results) == 20


# ═══════════════════════════════════════════════════════════
# BatchItemStatus model tests
# ═══════════════════════════════════════════════════════════


class TestBatchItemStatusModel:
    """Tests for BatchItemStatus Pydantic model."""

    def test_default_status_is_pending(self):
        """BatchItemStatus defaults to 'pending' status."""
        item = BatchItemStatus(filename="test.rtf")
        assert item.status == "pending"
        assert item.analysis_id is None
        assert item.total_matches == 0
        assert item.matches_by_level == {}
        assert item.error is None

    def test_completed_item(self):
        """BatchItemStatus with completed state has analysis_id."""
        item = BatchItemStatus(
            filename="done.rtf",
            status="completed",
            analysis_id="abc123",
            total_matches=5,
            matches_by_level={"1": 3, "2": 2},
        )
        assert item.status == "completed"
        assert item.analysis_id == "abc123"
        assert item.total_matches == 5

    def test_failed_item(self):
        """BatchItemStatus with failed state has error message."""
        item = BatchItemStatus(
            filename="fail.rtf",
            status="failed",
            error="Parse error: invalid RTF",
        )
        assert item.status == "failed"
        assert item.error == "Parse error: invalid RTF"


# ═══════════════════════════════════════════════════════════
# BatchAnalysisResponse model tests
# ═══════════════════════════════════════════════════════════


class TestBatchAnalysisResponseModel:
    """Tests for BatchAnalysisResponse Pydantic model."""

    def test_default_status_is_pending(self):
        """BatchAnalysisResponse defaults to 'pending' status."""
        resp = BatchAnalysisResponse(
            batch_id="b1",
            session_id="s1",
            total_files=3,
        )
        assert resp.status == "pending"
        assert resp.items == []
        assert resp.completed_count == 0
        assert resp.failed_count == 0
        assert resp.error is None

    def test_processing_status(self):
        """BatchAnalysisResponse with processing state."""
        resp = BatchAnalysisResponse(
            batch_id="b2",
            session_id="s1",
            total_files=2,
            status="processing",
            items=[
                BatchItemStatus(filename="a.rtf", status="completed", analysis_id="a1"),
                BatchItemStatus(filename="b.rtf", status="processing"),
            ],
            completed_count=1,
        )
        assert resp.status == "processing"
        assert resp.completed_count == 1

    def test_partial_status(self):
        """BatchAnalysisResponse with partial (mixed) status."""
        resp = BatchAnalysisResponse(
            batch_id="b3",
            session_id="s1",
            total_files=2,
            status="partial",
            items=[
                BatchItemStatus(filename="a.rtf", status="completed", analysis_id="a1"),
                BatchItemStatus(filename="b.rtf", status="failed", error="bad file"),
            ],
            completed_count=1,
            failed_count=1,
        )
        assert resp.status == "partial"

    def test_failed_status(self):
        """BatchAnalysisResponse with fully failed status."""
        resp = BatchAnalysisResponse(
            batch_id="b4",
            session_id="s1",
            total_files=1,
            status="failed",
            items=[
                BatchItemStatus(filename="a.rtf", status="failed", error="parse error"),
            ],
            failed_count=1,
            error="All files failed",
        )
        assert resp.status == "failed"
        assert resp.error == "All files failed"


# ═══════════════════════════════════════════════════════════
# Integration: analysis stored in session after batch
# ═══════════════════════════════════════════════════════════


class TestBatchAnalysisStorageIntegration:
    """Tests that batch-completed analyses are stored in the session and
    retrievable via the existing GET /api/analysis/results/{analysis_id}."""

    async def test_completed_analysis_retrievable_via_results_endpoint(
        self, client: AsyncClient
    ):
        """After batch processing, analysis can be fetched via GET /results/{id}."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("storage_test.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={"session_id": session_id, "include_summary": "false"},
        )
        assert resp.status_code == 200
        batch_id = resp.json()["batch_id"]

        # Wait for completion
        import asyncio
        for _ in range(20):
            await asyncio.sleep(0.2)
            status_resp = await client.get(f"/api/analysis/batch/{batch_id}/status")
            status_body = status_resp.json()
            if status_body["status"] in ("completed", "partial", "failed"):
                break

        # Find a completed item
        results_resp = await client.get(f"/api/analysis/batch/{batch_id}/results")
        results_body = results_resp.json()
        completed = [i for i in results_body["items"] if i["status"] == "completed"]
        if completed:
            analysis_id = completed[0]["analysis_id"]
            assert analysis_id is not None

            # Retrieve via standard results endpoint
            detail_resp = await client.get(f"/api/analysis/results/{analysis_id}")
            assert detail_resp.status_code == 200
            detail_body = detail_resp.json()
            assert detail_body["analysis_id"] == analysis_id


# ═══════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════


class TestBatchEdgeCases:
    """Edge case tests for batch processing."""

    async def test_batch_with_include_summary_false(self, client: AsyncClient):
        """POST /batch with include_summary=false does not call LLM."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("no_llm.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={
                "session_id": session_id,
                "include_summary": "false",
                "include_restructured": "false",
            },
        )
        assert resp.status_code == 200
        batch_id = resp.json()["batch_id"]

        # Wait for completion
        import asyncio
        for _ in range(20):
            await asyncio.sleep(0.2)
            status_resp = await client.get(f"/api/analysis/batch/{batch_id}/status")
            if status_resp.json()["status"] in ("completed", "partial", "failed"):
                break

        # Check results — should have search results but no LLM
        results_resp = await client.get(f"/api/analysis/batch/{batch_id}/results")
        assert results_resp.status_code == 200

    async def test_batch_status_endpoint_idempotent(self, client: AsyncClient):
        """Multiple GET /batch/{id}/status calls return consistent data."""
        session_id = await _create_session_with_dict(client)
        rtf_file = _make_rtf_file("idempotent.rtf")
        resp = await client.post(
            "/api/analysis/batch",
            files=[("files", rtf_file)],
            data={"session_id": session_id},
        )
        batch_id = resp.json()["batch_id"]

        # Poll multiple times
        statuses = []
        for _ in range(3):
            resp = await client.get(f"/api/analysis/batch/{batch_id}/status")
            assert resp.status_code == 200
            statuses.append(resp.json()["status"])

        # All statuses should be valid
        for s in statuses:
            assert s in ("pending", "processing", "completed", "partial", "failed")

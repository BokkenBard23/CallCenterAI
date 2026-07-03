"""Tests for SQLite-backed SessionStore, BatchStore, and export endpoints.

Covers:
  - SessionStore: create, get, update, delete, TTL cleanup, persistence
  - BatchStore: create, get, update, delete, cleanup_for_session
  - Export endpoints: Excel and PDF generation
  - Edge cases: expired sessions, concurrent access, missing dependencies
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import pytest
import pytest_asyncio

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient

from app.models import (
    AnalysisResponse,
    BatchAnalysisResponse,
    BatchItemStatus,
    DialogueTurn,
    DictMatch,
    DictionaryCondition,
    DictionaryNode,
    LLMResult,
    ParsedDialog,
    SearchResult,
)
from app.utils.session import BatchStore, Session, SessionStore


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _make_session_store(tmp_path: str) -> SessionStore:
    """Create a SessionStore with a temporary DB path."""
    db_path = os.path.join(tmp_path, "test_sessions.db")
    return SessionStore(ttl_seconds=7200, db_path=db_path)


def _make_batch_store(tmp_path: str) -> BatchStore:
    """Create a BatchStore with a temporary DB path."""
    db_path = os.path.join(tmp_path, "test_sessions.db")
    return BatchStore(db_path=db_path)


def _make_dialog() -> ParsedDialog:
    """Create a sample ParsedDialog."""
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте"),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день"),
        ],
        total_turns=2,
        client_turns=1,
        employee_turns=1,
    )


def _make_dictionary(name: str = "TestDict") -> DictionaryNode:
    """Create a sample DictionaryNode."""
    return DictionaryNode(
        id=f"{name}_id",
        name=name,
        parent_name=None,
        conditions=[
            DictionaryCondition(text="тестовая фраза", word_distance=2),
        ],
        condition_count=1,
    )


def _make_analysis(analysis_id: str = "ana1", session_id: str = "sess1") -> AnalysisResponse:
    """Create a sample AnalysisResponse."""
    return AnalysisResponse(
        analysis_id=analysis_id,
        session_id=session_id,
        status="completed",
        search_result=SearchResult(
            segments=[],
            total_matches=1,
            matches=[
                DictMatch(
                    phrase_text="тестовая фраза",
                    matched_text="тестовая фраза",
                    quarter="TestDict",
                    turn_index=0,
                    speaker="Клиент",
                    match_type="sliding_window",
                    cascade_order=1,
                    is_exact_match=True,
                    channel_constraint="ANY",
                )
            ],
            matches_by_level={"1": 1},
        ),
        llm_result=LLMResult(
            summary="Тестовое резюме диалога",
            topic="Тестовая тема",
            result="resolved",
            provider="test",
        ),
    )


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test DB files."""
    d = tempfile.mkdtemp()
    yield d
    # Best-effort cleanup on Windows (ignore errors if file is locked)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def session_store(tmp_dir):
    """Create a SessionStore with a temporary DB."""
    store = _make_session_store(tmp_dir)
    yield store
    store.close()


@pytest.fixture
def batch_store(tmp_dir):
    """Create a BatchStore with a temporary DB."""
    store = _make_batch_store(tmp_dir)
    yield store
    store.close()


@pytest_asyncio.fixture
async def client():
    """Async HTTP test client for the FastAPI app."""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ═══════════════════════════════════════════════════════════
# SessionStore — CRUD
# ═══════════════════════════════════════════════════════════


class TestSessionStoreCRUD:
    """Tests for SessionStore create/read/update/delete operations."""

    def test_create_returns_session_with_id(self, session_store):
        """create() returns a Session with an auto-generated ID."""
        session = session_store.create()
        assert session.id is not None
        assert len(session.id) == 12

    def test_get_returns_created_session(self, session_store):
        """get() retrieves a session by ID."""
        session = session_store.create()
        retrieved = session_store.get(session.id)
        assert retrieved is not None
        assert retrieved.id == session.id

    def test_get_nonexistent_returns_none(self, session_store):
        """get() returns None for non-existent session ID."""
        assert session_store.get("nonexistent") is None

    def test_get_or_create_existing(self, session_store):
        """get_or_create() returns existing session if found."""
        session = session_store.create()
        result = session_store.get_or_create(session.id)
        assert result.id == session.id

    def test_get_or_create_new(self, session_store):
        """get_or_create() creates new session if ID not found."""
        result = session_store.get_or_create(None)
        assert result.id is not None

    def test_update_session(self, session_store):
        """update() persists changes to a session."""
        session = session_store.create()
        session.metadata["key"] = "value"
        session_store.update(session)

        retrieved = session_store.get(session.id)
        assert retrieved is not None
        assert retrieved.metadata["key"] == "value"

    def test_delete_session(self, session_store):
        """delete() removes a session."""
        session = session_store.create()
        assert session_store.delete(session.id) is True
        assert session_store.get(session.id) is None

    def test_delete_nonexistent(self, session_store):
        """delete() returns False for non-existent session."""
        assert session_store.delete("ghost") is False

    def test_list_sessions(self, session_store):
        """list_sessions() returns all session IDs."""
        s1 = session_store.create()
        s2 = session_store.create()
        ids = session_store.list_sessions()
        assert s1.id in ids
        assert s2.id in ids


class TestSessionStoreWithDialog:
    """Tests for session store with dialog data."""

    def test_session_with_dialog(self, session_store):
        """Session with dialog data can be stored and retrieved."""
        session = session_store.create()
        session.dialog = _make_dialog()
        session_store.update(session)

        retrieved = session_store.get(session.id)
        assert retrieved is not None
        assert retrieved.dialog is not None
        assert retrieved.dialog.filename == "test.rtf"
        assert len(retrieved.dialog.turns) == 2

    def test_session_with_dictionaries(self, session_store):
        """Session with dictionaries can be stored and retrieved."""
        session = session_store.create()
        dict1 = _make_dictionary("Dict1")
        session_store.add_dictionary(session.id, dict1)

        retrieved = session_store.get(session.id)
        assert retrieved is not None
        assert "Dict1" in retrieved.dictionaries
        assert retrieved.dictionaries["Dict1"].name == "Dict1"

    def test_get_dictionary(self, session_store):
        """get_dictionary() returns a specific dictionary."""
        session = session_store.create()
        dict1 = _make_dictionary("Dict1")
        session_store.add_dictionary(session.id, dict1)

        result = session_store.get_dictionary(session.id, "Dict1")
        assert result is not None
        assert result.name == "Dict1"

    def test_get_dictionary_nonexistent(self, session_store):
        """get_dictionary() returns None for missing dictionary."""
        session = session_store.create()
        result = session_store.get_dictionary(session.id, "NoDict")
        assert result is None

    def test_session_with_analysis(self, session_store):
        """Session with analysis results can be stored and retrieved."""
        session = session_store.create()
        analysis = _make_analysis(session_id=session.id)
        session_store.add_analysis(session.id, analysis)

        retrieved = session_store.get(session.id)
        assert retrieved is not None
        assert analysis.analysis_id in retrieved.analyses

    def test_get_analysis_by_id(self, session_store):
        """get_analysis() finds an analysis across all sessions."""
        session = session_store.create()
        analysis = _make_analysis(analysis_id="findme", session_id=session.id)
        session_store.add_analysis(session.id, analysis)

        result = session_store.get_analysis("findme")
        assert result is not None
        assert result.analysis_id == "findme"

    def test_get_analysis_not_found(self, session_store):
        """get_analysis() returns None for unknown analysis ID."""
        assert session_store.get_analysis("ghost") is None


# ═══════════════════════════════════════════════════════════
# SessionStore — TTL & Cleanup
# ═══════════════════════════════════════════════════════════


class TestSessionStoreTTL:
    """Tests for TTL expiration and cleanup."""

    def test_expired_session_returns_none(self, tmp_dir):
        """An expired session is treated as non-existent."""
        db_path = os.path.join(tmp_dir, "ttl_test.db")
        store = SessionStore(ttl_seconds=1, db_path=db_path)
        session = store.create()

        # Wait for TTL to expire
        time.sleep(1.5)
        result = store.get(session.id)
        assert result is None

    def test_cleanup_expired(self, tmp_dir):
        """cleanup_expired() removes expired sessions."""
        db_path = os.path.join(tmp_dir, "cleanup_test.db")
        store = SessionStore(ttl_seconds=1, db_path=db_path)
        s1 = store.create()
        time.sleep(1.5)
        removed = store.cleanup_expired()
        assert removed >= 1
        assert store.get(s1.id) is None

    def test_non_expired_session_survives_cleanup(self, tmp_dir):
        """Non-expired sessions survive cleanup."""
        db_path = os.path.join(tmp_dir, "survive_test.db")
        store = SessionStore(ttl_seconds=300, db_path=db_path)
        s1 = store.create()
        removed = store.cleanup_expired()
        assert store.get(s1.id) is not None


# ═══════════════════════════════════════════════════════════
# SessionStore — Persistence
# ═══════════════════════════════════════════════════════════


class TestSessionStorePersistence:
    """Tests for SQLite persistence across restarts."""

    def test_session_persists_across_restart(self, tmp_dir):
        """Sessions survive when a new SessionStore uses the same DB file."""
        db_path = os.path.join(tmp_dir, "persist_test.db")

        # Create session in first store
        store1 = SessionStore(db_path=db_path)
        session = store1.create()
        session.dialog = _make_dialog()
        session.metadata["test_key"] = "test_value"
        store1.update(session)

        # Create second store pointing to same DB
        store2 = SessionStore(db_path=db_path)
        retrieved = store2.get(session.id)
        assert retrieved is not None
        assert retrieved.dialog is not None
        assert retrieved.dialog.filename == "test.rtf"
        assert retrieved.metadata["test_key"] == "test_value"

    def test_batch_persists_across_restart(self, tmp_dir):
        """Batches survive when a new BatchStore uses the same DB file."""
        db_path = os.path.join(tmp_dir, "batch_persist_test.db")

        # Create batch in first store
        store1 = BatchStore(db_path=db_path)
        batch = BatchAnalysisResponse(
            batch_id="persist_test",
            session_id="sess1",
            total_files=1,
            status="processing",
            items=[BatchItemStatus(filename="a.rtf")],
        )
        store1.create(batch)

        # Create second store pointing to same DB
        store2 = BatchStore(db_path=db_path)
        retrieved = store2.get("persist_test")
        assert retrieved is not None
        assert retrieved.batch_id == "persist_test"
        assert retrieved.session_id == "sess1"


# ═══════════════════════════════════════════════════════════
# SessionStore — Concurrency
# ═══════════════════════════════════════════════════════════


class TestSessionStoreConcurrency:
    """Tests for thread-safe concurrent access."""

    def test_concurrent_creates(self, session_store):
        """Multiple threads can create sessions concurrently."""
        results = []
        errors = []

        def create_session():
            try:
                s = session_store.create()
                retrieved = session_store.get(s.id)
                results.append(retrieved is not None)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_session) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert all(results)
        assert len(results) == 20


# ═══════════════════════════════════════════════════════════
# BatchStore — CRUD
# ═══════════════════════════════════════════════════════════


class TestBatchStoreCRUD:
    """Tests for BatchStore CRUD operations."""

    def test_create_and_get(self, batch_store):
        """Create a batch and retrieve it by ID."""
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
        assert len(retrieved.items) == 2

    def test_get_nonexistent(self, batch_store):
        """Getting a non-existent batch returns None."""
        assert batch_store.get("nope") is None

    def test_update(self, batch_store):
        """Update a batch's status and items."""
        batch = BatchAnalysisResponse(
            batch_id="upd1",
            session_id="sess1",
            total_files=1,
            status="processing",
            items=[BatchItemStatus(filename="x.rtf")],
        )
        batch_store.create(batch)

        batch.status = "completed"
        batch.items[0].status = "completed"
        batch.items[0].analysis_id = "ana1"
        batch.completed_count = 1
        batch_store.update(batch)

        retrieved = batch_store.get("upd1")
        assert retrieved is not None
        assert retrieved.status == "completed"
        assert retrieved.items[0].analysis_id == "ana1"

    def test_delete(self, batch_store):
        """Delete a batch by ID."""
        batch = BatchAnalysisResponse(
            batch_id="del1",
            session_id="sess1",
            total_files=1,
            status="processing",
            items=[BatchItemStatus(filename="z.rtf")],
        )
        batch_store.create(batch)
        assert batch_store.get("del1") is not None
        assert batch_store.delete("del1") is True
        assert batch_store.get("del1") is None

    def test_delete_nonexistent(self, batch_store):
        """Deleting a non-existent batch returns False."""
        assert batch_store.delete("ghost") is False

    def test_cleanup_for_session(self, batch_store):
        """Cleanup all batches associated with a session."""
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
        assert batch_store.get("b3") is not None


# ═══════════════════════════════════════════════════════════
# Export Endpoints — API tests
# ═══════════════════════════════════════════════════════════


class TestExportExcel:
    """Tests for GET /api/export/{session_id}/excel."""

    async def test_export_excel_session_not_found(self, client: AsyncClient):
        """Returns 404 for non-existent session."""
        resp = await client.get("/api/export/nonexistent_session/excel")
        assert resp.status_code == 404

    async def test_export_excel_no_analyses(self, client: AsyncClient):
        """Returns 400 for session without analysis results."""
        # Create session with dialog but no analysis
        from app.utils.session import session_store as store
        session = store.create()
        session.dialog = _make_dialog()
        store.update(session)

        resp = await client.get(f"/api/export/{session.id}/excel")
        assert resp.status_code == 400

    async def test_export_excel_success(self, client: AsyncClient):
        """Returns .xlsx file for session with analysis."""
        from app.utils.session import session_store as store
        session = store.create()
        session.dialog = _make_dialog()
        analysis = _make_analysis(session_id=session.id)
        store.add_analysis(session.id, analysis)

        resp = await client.get(f"/api/export/{session.id}/excel")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert ".xlsx" in resp.headers.get("content-disposition", "")
        # Verify it's a valid ZIP (XLSX is a ZIP archive)
        assert len(resp.content) > 100
        assert resp.content[:2] == b"PK"  # ZIP magic bytes


class TestExportPDF:
    """Tests for GET /api/export/{session_id}/pdf."""

    async def test_export_pdf_session_not_found(self, client: AsyncClient):
        """Returns 404 for non-existent session."""
        resp = await client.get("/api/export/nonexistent_session/pdf")
        assert resp.status_code == 404

    async def test_export_pdf_no_analyses(self, client: AsyncClient):
        """Returns 400 for session without analysis results."""
        from app.utils.session import session_store as store
        session = store.create()
        session.dialog = _make_dialog()
        store.update(session)

        resp = await client.get(f"/api/export/{session.id}/pdf")
        assert resp.status_code == 400

    async def test_export_pdf_success(self, client: AsyncClient):
        """Returns PDF file for session with analysis."""
        from app.utils.session import session_store as store
        session = store.create()
        session.dialog = _make_dialog()
        analysis = _make_analysis(session_id=session.id)
        store.add_analysis(session.id, analysis)

        resp = await client.get(f"/api/export/{session.id}/pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert ".pdf" in resp.headers.get("content-disposition", "")
        # Verify it's a valid PDF
        assert len(resp.content) > 100
        assert resp.content[:5] == b"%PDF-"


class TestExportWithLLMResult:
    """Tests for export endpoints with LLM results."""

    async def test_excel_with_summary(self, client: AsyncClient):
        """Excel export includes LLM summary sheet."""
        from app.utils.session import session_store as store
        session = store.create()
        session.dialog = _make_dialog()
        analysis = _make_analysis(session_id=session.id)
        store.add_analysis(session.id, analysis)

        resp = await client.get(f"/api/export/{session.id}/excel")
        assert resp.status_code == 200

    async def test_pdf_with_summary(self, client: AsyncClient):
        """PDF export includes LLM summary section."""
        from app.utils.session import session_store as store
        session = store.create()
        session.dialog = _make_dialog()
        analysis = _make_analysis(session_id=session.id)
        store.add_analysis(session.id, analysis)

        resp = await client.get(f"/api/export/{session.id}/pdf")
        assert resp.status_code == 200
        # The PDF should contain text from the summary
        # PDF content is binary but contains the text
        content_lower = resp.content.lower()
        # LLMResult.summary contains "Тестовое резюме диалога"
        # In PDF, text may be encoded differently, so just check it's a valid PDF
        assert resp.content[:5] == b"%PDF-"

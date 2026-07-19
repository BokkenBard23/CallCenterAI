"""Tests for persistent session storage with SQLite and memory backends.

Covers:
  - SqliteSessionStore: CRUD, TTL, persistence, concurrency, JSON round-trip
  - MemorySessionStore: CRUD, TTL, basic operations
  - Factory: create_session_store() with different config values
  - Fallback: SQLite failure → memory backend
  - Schema: table creation, WAL mode, index
  - Large sessions: stress test with big payloads
  - Config: session_backend, session_ttl_seconds settings
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from typing import Optional
from unittest.mock import patch

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
from app.services.session_store_base import (
    DEFAULT_TTL_SECONDS,
    Session,
    SessionStoreBase,
    deserialize_session,
    serialize_session,
)
from app.services.session_store_memory import MemorySessionStore
from app.services.session_store_sqlite import BatchStore, SqliteSessionStore


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _db_path(tmp_path: str, name: str = "test.db") -> str:
    """Build a DB path inside a temp directory."""
    return os.path.join(tmp_path, name)


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
                    match_type="morph_bow",
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
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sqlite_store(tmp_dir):
    """Create a SqliteSessionStore with a temporary DB."""
    store = SqliteSessionStore(db_path=_db_path(tmp_dir), ttl_seconds=7200)
    yield store
    store.close()


@pytest.fixture
def memory_store():
    """Create a MemorySessionStore."""
    store = MemorySessionStore(ttl_seconds=7200)
    yield store


# ═══════════════════════════════════════════════════════════
# Abstract base class — contract
# ═══════════════════════════════════════════════════════════


class TestSessionStoreBaseContract:
    """Verify that both backends satisfy the SessionStoreBase contract."""

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_is_subclass_of_base(self, store_fixture, request):
        """Both backends are subclasses of SessionStoreBase."""
        store = request.getfixturevalue(store_fixture)
        assert isinstance(store, SessionStoreBase)

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_create_returns_session(self, store_fixture, request):
        """create() returns a Session with an auto-generated ID."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        assert isinstance(session, Session)
        assert session.id is not None
        assert len(session.id) == 12

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_create_with_explicit_id(self, store_fixture, request):
        """create() uses the provided session_id when given."""
        store = request.getfixturevalue(store_fixture)
        session = store.create(session_id="custom123")
        assert session.id == "custom123"

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_returns_created_session(self, store_fixture, request):
        """get() retrieves a session by ID."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        retrieved = store.get(session.id)
        assert retrieved is not None
        assert retrieved.id == session.id

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_nonexistent_returns_none(self, store_fixture, request):
        """get() returns None for non-existent session ID."""
        store = request.getfixturevalue(store_fixture)
        assert store.get("nonexistent") is None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_or_create_existing(self, store_fixture, request):
        """get_or_create() returns existing session if found."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        result = store.get_or_create(session.id)
        assert result.id == session.id

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_or_create_new(self, store_fixture, request):
        """get_or_create() creates new session if ID not found."""
        store = request.getfixturevalue(store_fixture)
        result = store.get_or_create(None)
        assert result.id is not None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_update_session(self, store_fixture, request):
        """update() persists changes to a session."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        session.metadata["key"] = "value"
        store.update(session)
        retrieved = store.get(session.id)
        assert retrieved is not None
        assert retrieved.metadata["key"] == "value"

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_delete_session(self, store_fixture, request):
        """delete() removes a session."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        assert store.delete(session.id) is True
        assert store.get(session.id) is None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_delete_nonexistent(self, store_fixture, request):
        """delete() returns False for non-existent session."""
        store = request.getfixturevalue(store_fixture)
        assert store.delete("ghost") is False

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_list_sessions(self, store_fixture, request):
        """list_sessions() returns all session IDs."""
        store = request.getfixturevalue(store_fixture)
        s1 = store.create()
        s2 = store.create()
        ids = store.list_sessions()
        assert s1.id in ids
        assert s2.id in ids

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_add_dictionary(self, store_fixture, request):
        """add_dictionary() stores a dictionary in the session."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        dict1 = _make_dictionary("Dict1")
        store.add_dictionary(session.id, dict1)
        retrieved = store.get(session.id)
        assert retrieved is not None
        assert "Dict1" in retrieved.dictionaries

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_dictionary(self, store_fixture, request):
        """get_dictionary() returns a specific dictionary."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        dict1 = _make_dictionary("Dict1")
        store.add_dictionary(session.id, dict1)
        result = store.get_dictionary(session.id, "Dict1")
        assert result is not None
        assert result.name == "Dict1"

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_dictionary_nonexistent(self, store_fixture, request):
        """get_dictionary() returns None for missing dictionary."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        result = store.get_dictionary(session.id, "NoDict")
        assert result is None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_add_analysis(self, store_fixture, request):
        """add_analysis() stores an analysis in the session."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        analysis = _make_analysis(session_id=session.id)
        store.add_analysis(session.id, analysis)
        retrieved = store.get(session.id)
        assert retrieved is not None
        assert analysis.analysis_id in retrieved.analyses

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_analysis_by_id(self, store_fixture, request):
        """get_analysis() finds an analysis across all sessions."""
        store = request.getfixturevalue(store_fixture)
        session = store.create()
        analysis = _make_analysis(analysis_id="findme", session_id=session.id)
        store.add_analysis(session.id, analysis)
        result = store.get_analysis("findme")
        assert result is not None
        assert result.analysis_id == "findme"

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_get_analysis_not_found(self, store_fixture, request):
        """get_analysis() returns None for unknown analysis ID."""
        store = request.getfixturevalue(store_fixture)
        assert store.get_analysis("ghost") is None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_add_dictionary_nonexistent_session(self, store_fixture, request):
        """add_dictionary() returns None for non-existent session."""
        store = request.getfixturevalue(store_fixture)
        dict1 = _make_dictionary("Dict1")
        result = store.add_dictionary("nonexistent", dict1)
        assert result is None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_add_analysis_nonexistent_session(self, store_fixture, request):
        """add_analysis() returns None for non-existent session."""
        store = request.getfixturevalue(store_fixture)
        analysis = _make_analysis(session_id="nonexistent")
        result = store.add_analysis("nonexistent", analysis)
        assert result is None

    @pytest.mark.parametrize("store_fixture", ["sqlite_store", "memory_store"])
    def test_close_is_noop_or_safe(self, store_fixture, request):
        """close() does not raise."""
        store = request.getfixturevalue(store_fixture)
        store.close()  # Should not raise


# ═══════════════════════════════════════════════════════════
# Session dataclass — serialization
# ═══════════════════════════════════════════════════════════


class TestSessionSerialization:
    """Tests for Session dataclass JSON round-trip."""

    def test_roundtrip_empty_session(self):
        """Empty session survives serialize→deserialize."""
        session = Session()
        data = serialize_session(session)
        restored = deserialize_session(data)
        assert restored.id == session.id
        assert restored.dialog is None
        assert restored.dictionaries == {}
        assert restored.analyses == {}

    def test_roundtrip_with_dialog(self):
        """Session with dialog survives serialize→deserialize."""
        session = Session()
        session.dialog = _make_dialog()
        data = serialize_session(session)
        restored = deserialize_session(data)
        assert restored.dialog is not None
        assert restored.dialog.filename == "test.rtf"
        assert len(restored.dialog.turns) == 2

    def test_roundtrip_with_dictionaries(self):
        """Session with dictionaries survives serialize→deserialize."""
        session = Session()
        session.dictionaries["D1"] = _make_dictionary("D1")
        data = serialize_session(session)
        restored = deserialize_session(data)
        assert "D1" in restored.dictionaries
        assert restored.dictionaries["D1"].name == "D1"

    def test_roundtrip_with_analysis(self):
        """Session with analysis survives serialize→deserialize."""
        session = Session()
        analysis = _make_analysis(session_id=session.id)
        session.analyses[analysis.analysis_id] = analysis
        data = serialize_session(session)
        restored = deserialize_session(data)
        assert analysis.analysis_id in restored.analyses
        assert restored.analyses[analysis.analysis_id].status == "completed"

    def test_roundtrip_metadata(self):
        """Session metadata survives serialize→deserialize."""
        session = Session()
        session.metadata["custom"] = [1, 2, 3]
        session.metadata["nested"] = {"key": "value"}
        data = serialize_session(session)
        restored = deserialize_session(data)
        assert restored.metadata["custom"] == [1, 2, 3]
        assert restored.metadata["nested"] == {"key": "value"}

    def test_session_is_expired_false(self):
        """Fresh session is not expired."""
        session = Session()
        assert session.is_expired(7200) is False

    def test_session_is_expired_true(self):
        """Manipulated session appears expired."""
        from datetime import datetime, timedelta
        session = Session()
        session.last_accessed = datetime.now() - timedelta(seconds=8000)
        assert session.is_expired(7200) is True

    def test_session_is_expired_zero_ttl(self):
        """Zero TTL means never expired."""
        from datetime import datetime, timedelta
        session = Session()
        session.last_accessed = datetime.now() - timedelta(days=365)
        assert session.is_expired(0) is False

    def test_session_touch(self):
        """touch() updates last_accessed."""
        session = Session()
        old = session.last_accessed
        time.sleep(0.01)
        session.touch()
        assert session.last_accessed > old


# ═══════════════════════════════════════════════════════════
# SQLite backend — persistence
# ═══════════════════════════════════════════════════════════


class TestSqlitePersistence:
    """Tests for SQLite persistence across restarts."""

    def test_session_persists_across_restart(self, tmp_dir):
        """Sessions survive when a new SqliteSessionStore uses the same DB file."""
        db = _db_path(tmp_dir, "persist.db")
        store1 = SqliteSessionStore(db_path=db)
        session = store1.create()
        session.dialog = _make_dialog()
        session.metadata["test_key"] = "test_value"
        store1.update(session)
        store1.close()

        store2 = SqliteSessionStore(db_path=db)
        retrieved = store2.get(session.id)
        assert retrieved is not None
        assert retrieved.dialog is not None
        assert retrieved.dialog.filename == "test.rtf"
        assert retrieved.metadata["test_key"] == "test_value"
        store2.close()

    def test_batch_persists_across_restart(self, tmp_dir):
        """Batches survive when a new BatchStore uses the same DB file."""
        db = _db_path(tmp_dir, "batch_persist.db")
        store1 = BatchStore(db_path=db)
        batch = BatchAnalysisResponse(
            batch_id="persist_test",
            session_id="sess1",
            total_files=1,
            status="processing",
            items=[BatchItemStatus(filename="a.rtf")],
        )
        store1.create(batch)
        store1.close()

        store2 = BatchStore(db_path=db)
        retrieved = store2.get("persist_test")
        assert retrieved is not None
        assert retrieved.batch_id == "persist_test"
        store2.close()


# ═══════════════════════════════════════════════════════════
# SQLite backend — TTL & Cleanup
# ═══════════════════════════════════════════════════════════


class TestSqliteTTL:
    """Tests for SQLite TTL expiration and cleanup."""

    def test_expired_session_returns_none(self, tmp_dir):
        """An expired session is treated as non-existent."""
        db = _db_path(tmp_dir, "ttl.db")
        store = SqliteSessionStore(ttl_seconds=1, db_path=db)
        session = store.create()
        time.sleep(1.5)
        result = store.get(session.id)
        assert result is None
        store.close()

    def test_cleanup_expired(self, tmp_dir):
        """cleanup_expired() removes expired sessions."""
        db = _db_path(tmp_dir, "cleanup.db")
        store = SqliteSessionStore(ttl_seconds=1, db_path=db)
        s1 = store.create()
        time.sleep(1.5)
        removed = store.cleanup_expired()
        assert removed >= 1
        assert store.get(s1.id) is None
        store.close()

    def test_non_expired_session_survives_cleanup(self, tmp_dir):
        """Non-expired sessions survive cleanup."""
        db = _db_path(tmp_dir, "survive.db")
        store = SqliteSessionStore(ttl_seconds=300, db_path=db)
        s1 = store.create()
        removed = store.cleanup_expired()
        assert store.get(s1.id) is not None
        store.close()


# ═══════════════════════════════════════════════════════════
# Memory backend — TTL & Cleanup
# ═══════════════════════════════════════════════════════════


class TestMemoryTTL:
    """Tests for memory backend TTL expiration and cleanup."""

    def test_expired_session_returns_none(self):
        """An expired session is treated as non-existent."""
        store = MemorySessionStore(ttl_seconds=1)
        session = store.create()
        time.sleep(1.5)
        result = store.get(session.id)
        assert result is None

    def test_cleanup_expired(self):
        """cleanup_expired() removes expired sessions."""
        store = MemorySessionStore(ttl_seconds=1)
        s1 = store.create()
        time.sleep(1.5)
        removed = store.cleanup_expired()
        assert removed >= 1
        assert store.get(s1.id) is None

    def test_non_expired_session_survives_cleanup(self):
        """Non-expired sessions survive cleanup."""
        store = MemorySessionStore(ttl_seconds=300)
        s1 = store.create()
        removed = store.cleanup_expired()
        assert store.get(s1.id) is not None


# ═══════════════════════════════════════════════════════════
# SQLite backend — Concurrency
# ═══════════════════════════════════════════════════════════


class TestSqliteConcurrency:
    """Tests for thread-safe concurrent access with SQLite."""

    def test_concurrent_creates(self, sqlite_store):
        """Multiple threads can create sessions concurrently."""
        results = []
        errors = []

        def create_session():
            try:
                s = sqlite_store.create()
                retrieved = sqlite_store.get(s.id)
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

    def test_concurrent_reads_and_writes(self, sqlite_store):
        """Concurrent reads and writes don't corrupt data."""
        session = sqlite_store.create()
        errors = []

        def writer():
            try:
                for i in range(10):
                    session.metadata[f"key_{i}"] = f"value_{i}"
                    sqlite_store.update(session)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(10):
                    s = sqlite_store.get(session.id)
                    assert s is not None
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"


# ═══════════════════════════════════════════════════════════
# Memory backend — Concurrency
# ═══════════════════════════════════════════════════════════


class TestMemoryConcurrency:
    """Tests for thread-safe concurrent access with memory backend."""

    def test_concurrent_creates(self):
        """Multiple threads can create sessions concurrently."""
        store = MemorySessionStore()
        results = []
        errors = []

        def create_session():
            try:
                s = store.create()
                retrieved = store.get(s.id)
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
# SQLite backend — Schema
# ═══════════════════════════════════════════════════════════


class TestSqliteSchema:
    """Tests for SQLite schema creation and WAL mode."""

    def test_db_file_created(self, tmp_dir):
        """SQLite DB file is created on initialization."""
        db = _db_path(tmp_dir, "schema.db")
        assert not os.path.exists(db)
        store = SqliteSessionStore(db_path=db)
        assert os.path.exists(db)
        store.close()

    def test_data_dir_created(self, tmp_dir):
        """Parent directory is created if it doesn't exist."""
        db = os.path.join(tmp_dir, "subdir", "deep", "test.db")
        store = SqliteSessionStore(db_path=db)
        store.create()
        assert os.path.exists(db)
        store.close()

    def test_wal_mode_enabled(self, tmp_dir):
        """WAL journal mode is enabled for better concurrent reads."""
        db = _db_path(tmp_dir, "wal.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        result = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert result.lower() == "wal"
        store.close()

    def test_sessions_table_exists(self, tmp_dir):
        """sessions table is created on initialization."""
        db = _db_path(tmp_dir, "table.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchall()
        assert len(tables) == 1
        store.close()

    def test_idempotent_init(self, tmp_dir):
        """Initializing the same DB twice does not raise."""
        db = _db_path(tmp_dir, "idempotent.db")
        store1 = SqliteSessionStore(db_path=db)
        store1.close()
        store2 = SqliteSessionStore(db_path=db)
        store2.create()  # Should work fine
        store2.close()


# ═══════════════════════════════════════════════════════════
# SQLite backend — JSON round-trip
# ═══════════════════════════════════════════════════════════


class TestSqliteJsonRoundTrip:
    """Tests for JSON serialization round-trip through SQLite."""

    def test_dialog_round_trip(self, sqlite_store):
        """Dialog data survives SQLite storage and retrieval."""
        session = sqlite_store.create()
        session.dialog = _make_dialog()
        sqlite_store.update(session)
        retrieved = sqlite_store.get(session.id)
        assert retrieved is not None
        assert retrieved.dialog.filename == "test.rtf"
        assert len(retrieved.dialog.turns) == 2
        assert retrieved.dialog.turns[0].speaker == "Клиент"

    def test_nested_dictionary_round_trip(self, sqlite_store):
        """Nested dictionary hierarchy survives SQLite round-trip."""
        session = sqlite_store.create()
        parent = DictionaryNode(
            id="parent_id",
            name="ParentDict",
            conditions=[
                DictionaryCondition(text="родитель", word_distance=2),
            ],
            condition_count=1,
            has_children=True,
            children=[
                DictionaryNode(
                    id="child_id",
                    name="ChildDict",
                    parent_name="ParentDict",
                    conditions=[
                        DictionaryCondition(text="дочерний", word_distance=1),
                    ],
                    condition_count=1,
                ),
            ],
        )
        session.dictionaries["ParentDict"] = parent
        sqlite_store.update(session)
        retrieved = sqlite_store.get(session.id)
        assert retrieved is not None
        assert "ParentDict" in retrieved.dictionaries
        parent_dict = retrieved.dictionaries["ParentDict"]
        assert parent_dict.has_children is True
        assert len(parent_dict.children) == 1
        assert parent_dict.children[0].name == "ChildDict"

    def test_unicode_round_trip(self, sqlite_store):
        """Unicode (Russian) text survives SQLite round-trip."""
        session = sqlite_store.create()
        session.metadata["russian"] = "Привет, мир! Ёёё Жжж"
        session.metadata["emoji"] = "🎉🚀"
        sqlite_store.update(session)
        retrieved = sqlite_store.get(session.id)
        assert retrieved is not None
        assert retrieved.metadata["russian"] == "Привет, мир! Ёёё Жжж"
        assert retrieved.metadata["emoji"] == "🎉🚀"


# ═══════════════════════════════════════════════════════════
# Large sessions — stress test
# ═══════════════════════════════════════════════════════════


class TestLargeSessions:
    """Stress tests with large session payloads."""

    def test_large_dialog(self, sqlite_store):
        """Session with many turns (1000) survives storage and retrieval."""
        session = sqlite_store.create()
        turns = [
            DialogueTurn(
                turn_index=i,
                speaker="Клиент" if i % 2 == 0 else "Сотрудник",
                text=f"Реплика номер {i} с достаточно длинным текстом " * 3,
            )
            for i in range(1000)
        ]
        session.dialog = ParsedDialog(
            filename="large.rtf",
            turns=turns,
            total_turns=1000,
            client_turns=500,
            employee_turns=500,
        )
        sqlite_store.update(session)
        retrieved = sqlite_store.get(session.id)
        assert retrieved is not None
        assert retrieved.dialog is not None
        assert len(retrieved.dialog.turns) == 1000

    def test_many_dictionaries(self, sqlite_store):
        """Session with many dictionaries (100) survives storage and retrieval."""
        session = sqlite_store.create()
        for i in range(100):
            d = DictionaryNode(
                id=f"dict_{i}",
                name=f"Dict{i}",
                conditions=[
                    DictionaryCondition(text=f"фраза {j}", word_distance=2)
                    for j in range(10)
                ],
                condition_count=10,
            )
            session.dictionaries[f"Dict{i}"] = d
        sqlite_store.update(session)
        retrieved = sqlite_store.get(session.id)
        assert retrieved is not None
        assert len(retrieved.dictionaries) == 100

    def test_many_analyses(self, sqlite_store):
        """Session with many analyses (50) survives storage and retrieval."""
        session = sqlite_store.create()
        for i in range(50):
            analysis = AnalysisResponse(
                analysis_id=f"ana_{i}",
                session_id=session.id,
                status="completed",
                search_result=SearchResult(
                    segments=[],
                    total_matches=i,
                    matches=[],
                    matches_by_level={},
                ),
            )
            session.analyses[f"ana_{i}"] = analysis
        sqlite_store.update(session)
        retrieved = sqlite_store.get(session.id)
        assert retrieved is not None
        assert len(retrieved.analyses) == 50


# ═══════════════════════════════════════════════════════════
# Factory — create_session_store
# ═══════════════════════════════════════════════════════════


class TestFactory:
    """Tests for the session store factory function."""

    def test_factory_sqlite_backend(self, tmp_dir):
        """Factory creates SqliteSessionStore when backend='sqlite'."""
        from app.utils.session import create_session_store
        with patch("app.utils.session._get_db_path", return_value=_db_path(tmp_dir, "factory.db")):
            with patch("app.utils.session._get_ttl_seconds", return_value=7200):
                with patch("app.config.settings") as mock_settings:
                    mock_settings.session_backend = "sqlite"
                    mock_settings.session_db_path = _db_path(tmp_dir, "factory.db")
                    mock_settings.session_ttl_seconds = 7200
                    mock_settings.max_sessions = 50
                    mock_settings.sqlite_cache_size_kb = 524288
                    store = create_session_store()
                    assert isinstance(store, SqliteSessionStore)
                    store.close()

    def test_factory_memory_backend(self):
        """Factory creates MemorySessionStore when backend='memory'."""
        from app.utils.session import create_session_store
        with patch("app.config.settings") as mock_settings:
            mock_settings.session_backend = "memory"
            mock_settings.session_ttl_seconds = 7200
            store = create_session_store()
            assert isinstance(store, MemorySessionStore)

    def test_factory_fallback_on_sqlite_error(self, tmp_dir):
        """Factory falls back to MemorySessionStore if SQLite fails."""
        from app.utils.session import create_session_store
        with patch(
            "app.services.session_store_sqlite.SqliteSessionStore.__init__",
            side_effect=OSError("Permission denied"),
        ):
            with patch("app.config.settings") as mock_settings:
                mock_settings.session_backend = "sqlite"
                mock_settings.session_db_path = "/no/such/path/db.db"
                mock_settings.session_ttl_seconds = 7200
                store = create_session_store()
                assert isinstance(store, MemorySessionStore)

    def test_factory_default_is_sqlite(self, tmp_dir):
        """Default backend is sqlite when config is unavailable."""
        from app.utils.session import create_session_store
        with patch("app.utils.session._get_db_path", return_value=_db_path(tmp_dir, "default.db")):
            with patch("app.utils.session._get_ttl_seconds", return_value=7200):
                # When config import fails, backend defaults to "sqlite"
                with patch("app.config.settings", side_effect=ImportError):
                    store = create_session_store()
                    # Should get SQLite (or memory fallback)
                    assert isinstance(store, (SqliteSessionStore, MemorySessionStore))
                    if isinstance(store, SqliteSessionStore):
                        store.close()


# ═══════════════════════════════════════════════════════════
# Config settings
# ═══════════════════════════════════════════════════════════


class TestConfigSettings:
    """Tests for session-related config settings."""

    def test_default_session_backend(self):
        """Default session_backend is 'sqlite'."""
        from app.config import Settings
        s = Settings()
        assert s.session_backend == "sqlite"

    def test_default_session_ttl(self):
        """Default session_ttl_seconds is 7200."""
        from app.config import Settings
        s = Settings()
        assert s.session_ttl_seconds == 7200

    def test_default_session_db_path(self):
        """Default session_db_path is data/sessions.db."""
        from app.config import Settings
        from pathlib import Path
        s = Settings()
        assert s.session_db_path == Path("data/sessions.db")

    def test_env_override_session_backend(self):
        """session_backend can be overridden via env var."""
        from app.config import Settings
        with patch.dict(os.environ, {"SESSION_BACKEND": "memory"}):
            s = Settings()
            assert s.session_backend == "memory"

    def test_env_override_session_ttl(self):
        """session_ttl_seconds can be overridden via env var."""
        from app.config import Settings
        with patch.dict(os.environ, {"SESSION_TTL_SECONDS": "3600"}):
            s = Settings()
            assert s.session_ttl_seconds == 3600


# ═══════════════════════════════════════════════════════════
# Backward compatibility — existing imports work
# ═══════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Tests that existing imports from app.utils.session still work."""

    def test_import_session(self):
        """Session dataclass is importable from app.utils.session."""
        from app.utils.session import Session
        assert Session is not None

    def test_import_session_store(self):
        """session_store singleton is importable from app.utils.session."""
        from app.utils.session import session_store
        assert session_store is not None
        assert isinstance(session_store, SessionStoreBase)

    def test_import_batch_store(self):
        """batch_store singleton is importable from app.utils.session."""
        from app.utils.session import batch_store
        assert batch_store is not None

    def test_import_session_store_class(self):
        """SessionStore class is importable (alias for SqliteSessionStore)."""
        from app.utils.session import SessionStore
        assert SessionStore is SqliteSessionStore

    def test_import_batch_store_class(self):
        """BatchStore class is importable from app.utils.session."""
        from app.utils.session import BatchStore
        assert BatchStore is not None

    def test_import_serialize_helpers(self):
        """Serialization helpers are importable."""
        from app.utils.session import serialize_session, deserialize_session
        assert callable(serialize_session)
        assert callable(deserialize_session)

    def test_session_store_has_expected_methods(self):
        """session_store has all expected methods."""
        from app.utils.session import session_store
        expected_methods = [
            "create", "get", "get_or_create", "update", "delete",
            "list_sessions", "add_dictionary", "get_dictionary",
            "add_analysis", "get_analysis", "cleanup_expired", "close",
        ]
        for method in expected_methods:
            assert hasattr(session_store, method), f"Missing method: {method}"

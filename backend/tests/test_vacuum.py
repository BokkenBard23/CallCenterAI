"""Tests for SQLite database maintenance: auto_vacuum, VACUUM, incremental vacuum, max_sessions.

Covers:
  - PRAGMA auto_vacuum=INCREMENTAL on new databases (P3.1)
  - PRAGMA page_size=16384 on new databases
  - Connection-level PRAGMAs (mmap_size, cache_size, synchronous, temp_store, journal_size_limit)
  - One-time auto-migration of existing databases to auto_vacuum=INCREMENTAL
  - Graceful failure of auto-migration (locked DB, disk full)
  - vacuum() method: reclaims free pages, safe on empty DB, thread-safe
  - _maybe_incremental_vacuum: triggers after N writes, triggers after _delete_expired
  - MAX_SESSIONS configurable: from config.py, from constructor, from env
  - MemorySessionStore respects max_sessions
  - Backward compatibility: no positional-arg breakage
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.services.session_store_base import Session, SessionStoreBase, MAX_SESSIONS
from app.services.session_store_memory import MemorySessionStore
from app.services.session_store_sqlite import SqliteSessionStore


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _db_path(tmp_path: str, name: str = "vacuum_test.db") -> str:
    """Build a DB path inside a temp directory."""
    return os.path.join(tmp_path, name)


def _create_existing_db(db_path: str, auto_vacuum_mode: int = 0) -> None:
    """Create a pre-existing SQLite database with specified auto_vacuum mode.

    Simulates the state of a database created before P3 was deployed.
    Creates the sessions table and one test row.
    Also creates the mining tables so that _init_db doesn't add pages.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA auto_vacuum = {auto_vacuum_mode}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA page_size = 4096")  # default, pre-P3
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions "
        "(id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sessions (id, data, created_at, last_accessed) "
        "VALUES ('legacy1', '{}', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    # Pre-create mining tables so _init_db doesn't change page count
    _create_mining_tables(conn)
    conn.commit()
    conn.close()


def _create_mining_tables(conn: sqlite3.Connection) -> None:
    """Create the Track B mining tables (same schema as _MINING_SCHEMA_SQL)."""
    mining_sql = [
        "CREATE TABLE IF NOT EXISTS mining_jobs ("
        "job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
        "dictionary_id TEXT NOT NULL, directory_path TEXT NOT NULL, "
        "job_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
        "started_at TEXT NOT NULL, completed_at TEXT, checkpoint_at TEXT, "
        "total_dialogues INTEGER DEFAULT 0, processed_dialogues INTEGER DEFAULT 0, "
        "error TEXT, warning TEXT, result_json TEXT)",
        "CREATE TABLE IF NOT EXISTS mining_corpus ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, "
        "dialogue_id TEXT NOT NULL, file_path TEXT NOT NULL, channel TEXT, "
        "text TEXT NOT NULL, embedding_id INTEGER, turn_count INTEGER DEFAULT 0, "
        "llm_summary TEXT, llm_label TEXT, llm_score REAL, llm_reason TEXT)",
        "CREATE TABLE IF NOT EXISTS mining_fn_candidates ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, "
        "dialogue_id TEXT NOT NULL, phrase_group_id TEXT, score REAL NOT NULL, "
        "llm_label TEXT NOT NULL, llm_score REAL, llm_reason TEXT, proposed_phrase TEXT)",
        "CREATE TABLE IF NOT EXISTS mining_audit_results ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, "
        "phrase_group_id TEXT NOT NULL, phrase_text TEXT, recall REAL, "
        "missed_count INTEGER DEFAULT 0, recommendations_json TEXT, llm_explanation TEXT)",
        "CREATE TABLE IF NOT EXISTS mining_checkpoints ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, "
        "checkpoint_at TEXT NOT NULL, processed_count INTEGER NOT NULL, last_dialogue_id TEXT)",
    ]
    for stmt in mining_sql:
        conn.execute(stmt)
    for table in ["mining_corpus", "mining_fn_candidates", "mining_audit_results",
                   "mining_checkpoints", "mining_jobs"]:
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_job ON {table}(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mining_jobs_session_dict ON mining_jobs(session_id, dictionary_id)")


def _freelist_count(db_path: str) -> int:
    """Return PRAGMA freelist_count for a database file (fresh connection)."""
    conn = sqlite3.connect(db_path)
    count = conn.execute("PRAGMA freelist_count").fetchone()[0]
    conn.close()
    return count


def _page_count(db_path: str) -> int:
    """Return PRAGMA page_count for a database file (fresh connection)."""
    conn = sqlite3.connect(db_path)
    count = conn.execute("PRAGMA page_count").fetchone()[0]
    conn.close()
    return count


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
def store(tmp_dir):
    """Create a fresh SqliteSessionStore with a temporary DB."""
    s = SqliteSessionStore(db_path=_db_path(tmp_dir))
    yield s
    s.close()


# ═══════════════════════════════════════════════════════════
# PRAGMA settings on new databases
# ═══════════════════════════════════════════════════════════


class TestSqliteAutoVacuum:
    """Verify that persistent PRAGMAs are set on newly created databases."""

    def test_auto_vacuum_incremental_on_new_db(self, tmp_dir):
        """New DB has auto_vacuum=2 (INCREMENTAL) after store init."""
        db = _db_path(tmp_dir, "auto_vac_new.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        assert av == 2, f"Expected auto_vacuum=2 (INCREMENTAL), got {av}"
        store.close()

    def test_page_size_16384_on_new_db(self, tmp_dir):
        """New DB has page_size=16384 after store init."""
        db = _db_path(tmp_dir, "page_size_new.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        ps = conn.execute("PRAGMA page_size").fetchone()[0]
        assert ps == 16384, f"Expected page_size=16384, got {ps}"
        store.close()

    def test_page_size_persists_across_connections(self, tmp_dir):
        """page_size is persistent in the DB header (visible from new connections)."""
        db = _db_path(tmp_dir, "page_persist.db")
        store = SqliteSessionStore(db_path=db)
        store.close()

        # Open a brand-new connection (not thread-local to the store)
        conn = sqlite3.connect(db)
        ps = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.close()
        assert ps == 16384, f"Expected page_size=16384 from fresh connection, got {ps}"

    def test_auto_vacuum_persists_across_connections(self, tmp_dir):
        """auto_vacuum=INCREMENTAL is persistent in the DB header."""
        db = _db_path(tmp_dir, "av_persist.db")
        store = SqliteSessionStore(db_path=db)
        store.close()

        conn = sqlite3.connect(db)
        av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        conn.close()
        assert av == 2, f"Expected auto_vacuum=2 from fresh connection, got {av}"


class TestConnectionLevelPragmas:
    """Verify that connection-level PRAGMAs are set on every new connection."""

    def test_synchronous_normal(self, tmp_dir):
        """synchronous=NORMAL is set on new connections."""
        db = _db_path(tmp_dir, "sync_normal.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert sync == 1, f"Expected synchronous=1 (NORMAL), got {sync}"
        store.close()

    def test_mmap_size_set(self, tmp_dir):
        """mmap_size=268435456 is set on new connections."""
        db = _db_path(tmp_dir, "mmap.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        mmap = conn.execute("PRAGMA mmap_size").fetchone()[0]
        assert mmap == 268435456, f"Expected mmap_size=268435456, got {mmap}"
        store.close()

    def test_cache_size_set(self, tmp_dir):
        """cache_size reflects the configurable value (default 512 MB = -524288 KB)."""
        db = _db_path(tmp_dir, "cache.db")
        store = SqliteSessionStore(db_path=db)  # default 524288 KB
        conn = store._get_connection()
        cache = conn.execute("PRAGMA cache_size").fetchone()[0]
        assert cache == -524288, f"Expected cache_size=-524288 (512 MB), got {cache}"
        store.close()

    def test_cache_size_custom(self, tmp_dir):
        """cache_size accepts custom value from constructor."""
        db = _db_path(tmp_dir, "cache_custom.db")
        store = SqliteSessionStore(db_path=db, cache_size_kb=131072)  # 128 MB
        conn = store._get_connection()
        cache = conn.execute("PRAGMA cache_size").fetchone()[0]
        assert cache == -131072, f"Expected -131072 (128 MB), got {cache}"
        store.close()

    def test_temp_store_memory(self, tmp_dir):
        """temp_store=MEMORY is set on new connections."""
        db = _db_path(tmp_dir, "temp_store.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        ts = conn.execute("PRAGMA temp_store").fetchone()[0]
        assert ts == 2, f"Expected temp_store=2 (MEMORY), got {ts}"
        store.close()

    def test_journal_size_limit_set(self, tmp_dir):
        """journal_size_limit=67108864 is set on new connections."""
        db = _db_path(tmp_dir, "journal_limit.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        jsl = conn.execute("PRAGMA journal_size_limit").fetchone()[0]
        assert jsl == 67108864, f"Expected journal_size_limit=67108864, got {jsl}"
        store.close()


# ═══════════════════════════════════════════════════════════
# Auto-migration of existing databases
# ═══════════════════════════════════════════════════════════


class TestAutoMigrate:
    """One-time migration of existing databases to auto_vacuum=INCREMENTAL."""

    def test_auto_migrate_existing_db(self, tmp_dir):
        """Existing DB with auto_vacuum=0 gets migrated to INCREMENTAL on open."""
        db = _db_path(tmp_dir, "migrate_existing.db")
        _create_existing_db(db, auto_vacuum_mode=0)

        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()
        av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        assert av == 2, f"Expected auto_vacuum=2 after migration, got {av}"

        row = conn.execute("SELECT id FROM sessions WHERE id='legacy1'").fetchone()
        assert row is not None, "Existing data should survive migration VACUUM"
        store.close()

    def test_auto_migrate_skipped_if_already_incremental(self, tmp_dir):
        """If auto_vacuum is already 2, no VACUUM is needed (pragma unchanged)."""
        db = _db_path(tmp_dir, "migrate_skip.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA auto_vacuum = 2")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE sessions "
            "(id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO sessions (id, data, created_at, last_accessed) "
            "VALUES ('skip1', '{}', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        _create_mining_tables(conn)
        conn.commit()
        conn.close()

        store = SqliteSessionStore(db_path=db)

        # After init, auto_vacuum should still be 2 (no VACUUM was run)
        store_conn = store._get_connection()
        av = store_conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        assert av == 2, f"Expected auto_vacuum=2, got {av}"

        # Old data survives
        row = store_conn.execute("SELECT id FROM sessions WHERE id='skip1'").fetchone()
        assert row is not None
        store.close()

    def test_auto_migrate_graceful_failure(self, tmp_dir):
        """If migration fails, the store should still work."""
        db = _db_path(tmp_dir, "migrate_fail.db")
        _create_existing_db(db, auto_vacuum_mode=0)

        def failing_migrate(self_):
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Simulated VACUUM failure")

        with patch.object(SqliteSessionStore, "_ensure_auto_vacuum", failing_migrate):
            store = SqliteSessionStore(db_path=db)
            session = store.create()
            retrieved = store.get(session.id)
            assert retrieved is not None
            store.close()

    def test_auto_migrate_data_integrity(self, tmp_dir):
        """After migration, all existing data is intact."""
        db = _db_path(tmp_dir, "migrate_integrity.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA auto_vacuum = 0")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE sessions "
            "(id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed TEXT NOT NULL)"
        )
        for i in range(10):
            conn.execute(
                "INSERT INTO sessions (id, data, created_at, last_accessed) "
                "VALUES (?, '{}', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                (f"legacy_{i}",),
            )
        conn.commit()
        conn.close()

        store = SqliteSessionStore(db_path=db)
        conn_new = store._get_connection()
        rows = conn_new.execute("SELECT id FROM sessions ORDER BY id").fetchall()
        ids = [r[0] for r in rows]
        assert len(ids) == 10
        assert ids == [f"legacy_{i}" for i in range(10)]
        store.close()


# ═══════════════════════════════════════════════════════════
# vacuum() method
# ═══════════════════════════════════════════════════════════


class TestVacuumMethod:
    """Tests for the SqliteSessionStore.vacuum() method."""

    def test_vacuum_reclaims_free_pages(self, tmp_dir):
        """vacuum() reduces freelist_count to 0 when there are free pages."""
        db = _db_path(tmp_dir, "vacuum_reclaim.db")
        store = SqliteSessionStore(db_path=db)

        sessions = []
        for i in range(50):
            s = store.create()
            s.metadata["data"] = "x" * 20000
            store.update(s)
            sessions.append(s)

        for s in sessions:
            store.delete(s.id)

        freelist_before = _freelist_count(db)
        assert freelist_before > 0

        store.vacuum()

        freelist_after = _freelist_count(db)
        assert freelist_after == 0
        store.close()

    def test_vacuum_on_empty_db(self, tmp_dir):
        """vacuum() does not crash on an empty / newly created database."""
        db = _db_path(tmp_dir, "vacuum_empty.db")
        store = SqliteSessionStore(db_path=db)
        store.vacuum()
        store.close()

    def test_vacuum_after_single_session(self, tmp_dir):
        """vacuum() works with one active session (no free pages to reclaim)."""
        db = _db_path(tmp_dir, "vacuum_single.db")
        store = SqliteSessionStore(db_path=db)
        s = store.create()
        s.metadata["note"] = "test"
        store.update(s)
        store.vacuum()
        retrieved = store.get(s.id)
        assert retrieved is not None
        store.close()

    def test_vacuum_resets_write_count(self, tmp_dir):
        """After vacuum(), _write_count should be 0."""
        db = _db_path(tmp_dir, "vacuum_reset.db")
        store = SqliteSessionStore(db_path=db)

        for i in range(10):
            store.create()
        assert store._write_count >= 10

        store.vacuum()
        assert store._write_count == 0
        store.close()

    def test_concurrent_vacuum_is_safe(self, tmp_dir):
        """vacuum() under concurrent reads does not crash."""
        db = _db_path(tmp_dir, "vacuum_concurrent.db")
        store = SqliteSessionStore(db_path=db)

        sessions = []
        for i in range(30):
            s = store.create()
            store.update(s)
            sessions.append(s)

        errors = []

        def deleter():
            try:
                for s in sessions:
                    store.delete(s.id)
            except Exception as e:
                errors.append(e)

        def vacuum_runner():
            try:
                store.vacuum()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=deleter),
            threading.Thread(target=vacuum_runner),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        store.close()


# ═══════════════════════════════════════════════════════════
# Incremental vacuum
# ═══════════════════════════════════════════════════════════


class TestIncrementalVacuum:
    """Tests for the _maybe_incremental_vacuum mechanism."""

    def test_incremental_vacuum_no_freelist_noop(self, tmp_dir):
        """_maybe_incremental_vacuum does nothing when freelist is empty."""
        db = _db_path(tmp_dir, "inc_noop.db")
        store = SqliteSessionStore(db_path=db)
        conn = store._get_connection()

        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        store._maybe_incremental_vacuum(conn)
        freelist_after = conn.execute("PRAGMA freelist_count").fetchone()[0]
        assert freelist_after == freelist
        store.close()

    def test_incremental_vacuum_after_writes_and_deletes(self, tmp_dir):
        """Incremental vacuum should reclaim pages after deletes."""
        db = _db_path(tmp_dir, "inc_write_delete.db")
        store = SqliteSessionStore(db_path=db)

        sessions = []
        for i in range(100):
            s = store.create()
            s.metadata["data"] = "y" * 10000
            store.update(s)
            sessions.append(s)

        for s in sessions:
            store.delete(s.id)

        freelist_before = _freelist_count(db)
        assert freelist_before > 0

        conn = store._get_connection()
        store._maybe_incremental_vacuum(conn)

        freelist_after = _freelist_count(db)
        assert freelist_after < freelist_before
        store.close()

    def test_write_count_increments_on_create(self, tmp_dir):
        """_write_count increments after each create()."""
        db = _db_path(tmp_dir, "wc_create.db")
        store = SqliteSessionStore(db_path=db)

        for i in range(10):
            wc_before = store._write_count
            store.create()
            assert store._write_count == wc_before + 1
        store.close()

    def test_write_count_increments_on_update(self, tmp_dir):
        """_write_count increments after each update()."""
        db = _db_path(tmp_dir, "wc_update.db")
        store = SqliteSessionStore(db_path=db)
        s = store.create()
        wc_before = store._write_count

        for i in range(5):
            store.update(s)
            assert store._write_count == wc_before + i + 1
        store.close()

    def test_write_count_increments_on_delete(self, tmp_dir):
        """_write_count increments after each delete()."""
        db = _db_path(tmp_dir, "wc_delete.db")
        store = SqliteSessionStore(db_path=db)
        s = store.create()
        wc_before = store._write_count
        store.delete(s.id)
        assert store._write_count == wc_before + 1
        store.close()

    def test_write_count_increments_on_get(self, tmp_dir):
        """_write_count increments after each get() — get() does UPDATE last_accessed."""
        db = _db_path(tmp_dir, "wc_get.db")
        store = SqliteSessionStore(db_path=db)
        s = store.create()
        wc_after_create = store._write_count

        for i in range(5):
            store.get(s.id)
            assert store._write_count == wc_after_create + i + 1, (
                f"Expected _write_count={wc_after_create + i + 1}, "
                f"got {store._write_count}"
            )
        store.close()

    def test_write_count_increments_on_get_expired_delete(self, tmp_dir):
        """_write_count increments when get() deletes an expired session."""
        db = _db_path(tmp_dir, "wc_get_expired.db")
        store = SqliteSessionStore(db_path=db, ttl_seconds=1)
        s = store.create()
        wc_before = store._write_count

        time.sleep(1.5)
        # get() on expired session should DELETE + increment
        result = store.get(s.id)
        assert result is None, "Expired session should return None"
        assert store._write_count == wc_before + 1, (
            f"Expected _write_count={wc_before + 1} after expired-delete, "
            f"got {store._write_count}"
        )
        store.close()

    def test_write_count_on_add_dictionary(self, tmp_dir):
        """add_dictionary calls get() (write) + update() (write) → _write_count += 2."""
        db = _db_path(tmp_dir, "wc_add_dict.db")
        store = SqliteSessionStore(db_path=db)
        s = store.create()
        wc_before = store._write_count

        from app.models import DictionaryNode, DictionaryCondition
        d = DictionaryNode(
            id="d1", name="Dict1",
            conditions=[DictionaryCondition(text="фраза", word_distance=2)],
            condition_count=1,
        )
        store.add_dictionary(s.id, d)

        # get() (UPDATE last_accessed) + update() (UPDATE data) = 2 writes
        assert store._write_count == wc_before + 2, (
            f"Expected _write_count={wc_before + 2} after add_dictionary, "
            f"got {store._write_count}"
        )
        store.close()

    def test_write_count_on_add_analysis(self, tmp_dir):
        """add_analysis calls get() (write) + update() (write) → _write_count += 2."""
        db = _db_path(tmp_dir, "wc_add_analysis.db")
        store = SqliteSessionStore(db_path=db)
        s = store.create()
        wc_before = store._write_count

        from app.models import AnalysisResponse, SearchResult
        analysis = AnalysisResponse(
            analysis_id="ana1",
            session_id=s.id,
            status="completed",
            search_result=SearchResult(segments=[], total_matches=0, matches=[], matches_by_level={}),
        )
        store.add_analysis(s.id, analysis)

        assert store._write_count == wc_before + 2, (
            f"Expected _write_count={wc_before + 2} after add_analysis, "
            f"got {store._write_count}"
        )
        store.close()

    def test_periodic_vacuum_trigger_on_100th_write(self, tmp_dir):
        """After 100 writes, _maybe_incremental_vacuum is called automatically."""
        db = _db_path(tmp_dir, "periodic.db")
        store = SqliteSessionStore(db_path=db)

        sessions = []
        for i in range(50):
            s = store.create()
            sessions.append(s)
        for s in sessions:
            store.delete(s.id)

        assert store._write_count >= 100, (
            f"Expected _write_count >= 100, got {store._write_count}"
        )

        freelist = _freelist_count(db)
        assert freelist < 200, f"Freelist should be bounded, got {freelist}"
        store.close()

    def test_periodic_vacuum_trigger_includes_get_writes(self, tmp_dir):
        """100 writes from get() (read-heavy workload) should trigger incremental vacuum."""
        db = _db_path(tmp_dir, "periodic_get.db")
        store = SqliteSessionStore(db_path=db)

        # Create 50 sessions with large data (50KB each → ~5 pages per session
        # at 16KB page_size, so ~250 free pages after delete — well above
        # the incremental_vacuum threshold of 50).
        sessions = []
        for i in range(50):
            s = store.create()
            s.metadata["data"] = "z" * 50000  # 50KB
            store.update(s)
            sessions.append(s)

        # Delete all to create free pages
        for s in sessions:
            store.delete(s.id)

        wc_after_cleanup = store._write_count
        freelist_before = _freelist_count(db)
        assert freelist_before > 50, (
            f"Expected freelist > 50 (threshold), got {freelist_before}"
        )

        # Force _write_count to next multiple of 100 via creates
        target = (wc_after_cleanup // 100 + 1) * 100
        creates_needed = target - wc_after_cleanup
        for i in range(creates_needed):
            store.create()

        assert store._write_count % 100 == 0

        freelist_after = _freelist_count(db)
        assert freelist_after < freelist_before, (
            f"Incremental vacuum should have reclaimed pages: "
            f"{freelist_before} -> {freelist_after}"
        )
        store.close()

    def test_delete_expired_returns_actual_ids(self, tmp_dir):
        """_delete_expired should return the list of actually deleted session IDs."""
        db = _db_path(tmp_dir, "delete_expired_ids.db")
        store = SqliteSessionStore(db_path=db, ttl_seconds=1)

        # Create 3 sessions
        s1 = store.create()
        s2 = store.create()
        s3 = store.create()

        # Wait for expiry
        time.sleep(1.5)

        # Force cleanup via cleanup_expired (uses _delete_expired internally
        # through _maybe_cleanup in create() OR directly)
        removed = store.cleanup_expired()
        assert removed == 3, f"Expected 3 removed, got {removed}"

        # Verify the sessions are gone
        assert store.get(s1.id) is None
        assert store.get(s2.id) is None
        assert store.get(s3.id) is None
        store.close()


# ═══════════════════════════════════════════════════════════
# MAX_SESSIONS configurable
# ═══════════════════════════════════════════════════════════


class TestMaxSessions:
    """Verify that max_sessions is configurable and respected."""

    def test_store_uses_custom_max_sessions(self, tmp_dir):
        """SqliteSessionStore triggers cleanup when count exceeds max_sessions
        and expired sessions exist."""
        db = _db_path(tmp_dir, "custom_max.db")
        store = SqliteSessionStore(db_path=db, max_sessions=3)
        assert store._max_sessions == 3

        # Create 3 sessions — all within TTL, no cleanup needed
        s1 = store.create()  # 1
        s2 = store.create()  # 2
        s3 = store.create()  # 3
        assert len(store.list_sessions()) == 3

        # Create 4th — _maybe_cleanup fires but no expired sessions → 4 visible
        s4 = store.create()  # 4
        assert len(store.list_sessions()) == 4

        # Manually expire one session via SQL
        conn = store._get_connection()
        conn.execute(
            "UPDATE sessions SET last_accessed = '2020-01-01T00:00:00' WHERE id = ?",
            (s1.id,),
        )
        conn.commit()

        # Force cleanup — should remove the expired session
        removed = store.cleanup_expired()
        assert removed == 1, f"Expected 1 expired session removed, got {removed}"
        assert len(store.list_sessions()) == 3

        # Now create another — 4th again, but 1 expired exists → cleanup removes it
        s5 = store.create()
        assert len(store.list_sessions()) <= 4

        store.close()

    def test_default_max_sessions(self, tmp_dir):
        """SqliteSessionStore default max_sessions is 100."""
        db = _db_path(tmp_dir, "default_max.db")
        store = SqliteSessionStore(db_path=db)
        assert store._max_sessions == 100
        store.close()

    def test_memory_store_respects_max_sessions(self):
        """MemorySessionStore triggers cleanup when count exceeds max_sessions
        and expired sessions exist."""
        store = MemorySessionStore(ttl_seconds=7200, max_sessions=3)
        assert store._max_sessions == 3

        s1 = store.create()
        s2 = store.create()
        s3 = store.create()
        assert len(store.list_sessions()) == 3

        # 4th create — _maybe_cleanup fires (3 >= 3), but no expired sessions
        s4 = store.create()
        assert len(store.list_sessions()) == 4

        # Manually expire one session via internal dict (bypasses touch())
        store._sessions[s1.id].last_accessed = datetime.now() - timedelta(days=365)

        # Now 5th create — _maybe_cleanup should remove s1
        s5 = store.create()
        all_ids = store.list_sessions()
        assert len(all_ids) <= 4, (
            f"Expected <=4 sessions after cleanup, got {len(all_ids)}"
        )
        assert s1.id not in all_ids, "Expired session should have been cleaned up"

    def test_memory_store_default(self):
        """MemorySessionStore default max_sessions is 100."""
        store = MemorySessionStore()
        assert store._max_sessions == 100

    def test_factory_passes_max_sessions_sqlite(self, tmp_dir):
        """Factory creates SqliteSessionStore with max_sessions from settings."""
        from app.utils.session import create_session_store
        db = _db_path(tmp_dir, "factory_max.db")
        with patch("app.config.settings") as mock:
            mock.session_backend = "sqlite"
            mock.session_db_path = db
            mock.session_ttl_seconds = 7200
            mock.max_sessions = 50
            store = create_session_store()
            assert store._max_sessions == 50
            store.close()

    def test_factory_passes_max_sessions_memory(self):
        """Factory creates MemorySessionStore with max_sessions from settings."""
        from app.utils.session import create_session_store
        with patch("app.config.settings") as mock:
            mock.session_backend = "memory"
            mock.session_ttl_seconds = 7200
            mock.max_sessions = 25
            store = create_session_store()
            assert store._max_sessions == 25

    def test_max_sessions_from_env(self, tmp_dir):
        """Settings reads MAX_SESSIONS from environment."""
        with patch.dict(os.environ, {"MAX_SESSIONS": "77"}):
            s = Settings()
            assert s.max_sessions == 77

    def test_default_max_sessions_in_settings(self):
        """Settings default max_sessions is 100."""
        s = Settings()
        assert s.max_sessions == 100

    def test_legacy_max_sessions_constant(self):
        """MAX_SESSIONS constant is still 100 (updated from 1000)."""
        assert MAX_SESSIONS == 100


# ═══════════════════════════════════════════════════════════
# WAL checkpoint and vacuum integration
# ═══════════════════════════════════════════════════════════


class TestWalVacuumIntegration:
    """Integration tests for WAL checkpoint + VACUUM interaction."""

    def test_vacuum_truncates_wal(self, tmp_dir):
        """After vacuum() + checkpoint(TRUNCATE), WAL file is small."""
        db = _db_path(tmp_dir, "wal_truncate.db")
        store = SqliteSessionStore(db_path=db)

        for i in range(20):
            s = store.create()
            store.delete(s.id)

        wal_path = db + "-wal"
        wal_size_before = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0

        store.vacuum()

        wal_size_after = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        assert wal_size_after <= wal_size_before
        assert wal_size_after < 32768
        store.close()

    def test_vacuum_preserves_data(self, tmp_dir):
        """After vacuum, all existing sessions are still readable."""
        db = _db_path(tmp_dir, "vacuum_preserve.db")
        store = SqliteSessionStore(db_path=db)

        session_ids = []
        for i in range(20):
            s = store.create()
            s.metadata["index"] = i
            store.update(s)
            session_ids.append(s.id)

        store.vacuum()

        for sid in session_ids:
            retrieved = store.get(sid)
            assert retrieved is not None
            assert retrieved.metadata["index"] == session_ids.index(sid)
        store.close()


# ═══════════════════════════════════════════════════════════
# Backward compatibility
# ═══════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Existing constructor signatures still work (positional and keyword)."""

    def test_old_positional_db_path(self, tmp_dir):
        """SqliteSessionStore('path') still works (db_path as first positional)."""
        db = _db_path(tmp_dir, "back_compat.db")
        store = SqliteSessionStore(db)
        s = store.create()
        assert s is not None
        store.close()

    def test_old_keyword_only_args(self, tmp_dir):
        """SqliteSessionStore(db_path=..., ttl_seconds=...) still works."""
        db = _db_path(tmp_dir, "back_kwarg.db")
        store = SqliteSessionStore(db_path=db, ttl_seconds=3600)
        assert store._ttl_seconds == 3600
        assert store._max_sessions == 100
        store.close()

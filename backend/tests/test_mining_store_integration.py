"""Integration tests for MiningStore — full job lifecycle e2e.

Covers:
  - Job CRUD: create, get, update, cancel
  - Corpus entry lifecycle (add, list)
  - FN candidate lifecycle (add, list)
  - Audit result lifecycle (add, list)
  - Checkpoint lifecycle (add, get_last, get_progress)
  - Duplicate detection via find_running_job
  - Error handling: unknown job returns None
  - Thread safety under concurrent writes
  - verify_tables_exist
  - JSON helpers (dump_json, load_json)
  - Cleanup via close()
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime

import pytest

from app.services.session_store_sqlite import MiningStore


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def tmp_db_path():
    """Create a temporary database path and clean up after the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    # Clean up WAL/SHM files
    for ext in ("-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except FileNotFoundError:
            pass


@pytest.fixture
def store(tmp_db_path):
    """Create a MiningStore with a temporary database."""
    s = MiningStore(db_path=tmp_db_path)
    yield s
    s.close()


@pytest.fixture
def sample_job_id() -> str:
    return "test-job-001"


@pytest.fixture
def sample_session_id() -> str:
    return "sess-mining-001"


@pytest.fixture
def sample_dict_id() -> str:
    return "dict-quality-001"


# ═══════════════════════════════════════════════════════════
# Job lifecycle
# ═══════════════════════════════════════════════════════════


class TestJobLifecycle:
    """Full CRUD lifecycle for mining jobs."""

    def test_create_job_returns_full_record(self, store, sample_job_id, sample_session_id, sample_dict_id):
        result = store.create_job(
            job_id=sample_job_id,
            session_id=sample_session_id,
            dictionary_id=sample_dict_id,
            directory_path="/data/rtf/2026-07",
            job_type="index",
        )
        assert result["job_id"] == sample_job_id
        assert result["session_id"] == sample_session_id
        assert result["dictionary_id"] == sample_dict_id
        assert result["status"] == "pending"
        assert result["started_at"] is not None
        assert result["completed_at"] is None
        assert result["error"] is None

    def test_get_job_returns_none_for_unknown(self, store):
        assert store.get_job("nonexistent-job") is None

    def test_get_job_returns_created_job(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id,
            session_id=sample_session_id,
            dictionary_id=sample_dict_id,
            directory_path="/data/rtf",
            job_type="find_fn",
        )
        retrieved = store.get_job(sample_job_id)
        assert retrieved is not None
        assert retrieved["job_id"] == sample_job_id
        assert retrieved["job_type"] == "find_fn"
        assert retrieved["status"] == "pending"

    def test_update_job_status(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id,
            session_id=sample_session_id,
            dictionary_id=sample_dict_id,
            directory_path="/data/rtf",
            job_type="audit",
        )
        updated = store.update_job(sample_job_id, status="running")
        assert updated is True
        job = store.get_job(sample_job_id)
        assert job["status"] == "running"

    def test_update_job_partial_fields(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id,
            session_id=sample_session_id,
            dictionary_id=sample_dict_id,
            directory_path="/data/rtf",
            job_type="index",
        )
        now = datetime.now().isoformat()
        store.update_job(
            sample_job_id,
            status="completed",
            completed_at=now,
            total_dialogues=50,
            processed_dialogues=50,
        )
        job = store.get_job(sample_job_id)
        assert job["status"] == "completed"
        assert job["completed_at"] == now
        assert job["total_dialogues"] == 50
        assert job["processed_dialogues"] == 50

    def test_update_job_no_changes_returns_false(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id,
            session_id=sample_session_id,
            dictionary_id=sample_dict_id,
            directory_path="/data/rtf",
            job_type="index",
        )
        result = store.update_job(sample_job_id)
        assert result is False

    def test_cancel_job(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id,
            session_id=sample_session_id,
            dictionary_id=sample_dict_id,
            directory_path="/data/rtf",
            job_type="index",
        )
        result = store.cancel_job(sample_job_id)
        assert result is True
        job = store.get_job(sample_job_id)
        assert job["status"] == "cancelled"

    def test_cancel_nonexistent_job_returns_false(self, store):
        assert store.cancel_job("ghost-job") is False


class TestFindRunningJob:
    """Duplicate job detection via find_running_job."""

    def test_find_running_returns_pending_job(self, store, sample_session_id, sample_dict_id):
        store.create_job(
            job_id="job-1", session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        running = store.find_running_job(sample_session_id, sample_dict_id)
        assert running is not None
        assert running["job_id"] == "job-1"

    def test_find_running_returns_running_job(self, store, sample_session_id, sample_dict_id):
        store.create_job(
            job_id="job-2", session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        store.update_job("job-2", status="running")
        running = store.find_running_job(sample_session_id, sample_dict_id)
        assert running is not None
        assert running["status"] == "running"

    def test_find_running_returns_none_for_completed(self, store, sample_session_id, sample_dict_id):
        store.create_job(
            job_id="job-3", session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="find_fn",
        )
        store.update_job("job-3", status="completed")
        running = store.find_running_job(sample_session_id, sample_dict_id)
        assert running is None

    def test_find_running_different_session(self, store, sample_dict_id):
        store.create_job(
            job_id="job-4", session_id="sess-a",
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        running = store.find_running_job("sess-b", sample_dict_id)
        assert running is None

    def test_find_running_different_dict(self, store, sample_session_id):
        store.create_job(
            job_id="job-5", session_id=sample_session_id,
            dictionary_id="dict-a", directory_path="/data", job_type="index",
        )
        running = store.find_running_job(sample_session_id, "dict-b")
        assert running is None


# ═══════════════════════════════════════════════════════════
# Corpus entries
# ═══════════════════════════════════════════════════════════


class TestCorpusLifecycle:
    """Add and list corpus entries."""

    def test_add_corpus_entry(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        row_id = store.add_corpus_entry(
            job_id=sample_job_id,
            dialogue_id="dial-001",
            file_path="/data/dial-001.rtf",
            text="Здравствуйте, чем могу помочь?",
            channel="OPERATOR",
            turn_count=1,
        )
        assert row_id > 0

    def test_list_corpus_returns_entries(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        store.add_corpus_entry(
            job_id=sample_job_id, dialogue_id="d1",
            file_path="/data/d1.rtf", text="Hello", channel="CLIENT",
        )
        store.add_corpus_entry(
            job_id=sample_job_id, dialogue_id="d2",
            file_path="/data/d2.rtf", text="World", channel="OPERATOR",
        )
        entries = store.list_corpus(sample_job_id)
        assert len(entries) == 2
        assert entries[0]["dialogue_id"] in ("d1", "d2")

    def test_list_corpus_empty_job(self, store):
        entries = store.list_corpus("ghost-job")
        assert entries == []

    def test_corpus_entry_with_all_fields(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        row_id = store.add_corpus_entry(
            job_id=sample_job_id, dialogue_id="d-full",
            file_path="/data/d-full.rtf", text="Test",
            channel="ANY", turn_count=5, embedding_id=42,
            llm_summary="Test summary", llm_label="positive",
            llm_score=0.95, llm_reason="Good call",
        )
        entries = store.list_corpus(sample_job_id)
        entry = entries[0]
        assert entry["embedding_id"] == 42
        assert entry["llm_summary"] == "Test summary"
        assert entry["llm_score"] == 0.95


# ═══════════════════════════════════════════════════════════
# FN candidates
# ═══════════════════════════════════════════════════════════


class TestFnCandidateLifecycle:
    """Add and list false-negative candidates."""

    def test_add_fn_candidate(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="find_fn",
        )
        row_id = store.add_fn_candidate(
            job_id=sample_job_id, dialogue_id="d-fn-1",
            score=0.87, llm_label="relevant",
            phrase_group_id="pg-1",
        )
        assert row_id > 0

    def test_list_fn_candidates(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="find_fn",
        )
        store.add_fn_candidate(
            job_id=sample_job_id, dialogue_id="d1", score=0.9,
            llm_label="relevant", phrase_group_id="pg-1",
            llm_score=0.85, llm_reason="Similar context",
            proposed_phrase="новая фраза",
        )
        candidates = store.list_fn_candidates(sample_job_id)
        assert len(candidates) == 1
        assert candidates[0]["proposed_phrase"] == "новая фраза"
        assert candidates[0]["llm_score"] == 0.85

    def test_list_fn_candidates_empty(self, store):
        assert store.list_fn_candidates("no-such-job") == []


# ═══════════════════════════════════════════════════════════
# Audit results
# ═══════════════════════════════════════════════════════════


class TestAuditResultLifecycle:
    """Add and list audit results."""

    def test_add_audit_result(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="audit",
        )
        row_id = store.add_audit_result(
            job_id=sample_job_id, phrase_group_id="pg-audit-1",
            phrase_text="тестовая фраза", recall=0.75, missed_count=3,
            recommendations_json='[{"type": "add_phrase", "phrase": "новая", "reason": "missed"}]',
            llm_explanation="**Анализ:** фраза найдена в 75% случаев.",
        )
        assert row_id > 0

    def test_list_audit_results(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="audit",
        )
        store.add_audit_result(
            job_id=sample_job_id, phrase_group_id="pg-1",
            phrase_text="фраза 1", recall=1.0, missed_count=0,
            recommendations_json="[]", llm_explanation="All good.",
        )
        results = store.list_audit_results(sample_job_id)
        assert len(results) == 1
        assert results[0]["recall"] == 1.0

    def test_list_audit_results_empty(self, store):
        assert store.list_audit_results("ghost") == []


# ═══════════════════════════════════════════════════════════
# Checkpoints
# ═══════════════════════════════════════════════════════════


class TestCheckpointLifecycle:
    """Checkpoint operations for job resumption."""

    def test_add_checkpoint(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        store.add_checkpoint(
            job_id=sample_job_id, processed_count=25,
            last_dialogue_id="dial-025",
        )
        progress = store.get_progress(sample_job_id)
        assert progress == 25

    def test_get_last_checkpoint(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        store.add_checkpoint(job_id=sample_job_id, processed_count=10, last_dialogue_id="d10")
        store.add_checkpoint(job_id=sample_job_id, processed_count=25, last_dialogue_id="d25")
        store.add_checkpoint(job_id=sample_job_id, processed_count=50, last_dialogue_id="d50")
        last = store.get_last_checkpoint(sample_job_id)
        assert last == 50

    def test_get_last_checkpoint_no_checkpoints(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        last = store.get_last_checkpoint(sample_job_id)
        assert last is None

    def test_get_progress_nonexistent_job(self, store):
        assert store.get_progress("ghost") is None

    def test_get_progress_after_update(self, store, sample_job_id, sample_session_id, sample_dict_id):
        store.create_job(
            job_id=sample_job_id, session_id=sample_session_id,
            dictionary_id=sample_dict_id, directory_path="/data", job_type="index",
        )
        store.update_job(sample_job_id, processed_dialogues=42)
        assert store.get_progress(sample_job_id) == 42


# ═══════════════════════════════════════════════════════════
# verify_tables_exist
# ═══════════════════════════════════════════════════════════


class TestVerifyTables:
    """Schema verification helper."""

    def test_verify_all_tables_exist(self, store):
        tables = ["mining_jobs", "mining_corpus", "mining_fn_candidates",
                   "mining_audit_results", "mining_checkpoints"]
        result = store.verify_tables_exist(tables)
        for name, exists in result.items():
            assert exists, f"Table {name} should exist but was not found"

    def test_verify_non_existent_table(self, store):
        result = store.verify_tables_exist(["nonexistent_table"])
        assert result["nonexistent_table"] is False

    def test_verify_empty_list_returns_empty(self, store):
        assert store.verify_tables_exist([]) == {}


# ═══════════════════════════════════════════════════════════
# JSON helpers
# ═══════════════════════════════════════════════════════════


class TestJsonHelpers:
    """Static JSON serialization helpers."""

    def test_dump_json_string(self):
        assert MiningStore.dump_json({"a": 1}) == '{"a": 1}'

    def test_dump_json_unicode(self):
        result = MiningStore.dump_json({"text": "привет"})
        assert "привет" in result

    def test_dump_json_fallback(self):
        class Unserializable:
            def __str__(self):
                return "fallback"
        result = MiningStore.dump_json({"obj": Unserializable()})
        assert "fallback" in result

    def test_load_json_valid(self):
        assert MiningStore.load_json('{"key": "value"}') == {"key": "value"}

    def test_load_json_none(self):
        assert MiningStore.load_json(None) is None

    def test_load_json_empty(self):
        assert MiningStore.load_json("") is None

    def test_load_json_invalid(self):
        assert MiningStore.load_json("{invalid}") is None


# ═══════════════════════════════════════════════════════════
# Thread safety
# ═══════════════════════════════════════════════════════════


class TestThreadSafety:
    """Concurrent writes should not corrupt the database."""

    def test_concurrent_job_creation(self):
        """Use tempfile directly to avoid fixture teardown conflict with threads."""
        import gc
        import tempfile
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store = MiningStore(db_path=db_path)
            errors = []

            def create_job_thread(job_id: str):
                try:
                    store.create_job(
                        job_id=job_id, session_id="sess-concurrent",
                        dictionary_id="dict-concurrent",
                        directory_path="/data", job_type="index",
                    )
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=create_job_thread, args=(f"job-concurrent-{i}",))
                       for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
            for t in threads:
                if t.is_alive():
                    errors.append(RuntimeError(f"Thread {t.name} timed out"))

            store.close()
            assert len(errors) == 0, f"Concurrent errors: {errors}"
            # Re-open to verify
            store2 = MiningStore(db_path=db_path)
            for i in range(10):
                assert store2.get_job(f"job-concurrent-{i}") is not None
            store2.close()
            # Force GC to release thread-local connections
            del store
            gc.collect()
        finally:
            for _ in range(3):  # Retry with GC in between
                try:
                    os.unlink(db_path)
                    break
                except PermissionError:
                    gc.collect()
            for ext in ("-wal", "-shm"):
                try:
                    os.unlink(db_path + ext)
                except (FileNotFoundError, PermissionError):
                    pass

    def test_concurrent_reads_and_writes(self):
        """Use tempfile directly to avoid fixture teardown conflict with threads."""
        import gc
        import tempfile
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store = MiningStore(db_path=db_path)
            store.create_job(
                job_id="concurrent-rw-job", session_id="sess-rw",
                dictionary_id="dict-rw", directory_path="/data", job_type="index",
            )
            errors = []

            def reader():
                try:
                    for _ in range(20):
                        store.get_job("concurrent-rw-job")
                except Exception as e:
                    errors.append(e)

            def writer():
                try:
                    for i in range(10):
                        store.update_job("concurrent-rw-job", processed_dialogues=i)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
            for t in threads:
                if t.is_alive():
                    errors.append(RuntimeError(f"Thread {t.name} timed out"))

            store.close()
            del store
            gc.collect()
            assert len(errors) == 0
        finally:
            for _ in range(3):
                try:
                    os.unlink(db_path)
                    break
                except PermissionError:
                    gc.collect()
            for ext in ("-wal", "-shm"):
                try:
                    os.unlink(db_path + ext)
                except (FileNotFoundError, PermissionError):
                    pass


# ═══════════════════════════════════════════════════════════
# Resource management
# ═══════════════════════════════════════════════════════════


class TestResourceManagement:
    """close() and re-initialization."""

    def test_close_is_idempotent(self, store):
        store.close()
        store.close()  # second call must not raise

    def test_reinit_after_close(self, tmp_db_path):
        store = MiningStore(db_path=tmp_db_path)
        store.create_job(
            job_id="reinit-job", session_id="sess-r",
            dictionary_id="dict-r", directory_path="/data", job_type="index",
        )
        store.close()
        # Create a new store on the same path
        store2 = MiningStore(db_path=tmp_db_path)
        job = store2.get_job("reinit-job")
        assert job is not None, "Job should survive store close + reopen"
        store2.close()

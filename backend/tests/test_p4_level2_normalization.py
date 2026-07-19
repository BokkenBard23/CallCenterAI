"""Tests for P4 Level 2 — dictionary table normalization.

Verifies that:
  1. Dictionaries are stored in a separate ``dictionaries`` table, not in
     the ``sessions.data`` JSON blob.
  2. ``session_store.get()`` loads dictionaries from the separate table
     transparently — callers see ``session.dictionaries`` as before.
  3. ``include_dictionaries=False`` returns a Session with empty
     ``dictionaries={}`` (fast path for get_analysis/update_analysis_llm).
  4. ``get_dictionary(session_id, dict_name)`` loads a single dictionary
     by name — O(log N) via UNIQUE index, not O(N) session deserialization.
  5. ``add_dictionary()`` performs a direct INSERT into the dictionaries
     table without rewriting the session JSON blob.
  6. Deleting a session cascades to delete its dictionaries (FOREIGN KEY
     ON DELETE CASCADE).
  7. Dictionary edits (rename, condition changes) are persisted via
     ``update()`` which upserts all dictionaries in one transaction.
  8. ``list_sessions_summary()`` counts dictionaries via SQL LEFT JOIN
     instead of parsing session JSON blobs.
"""

from __future__ import annotations

import os
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    AnalysisResponse,
    DialogueTurn,
    DictionaryCondition,
    DictionaryNode,
    ExtraLimitation,
    ExtraLimitationLimit,
    ParsedDialog,
    SearchResult,
)
from app.services.session_store_sqlite import SqliteSessionStore


# ── Helpers ─────────────────────────────────────────────────


def _make_dialog() -> ParsedDialog:
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(
                speaker="operator", text="Здравствуйте",
                turn_index=0, start_ms=0, end_ms=500,
            ),
            DialogueTurn(
                speaker="client", text="Добрый день",
                turn_index=1, start_ms=600, end_ms=1000,
            ),
        ],
    )


def _make_dictionary(
    name: str = "Тестовый словарь",
    dict_id: str = "test-dict-id",
    num_conditions: int = 5,
) -> DictionaryNode:
    conditions = [
        DictionaryCondition(
            text=f"условие {i}",
            word_distance=2 if i % 2 == 0 else 3,
            is_exact=False if i % 2 == 0 else True,
        )
        for i in range(num_conditions)
    ]
    return DictionaryNode(
        id=dict_id,
        name=name,
        conditions=conditions,
        condition_count=num_conditions,
    )


# ── Tests: dictionary table exists and is separate from sessions.data ──


class TestDictionaryTableNormalization:
    """P4 Level 2: dictionaries stored in a separate table."""

    def test_dictionaries_table_exists_after_init(self, tmp_path) -> None:
        """The ``dictionaries`` table is created by _init_db()."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        conn = store._get_connection()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dictionaries'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "dictionaries"
        store.close()

    def test_foreign_key_cascade_constraint_exists(self, tmp_path) -> None:
        """The dictionaries table has a FK to sessions with ON DELETE CASCADE."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        conn = store._get_connection()
        # sqlite_foreign_key_list returns FK constraints on the table
        fks = conn.execute("PRAGMA foreign_key_list(dictionaries)").fetchall()
        assert len(fks) >= 1
        # Each row: (id, seq, table, from, to, on_update, on_delete, match)
        # We want at least one FK referencing sessions with ON DELETE CASCADE
        cascade_fks = [
            fk for fk in fks if fk[2] == "sessions" and fk[6] == "CASCADE"
        ]
        assert len(cascade_fks) >= 1, (
            f"Expected FK to sessions with CASCADE, got: {fks}"
        )
        store.close()

    def test_dictionaries_not_in_session_json(self, tmp_path) -> None:
        """After add_dictionary, the session JSON blob does NOT contain dictionaries."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск"))

        # Read the raw session JSON from DB
        conn = store._get_connection()
        row = conn.execute(
            "SELECT data FROM sessions WHERE id = ?", ("sess-1",)
        ).fetchone()
        assert row is not None
        blob = json.loads(row[0])
        assert "dictionaries" in blob
        # The dictionaries key should be empty — dictionaries are in the
        # separate table.
        assert blob["dictionaries"] == {}, (
            "dictionaries should be empty in session JSON blob; "
            f"got {len(blob['dictionaries'])} entries"
        )

        # But the dictionaries table should have one row
        dict_rows = conn.execute(
            "SELECT name FROM dictionaries WHERE session_id = ?", ("sess-1",)
        ).fetchall()
        assert len(dict_rows) == 1
        assert dict_rows[0][0] == "Риск"
        store.close()

    def test_get_loads_dictionaries_from_table(self, tmp_path) -> None:
        """session_store.get() transparently loads dictionaries from the table."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        original_dict = _make_dictionary("Риск", num_conditions=10)
        store.add_dictionary("sess-1", original_dict)

        # get() should load dictionaries from the table
        loaded = store.get("sess-1")
        assert loaded is not None
        assert "Риск" in loaded.dictionaries
        loaded_dict = loaded.dictionaries["Риск"]
        assert len(loaded_dict.conditions) == 10
        assert loaded_dict.conditions[0].text == "условие 0"
        store.close()

    def test_get_with_include_dictionaries_false(self, tmp_path) -> None:
        """include_dictionaries=False returns empty dictionaries (fast path)."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск"))

        loaded = store.get("sess-1", include_dictionaries=False)
        assert loaded is not None
        # Dictionaries should be empty — fast path for callers that don't need them
        assert loaded.dictionaries == {}
        # But dialog should still be present (if set)
        store.close()

    def test_get_dictionary_by_name_fast_path(self, tmp_path) -> None:
        """get_dictionary loads a single dict by name without loading all dicts."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=5))
        store.add_dictionary("sess-1", _make_dictionary("Качество", num_conditions=3))

        # get_dictionary should return just the requested dictionary
        result = store.get_dictionary("sess-1", "Риск")
        assert result is not None
        assert result.name == "Риск"
        assert len(result.conditions) == 5

        result2 = store.get_dictionary("sess-1", "Качество")
        assert result2 is not None
        assert result2.name == "Качество"
        assert len(result2.conditions) == 3

        # Non-existent dictionary returns None
        result3 = store.get_dictionary("sess-1", "Несуществующий")
        assert result3 is None
        store.close()

    def test_add_dictionary_is_upsert(self, tmp_path) -> None:
        """add_dictionary on existing name replaces, not duplicates."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=3))
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=7))

        conn = store._get_connection()
        rows = conn.execute(
            "SELECT name FROM dictionaries WHERE session_id = ? AND name = ?",
            ("sess-1", "Риск"),
        ).fetchall()
        assert len(rows) == 1  # no duplicate

        loaded = store.get_dictionary("sess-1", "Риск")
        assert len(loaded.conditions) == 7  # updated version
        store.close()


class TestCascadeDelete:
    """Deleting a session cascades to delete its dictionaries."""

    def test_delete_session_removes_dictionaries(self, tmp_path) -> None:
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск"))
        store.add_dictionary("sess-1", _make_dictionary("Качество"))

        # Verify dictionaries exist
        conn = store._get_connection()
        assert conn.execute(
            "SELECT COUNT(*) FROM dictionaries WHERE session_id = ?", ("sess-1",)
        ).fetchone()[0] == 2

        # Delete session
        deleted = store.delete("sess-1")
        assert deleted is True

        # Dictionaries should be gone (CASCADE)
        assert conn.execute(
            "SELECT COUNT(*) FROM dictionaries WHERE session_id = ?", ("sess-1",)
        ).fetchone()[0] == 0
        store.close()

    def test_delete_nonexistent_session_no_error(self, tmp_path) -> None:
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        deleted = store.delete("nonexistent")
        assert deleted is False
        store.close()


class TestUpdatePersistsDictionaries:
    """update() upserts all dictionaries in a single transaction."""

    def test_update_saves_new_dictionaries(self, tmp_path) -> None:
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        session = store.get("sess-1")
        session.dictionaries["Риск"] = _make_dictionary("Риск", num_conditions=5)
        store.update(session)

        # Reload from a new store instance
        store2 = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        loaded = store2.get("sess-1")
        assert "Риск" in loaded.dictionaries
        assert len(loaded.dictionaries["Риск"].conditions) == 5
        store.close()
        store2.close()

    def test_update_removes_deleted_dictionaries(self, tmp_path) -> None:
        """If a dictionary is removed from session.dictionaries and update()
        is called, the dictionaries table row should be removed too."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск"))
        store.add_dictionary("sess-1", _make_dictionary("Качество"))

        # Remove one dictionary from the session
        session = store.get("sess-1")
        del session.dictionaries["Риск"]
        store.update(session)

        # The dictionaries table should no longer have "Риск"
        loaded = store.get("sess-1")
        assert "Риск" not in loaded.dictionaries
        assert "Качество" in loaded.dictionaries
        store.close()

    def test_update_preserves_dictionary_edits(self, tmp_path) -> None:
        """Editing a condition in a dictionary and calling update() persists the change."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=3))

        # Edit: change condition text
        session = store.get("sess-1")
        session.dictionaries["Риск"].conditions[0].text = "изменённое условие"
        session.dictionaries["Риск"].conditions[1].word_distance = 7
        store.update(session)

        # Reload and verify
        loaded = store.get("sess-1")
        assert loaded.dictionaries["Риск"].conditions[0].text == "изменённое условие"
        assert loaded.dictionaries["Риск"].conditions[1].word_distance == 7
        store.close()


class TestListSessionsSummary:
    """list_sessions_summary counts dictionaries via SQL, not JSON parsing."""

    def test_summary_counts_dictionaries_correctly(self, tmp_path) -> None:
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск"))
        store.add_dictionary("sess-1", _make_dictionary("Качество"))
        store.create("sess-2")
        # sess-2 has no dictionaries

        summaries = store.list_sessions_summary()
        assert len(summaries) == 2

        s1 = next(s for s in summaries if s["session_id"] == "sess-1")
        assert s1["has_dictionary"] is True
        assert s1["dictionary_count"] == 2

        s2 = next(s for s in summaries if s["session_id"] == "sess-2")
        assert s2["has_dictionary"] is False
        assert s2["dictionary_count"] == 0
        store.close()

    def test_summary_does_not_load_dictionaries_json(self, tmp_path) -> None:
        """The session JSON blob should NOT contain dictionaries (they're in
        a separate table). list_sessions_summary should still report the
        correct count via SQL JOIN."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=50))

        # Verify session JSON blob has empty dictionaries
        conn = store._get_connection()
        blob = json.loads(
            conn.execute("SELECT data FROM sessions WHERE id = 'sess-1'").fetchone()[0]
        )
        assert blob["dictionaries"] == {}

        # But summary should still report count=1 via SQL
        summaries = store.list_sessions_summary()
        s1 = summaries[0]
        assert s1["dictionary_count"] == 1
        store.close()


class TestGetAnalysisWithoutDictionaries:
    """get_analysis does NOT load dictionaries — fast path."""

    def test_get_analysis_finds_analysis_without_loading_dictionaries(
        self, tmp_path
    ) -> None:
        """get_analysis should find an analysis by ID without loading the
        multi-MB dictionary payloads."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=100))

        # Add an analysis
        analysis = AnalysisResponse(
            analysis_id="anal-1",
            session_id="sess-1",
            status="completed",
            search_result=SearchResult(
                segments=[], total_matches=3, matches=[], matches_by_level={"1": 3},
            ),
        )
        store.add_analysis("sess-1", analysis)

        # get_analysis should find it
        found = store.get_analysis("anal-1")
        assert found is not None
        assert found.analysis_id == "anal-1"
        assert found.search_result.total_matches == 3
        store.close()

    def test_get_analysis_returns_none_for_missing(self, tmp_path) -> None:
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        found = store.get_analysis("nonexistent")
        assert found is None
        store.close()


class TestUpdateAnalysisLLMWithoutDictionaries:
    """update_analysis_llm uses include_dictionaries=False — fast path."""

    def test_update_analysis_llm_without_loading_dictionaries(self, tmp_path) -> None:
        from app.models import LLMResult

        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary("Риск", num_conditions=100))

        analysis = AnalysisResponse(
            analysis_id="anal-1",
            session_id="sess-1",
            status="completed",
            search_result=SearchResult(
                segments=[], total_matches=1, matches=[], matches_by_level={"1": 1},
            ),
        )
        store.add_analysis("sess-1", analysis)

        new_llm = LLMResult(
            provider="beeline", model="m1",
            summary="тестовая сводка", restructured_dialogue="",
        )
        updated = store.update_analysis_llm(
            analysis_id="anal-1",
            llm_result=new_llm,
            status="completed",
        )
        assert updated is not None
        assert updated.llm_result is not None
        assert updated.llm_result.summary == "тестовая сводка"

        # Verify persistence: reload via get_analysis
        reloaded = store.get_analysis("anal-1")
        assert reloaded is not None
        assert reloaded.llm_result is not None
        assert reloaded.llm_result.summary == "тестовая сводка"
        # And the original search_result is preserved
        assert reloaded.search_result is not None
        assert reloaded.search_result.total_matches == 1
        store.close()


class TestLargeDictionaryPerformance:
    """Smoke test: a large dictionary (500 conditions) round-trips through
    the normalized table."""

    def test_large_dictionary_round_trip(self, tmp_path) -> None:
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        big_dict = _make_dictionary("Большой словарь", num_conditions=500)
        store.add_dictionary("sess-1", big_dict)

        # Reload from a new store instance (simulates server restart)
        store2 = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        loaded = store2.get("sess-1")
        assert "Большой словарь" in loaded.dictionaries
        loaded_dict = loaded.dictionaries["Большой словарь"]
        assert len(loaded_dict.conditions) == 500
        # Defaults restored
        assert loaded_dict.conditions[0].word_distance == 2
        store.close()
        store2.close()

    def test_session_json_size_is_small_without_dictionaries(self, tmp_path) -> None:
        """The session JSON blob should be small even with a large dictionary,
        because dictionaries are stored in the separate table."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary(
            "sess-1", _make_dictionary("Большой словарь", num_conditions=500)
        )

        conn = store._get_connection()
        blob_size = len(
            conn.execute("SELECT data FROM sessions WHERE id = 'sess-1'").fetchone()[0]
        )
        # The session JSON should be small — no dictionary data in it.
        # A 500-condition dictionary would be ~50KB in JSON, but the session
        # blob should be < 5KB (just dialog + analyses + metadata).
        assert blob_size < 5000, (
            f"Session JSON blob is {blob_size} bytes — expected < 5000 "
            "(dictionaries should be in separate table)"
        )
        store.close()

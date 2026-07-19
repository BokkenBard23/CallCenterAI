"""Tests for P4 Level 1 — JSON serialization optimization.

Verifies:
  1. ``serialize_session()`` uses ``exclude_defaults=True, exclude_none=True``
     and produces a smaller JSON payload than the unoptimized path.
  2. Round-trip (serialize → deserialize) preserves all data — defaults
     are restored by Pydantic on construction.
  3. GZipMiddleware is registered on the FastAPI app (gzip.responses > 100 KB).
  4. End-to-end: a session with a non-trivial dictionary survives
     SQLite persistence and retrieval with identical semantic content.
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    AnalysisResponse,
    DictionaryCondition,
    DictionaryNode,
    ExtraLimitation,
    ExtraLimitationLimit,
    ParsedDialog,
    DialogueTurn,
    SearchResult,
)
from app.services.session_store_base import (
    Session,
    deserialize_session,
    serialize_session,
)
from app.services.session_store_sqlite import SqliteSessionStore


# ── Fixtures ─────────────────────────────────────────────────


def _make_dictionary_with_defaults(name: str = "Тестовый словарь") -> DictionaryNode:
    """Build a DictionaryNode where many fields equal their model defaults.

    Such fields should be stripped by ``exclude_defaults=True`` and
    restored by Pydantic on load.
    """
    conditions = [
        DictionaryCondition(
            text="условие один",
            word_distance=2,            # default value → stripped
            is_exact=False,             # default value → stripped
            extra_limitations=[],
        ),
        DictionaryCondition(
            text="условие два",
            word_distance=3,            # non-default → kept
            is_exact=True,              # non-default → kept
            extra_limitations=[
                ExtraLimitation(
                    type="open",
                    limits=[
                        ExtraLimitationLimit(value=1, value_type="Seconds"),
                        ExtraLimitationLimit(value=0, value_type="Seconds"),  # default-ish
                    ],
                ),
            ],
        ),
    ]
    return DictionaryNode(
        id="test-dict-id",
        name=name,
        conditions=conditions,
        condition_count=len(conditions),
        has_children=False,            # default → stripped
        children_count=0,              # default → stripped
    )


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


# ── Tests: exclude_defaults reduces size ─────────────────────


class TestExcludeDefaults:
    """P4 Level 1: serialization strips defaults and restores them on load."""

    def test_serialized_payload_excludes_default_fields(self) -> None:
        """JSON output should NOT contain fields whose value equals the default."""
        session = Session(dialog=_make_dialog())
        session.dictionaries["test"] = _make_dictionary_with_defaults()

        payload = serialize_session(session)
        # The raw payload must be valid JSON
        raw = json.loads(payload)

        # Inspect the first condition of the stored dictionary.
        cond0 = raw["dictionaries"]["test"]["conditions"][0]
        # `word_distance` default is 2 → must be stripped
        assert "word_distance" not in cond0, (
            "exclude_defaults=True failed: word_distance=2 should have been stripped"
        )
        # `is_exact` default is False → must be stripped
        assert "is_exact" not in cond0, (
            "exclude_defaults=True failed: is_exact=False should have been stripped"
        )
        # `extra_limitations` default is [] → must be stripped
        assert "extra_limitations" not in cond0

    def test_serialized_payload_keeps_non_default_fields(self) -> None:
        """Non-default values must survive serialization."""
        session = Session(dialog=_make_dialog())
        session.dictionaries["test"] = _make_dictionary_with_defaults()

        raw = json.loads(serialize_session(session))
        cond1 = raw["dictionaries"]["test"]["conditions"][1]

        # word_distance=3 (non-default 2) → kept
        assert cond1.get("word_distance") == 3
        # is_exact=True (non-default False) → kept
        assert cond1.get("is_exact") is True
        # extra_limitations with content → kept
        assert len(cond1.get("extra_limitations", [])) == 1

    def test_serialization_size_smaller_than_naive_dump(self) -> None:
        """serialize_session output must be smaller than model_dump() without flags."""
        session = Session(dialog=_make_dialog())
        session.dictionaries["test"] = _make_dictionary_with_defaults()

        optimized = serialize_session(session)

        # Naive (unoptimized) serialization
        naive_data = {
            "id": session.id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "dialog": session.dialog.model_dump(mode="json") if session.dialog else None,
            "dictionaries": {
                k: v.model_dump(mode="json") for k, v in session.dictionaries.items()
            },
            "analyses": {
                k: v.model_dump(mode="json") for k, v in session.analyses.items()
            },
            "metadata": session.metadata,
        }
        naive = json.dumps(naive_data, ensure_ascii=False)

        assert len(optimized) < len(naive), (
            f"Optimized payload ({len(optimized)} bytes) should be smaller than "
            f"naive ({len(naive)} bytes)"
        )

    def test_roundtrip_preserves_semantic_data(self) -> None:
        """serialize → deserialize must produce an equivalent Session."""
        session = Session(dialog=_make_dialog())
        session.dictionaries["test"] = _make_dictionary_with_defaults()

        restored = deserialize_session(serialize_session(session))

        # Dialog round-trips
        assert restored.dialog is not None
        assert len(restored.dialog.turns) == 2

        # Dictionary round-trips with all defaults restored
        d = restored.dictionaries["test"]
        assert d.name == "Тестовый словарь"
        assert len(d.conditions) == 2

        # Condition 0: defaults restored
        c0 = d.conditions[0]
        assert c0.word_distance == 2          # default restored
        assert c0.is_exact is False             # default restored
        assert c0.extra_limitations == []       # default restored

        # Condition 1: non-defaults preserved
        c1 = d.conditions[1]
        assert c1.word_distance == 3
        assert c1.is_exact is True
        assert len(c1.extra_limitations) == 1


# ── Tests: GZipMiddleware registered ─────────────────────────


class TestGZipMiddleware:
    """P4 Level 1: GZipMiddleware compresses responses larger than 100 KB."""

    def test_gzip_middleware_present_on_app(self) -> None:
        """GZipMiddleware must be added to the FastAPI app's middleware stack."""
        from app.main import app

        # Starlette stores middleware as a list of Middleware instances.
        middleware_classes = [
            m.cls.__name__ if hasattr(m, "cls") else m.__class__.__name__
            for m in app.user_middleware
        ]
        assert "GZipMiddleware" in middleware_classes, (
            "GZipMiddleware not registered; user_middleware: "
            f"{middleware_classes}"
        )

    def test_large_response_is_gzipped(self, tmp_path) -> None:
        """A response > 100 KB should be served with Content-Encoding: gzip."""
        from app.main import app
        from app.utils.session import session_store

        # Build a session with a large dictionary payload
        conditions = [
            DictionaryCondition(
                text=f"условие номер {i} " * 20,
                word_distance=2,
                is_exact=False,
            )
            for i in range(500)
        ]
        big_dict = DictionaryNode(
            id="big-dict-id",
            name="Большой словарь",
            conditions=conditions,
            condition_count=len(conditions),
        )
        session = Session(dialog=_make_dialog())
        session.dictionaries[big_dict.name] = big_dict
        session_store.create(session.id) if hasattr(session_store, "create") else None
        # Use session_store.update (works for both memory and sqlite backends)
        from app.services.session_store_base import Session as S
        # Register the session by direct create+update
        try:
            session_store.update(session)
        except Exception:
            # Some backends require create() first
            session_store.create(session.id)
            session_store.update(session)

        client = TestClient(app)
        response = client.get(
            f"/api/dictionary/{session.id}",
            headers={"Accept-Encoding": "gzip"},
        )

        # The endpoint must return 200
        assert response.status_code == 200, response.text

        # The body must be large enough to trigger gzip (>100 KB)
        assert len(response.content) > 100 * 1024 or response.headers.get("content-encoding") == "gzip", (
            "Expected either > 100 KB body or gzip Content-Encoding header; got "
            f"{response.headers.get('content-encoding')}, body={len(response.content)} bytes"
        )

        # When the response is gzipped, the Content-Encoding header is set
        if len(response.content) < 5 * 1024 * 1024:  # only assert when body is reasonably sized
            assert response.headers.get("content-encoding") == "gzip"


# ── Tests: SQLite persistence with optimized serialization ───


class TestSqlitePersistenceWithExcludeDefaults:
    """SQLite backend must survive the optimized serialization round-trip."""

    def test_large_dictionary_persists_and_reloads(self, tmp_path) -> None:
        """A session with a big dictionary must round-trip through SQLite."""
        db_path = str(tmp_path / "test_p4.db")
        store = SqliteSessionStore(db_path=db_path, max_sessions=10)

        conditions = [
            DictionaryCondition(
                text=f"phrase {i}",
                word_distance=2,            # default
                is_exact=False,            # default
            )
            for i in range(200)
        ]
        big_dict = DictionaryNode(
            id="big-dict-id-3",
            name="Риск",
            conditions=conditions,
            condition_count=len(conditions),
        )
        session = Session(dialog=_make_dialog())
        session.dictionaries[big_dict.name] = big_dict

        store.create(session.id)
        store.update(session)

        # Force reload from a NEW store instance (simulates restart)
        store2 = SqliteSessionStore(db_path=db_path, max_sessions=10)
        loaded = store2.get(session.id)

        assert loaded is not None
        assert big_dict.name in loaded.dictionaries
        loaded_dict = loaded.dictionaries[big_dict.name]
        assert len(loaded_dict.conditions) == 200
        # Defaults restored
        c0 = loaded_dict.conditions[0]
        assert c0.word_distance == 2
        assert c0.is_exact is False

    def test_optimized_payload_smaller_in_db(self, tmp_path) -> None:
        """The actual TEXT stored in DB must be smaller than naive dump."""
        db_path = str(tmp_path / "test_p4_size.db")
        store = SqliteSessionStore(db_path=db_path, max_sessions=10)

        conditions = [
            DictionaryCondition(
                text=f"phrase {i}",
                word_distance=2,
                is_exact=False,
            )
            for i in range(200)
        ]
        big_dict = DictionaryNode(
            id="big-dict-id-2",
            name="Риск",
            conditions=conditions,
            condition_count=len(conditions),
        )
        session = Session(dialog=_make_dialog())
        session.dictionaries[big_dict.name] = big_dict

        store.create(session.id)
        store.update(session)

        # Read raw data column from DB
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT data FROM sessions WHERE id = ?", (session.id,)
        ).fetchone()
        conn.close()

        assert row is not None
        stored_text = row[0]

        # Build naive (unoptimized) payload for comparison
        naive_data = {
            "id": session.id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "dialog": session.dialog.model_dump(mode="json") if session.dialog else None,
            "dictionaries": {
                k: v.model_dump(mode="json") for k, v in session.dictionaries.items()
            },
            "analyses": {
                k: v.model_dump(mode="json") for k, v in session.analyses.items()
            },
            "metadata": session.metadata,
        }
        naive_text = json.dumps(naive_data, ensure_ascii=False)

        # The stored (optimized) text must be smaller than naive
        assert len(stored_text) < len(naive_text), (
            f"Optimized DB payload ({len(stored_text)} bytes) should be smaller "
            f"than naive ({len(naive_text)} bytes)"
        )

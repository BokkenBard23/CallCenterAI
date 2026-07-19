"""Tests for P4 Level 2.5 — gzip-compressed BLOB storage.

Verifies that:
  1. Dictionary nodes are stored as gzip-compressed BLOBs (not plain TEXT).
  2. The compressed BLOB is significantly smaller than the naive JSON.
  3. Round-trip preserves all data (compression is lossless).
  4. A large dictionary (500 conditions) compresses well.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    DictionaryCondition,
    DictionaryNode,
)
from app.services.session_store_sqlite import (
    SqliteSessionStore,
    _deserialize_dict,
    _serialize_dict,
)


def _make_dictionary(num_conditions: int = 10) -> DictionaryNode:
    conditions = [
        DictionaryCondition(
            text=f"условие номер {i} " * 5,
            word_distance=2 if i % 2 == 0 else 3,
            is_exact=False if i % 2 == 0 else True,
        )
        for i in range(num_conditions)
    ]
    return DictionaryNode(
        id=f"dict-{num_conditions}",
        name=f"Словарь {num_conditions}",
        conditions=conditions,
        condition_count=num_conditions,
    )


# ── Tests: _serialize_dict / _deserialize_dict helpers ─────


class TestSerializeDictHelpers:
    def test_serialize_returns_gzip_bytes(self) -> None:
        """_serialize_dict returns bytes that gzip.decompress can decode."""
        node = _make_dictionary(5)
        blob = _serialize_dict(node)
        assert isinstance(blob, bytes)
        # Should be valid gzip — gzip magic number 0x1f 0x8b
        assert blob[:2] == b"\x1f\x8b"

    def test_round_trip_preserves_data(self) -> None:
        """_deserialize_dict(_serialize_dict(node)) returns an equivalent node."""
        original = _make_dictionary(20)
        blob = _serialize_dict(original)
        restored = _deserialize_dict(blob)

        assert restored.name == original.name
        assert len(restored.conditions) == len(original.conditions)
        for orig_cond, rest_cond in zip(original.conditions, restored.conditions):
            assert rest_cond.text == orig_cond.text
            assert rest_cond.word_distance == orig_cond.word_distance
            assert rest_cond.is_exact == orig_cond.is_exact

    def test_compressed_smaller_than_naive_json(self) -> None:
        """The gzip BLOB must be smaller than the naive JSON string."""
        node = _make_dictionary(100)
        blob = _serialize_dict(node)
        naive_json = node.model_dump_json(
            exclude_defaults=True, exclude_none=True
        ).encode("utf-8")

        assert len(blob) < len(naive_json), (
            f"Compressed ({len(blob)} bytes) should be smaller than "
            f"naive JSON ({len(naive_json)} bytes)"
        )

    def test_large_dictionary_compresses_well(self) -> None:
        """A 500-condition dictionary should compress to < 30% of naive JSON."""
        node = _make_dictionary(500)
        blob = _serialize_dict(node)
        naive_json = node.model_dump_json(
            exclude_defaults=True, exclude_none=True
        ).encode("utf-8")

        ratio = len(blob) / len(naive_json)
        assert ratio < 0.30, (
            f"Compression ratio {ratio:.2%} — expected < 30% for a large dictionary"
        )


# ── Tests: BLOB storage in DB ──────────────────────────────


class TestBlobStorageInDB:
    def test_dictionary_stored_as_blob_not_text(self, tmp_path) -> None:
        """The node_blob column holds binary gzip data, not plain JSON text."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        store.add_dictionary("sess-1", _make_dictionary(10))

        # Read raw bytes from the DB
        conn = store._get_connection()
        row = conn.execute(
            "SELECT node_blob FROM dictionaries WHERE session_id = ? AND name = ?",
            ("sess-1", f"Словарь {10}"),
        ).fetchone()
        assert row is not None
        blob = row[0]
        assert isinstance(blob, bytes)
        # gzip magic number
        assert blob[:2] == b"\x1f\x8b"
        store.close()

    def test_blob_size_smaller_than_naive_text(self, tmp_path) -> None:
        """The BLOB stored in DB is smaller than the naive JSON TEXT would be."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        node = _make_dictionary(200)
        store.add_dictionary("sess-1", node)

        conn = store._get_connection()
        row = conn.execute(
            "SELECT node_blob FROM dictionaries WHERE session_id = ? AND name = ?",
            ("sess-1", node.name),
        ).fetchone()
        blob_size = len(row[0])

        # What naive TEXT storage would have been:
        naive_text = node.model_dump_json(
            exclude_defaults=True, exclude_none=True
        )
        naive_size = len(naive_text.encode("utf-8"))

        assert blob_size < naive_size, (
            f"DB BLOB ({blob_size} bytes) should be smaller than "
            f"naive TEXT ({naive_size} bytes)"
        )

    def test_large_dictionary_round_trip_through_db(self, tmp_path) -> None:
        """A 500-condition dictionary round-trips through BLOB storage."""
        store = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        store.create("sess-1")
        original = _make_dictionary(500)
        store.add_dictionary("sess-1", original)

        # Reload from a new store
        store2 = SqliteSessionStore(db_path=str(tmp_path / "test.db"))
        loaded = store2.get_dictionary("sess-1", original.name)
        assert loaded is not None
        assert len(loaded.conditions) == 500
        assert loaded.conditions[0].text == original.conditions[0].text
        store.close()
        store2.close()

    def test_db_size_with_compressed_blobs(self, tmp_path) -> None:
        """The actual BLOB data stays small even with large dictionaries (gzip).

        Note: the DB file size includes SQLite page overhead (16 KB page_size,
        WAL, indexes) — so we check the SUM of node_blob lengths, not the file
        size. The gzip BLOB payload should be < 20 KB for 5×100-condition dicts.
        """
        db_path = str(tmp_path / "test.db")
        store = SqliteSessionStore(db_path=db_path)
        store.create("sess-1")
        # Add 5 large dictionaries (same name to avoid UNIQUE conflict)
        for i in range(5):
            node = _make_dictionary(100)
            node.name = f"Словарь {i}"
            store.add_dictionary("sess-1", node)
        store.close()

        # Re-open and measure the actual BLOB payload sizes
        store2 = SqliteSessionStore(db_path=db_path)
        conn = store2._get_connection()
        rows = conn.execute(
            "SELECT LENGTH(node_blob) FROM dictionaries WHERE session_id = ?",
            ("sess-1",),
        ).fetchall()
        store2.close()

        total_blob_bytes = sum(r[0] for r in rows)
        # 5×100-condition dicts with exclude_defaults + gzip should be < 20 KB
        # (naive JSON would be ~50 KB)
        assert total_blob_bytes < 20_000, (
            f"Total BLOB payload is {total_blob_bytes} bytes — expected < 20 KB "
            "with gzip compression"
        )
        assert len(rows) == 5

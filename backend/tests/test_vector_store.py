"""Tests for VectorStore service (FAISS-based vector store).

Covers:
  - Add + search → finds nearest vector
  - Add batch → all vectors accessible for search
  - Delete by dialogue → vectors removed, rollback on error
  - Save + load → persists and restores correctly
  - Empty store → search returns []
  - Metadata correct in search results
  - L2 normalization: cosine similarity correct (score ∈ [0, 1])
  - Performance: 1000 vectors search < 100ms
  - Transaction rollback: delete fails → metadata restored
  - VectorSearchResult entities populated from metadata
  - Validation: mismatched embeddings/metadata raises ValueError
  - Validation: wrong dimension raises ValueError
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.models import VectorSearchResult
from app.services.vector_store import VectorStore, VectorStoreMigration


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

DIMENSION = 1536


def _random_vector(seed: int = 42) -> List[float]:
    """Generate a random L2-normalized vector for testing."""
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(DIMENSION).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def _random_embeddings(count: int, seed_start: int = 0) -> List[List[float]]:
    """Generate multiple random L2-normalized vectors."""
    return [_random_vector(seed=seed_start + i) for i in range(count)]


def _sample_metadata(
    count: int,
    dialogue_id: str = "dialogue-1",
    chunk_type: str = "utterance",
    entities: bool = False,
) -> List[Dict[str, Any]]:
    """Generate sample metadata for testing."""
    result = []
    for i in range(count):
        meta: Dict[str, Any] = {
            "chunk_id": f"chunk-{uuid.uuid4().hex[:8]}",
            "dialogue_id": dialogue_id,
            "turn_index": i,
            "speaker": "Клиент" if i % 2 == 0 else "Сотрудник",
            "text": f"Sample text for chunk {i}",
            "chunk_type": chunk_type,
        }
        if entities:
            meta["entities"] = [
                {"text": f"Entity{i}", "type": "PER", "normal": f"entity{i}"},
            ]
        else:
            meta["entities"] = []
        result.append(meta)
    return result


# ═══════════════════════════════════════════════════════════
# Test: Add + Search
# ═══════════════════════════════════════════════════════════


class TestAddAndSearch:
    """Test adding vectors and searching for nearest neighbors."""

    def test_add_and_search_finds_nearest(self) -> None:
        """Add vectors and search → finds the nearest vector."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        # Create a known vector
        target_vec = _random_vector(seed=100)
        metadata = _sample_metadata(1, dialogue_id="d1")
        store.add([target_vec], metadata)

        # Add some other vectors
        other_vecs = _random_embeddings(5, seed_start=200)
        other_meta = _sample_metadata(5, dialogue_id="d2")
        store.add(other_vecs, other_meta)

        # Search with the target vector → should find itself as top result
        results = store.search(target_vec, k=3)

        assert len(results) >= 1
        assert results[0].dialogue_id == "d1"
        assert results[0].score > 0.99  # Should be nearly identical to itself

    def test_add_single_vector_searchable(self) -> None:
        """Add a single vector → search finds it."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        vec = _random_vector(seed=42)
        meta = _sample_metadata(1, dialogue_id="single")
        store.add([vec], meta)

        results = store.search(vec, k=1)
        assert len(results) == 1
        assert results[0].score > 0.99

    def test_search_returns_sorted_by_score(self) -> None:
        """Search results are sorted by cosine similarity (descending)."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        # Add multiple vectors
        vecs = _random_embeddings(5, seed_start=300)
        metas = _sample_metadata(5, dialogue_id="sorted")
        store.add(vecs, metas)

        # Search with a random query
        query = _random_vector(seed=999)
        results = store.search(query, k=5)

        # Verify sorted descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


# ═══════════════════════════════════════════════════════════
# Test: Add batch
# ═══════════════════════════════════════════════════════════


class TestAddBatch:
    """Test batch adding of vectors."""

    def test_add_batch_all_accessible(self) -> None:
        """Add a batch of vectors → all are accessible via search."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(10, seed_start=400)
        metas = _sample_metadata(10, dialogue_id="batch")
        store.add(vecs, metas)

        assert store.index.ntotal == 10
        assert store.get_stats()["total_vectors"] == 10

        # Each vector should find itself as the nearest
        for i, vec in enumerate(vecs):
            results = store.search(vec, k=1)
            assert len(results) == 1
            assert results[0].turn_index == i

    def test_add_empty_list_noop(self) -> None:
        """Adding empty embeddings list is a no-op."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        store.add([], [])

        assert store.index.ntotal == 0
        assert store.get_stats()["total_vectors"] == 0

    def test_add_multiple_batches(self) -> None:
        """Multiple batch adds accumulate correctly."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        for batch_idx in range(3):
            vecs = _random_embeddings(5, seed_start=batch_idx * 100)
            metas = _sample_metadata(5, dialogue_id=f"batch-{batch_idx}")
            store.add(vecs, metas)

        assert store.index.ntotal == 15
        assert store.get_stats()["total_vectors"] == 15
        assert store.get_stats()["unique_dialogues"] == 3


# ═══════════════════════════════════════════════════════════
# Test: Delete by dialogue
# ═══════════════════════════════════════════════════════════


class TestDeleteByDialogue:
    """Test deletion of vectors by dialogue_id."""

    def test_delete_removes_vectors(self) -> None:
        """Delete by dialogue_id removes all vectors for that dialogue."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        # Add vectors for two dialogues
        vecs1 = _random_embeddings(3, seed_start=500)
        metas1 = _sample_metadata(3, dialogue_id="delete-me")
        store.add(vecs1, metas1)

        vecs2 = _random_embeddings(4, seed_start=600)
        metas2 = _sample_metadata(4, dialogue_id="keep-me")
        store.add(vecs2, metas2)

        assert store.index.ntotal == 7

        # Delete one dialogue
        deleted = store.delete_by_dialogue("delete-me")
        assert deleted == 3
        assert store.index.ntotal == 4
        assert store.get_stats()["total_vectors"] == 4
        assert store.get_stats()["unique_dialogues"] == 1

    def test_delete_nonexistent_dialogue_returns_zero(self) -> None:
        """Deleting a non-existent dialogue_id returns 0."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        vecs = _random_embeddings(3, seed_start=700)
        metas = _sample_metadata(3, dialogue_id="exists")
        store.add(vecs, metas)

        deleted = store.delete_by_dialogue("nonexistent")
        assert deleted == 0
        assert store.index.ntotal == 3

    def test_delete_all_vectors_results_in_empty_store(self) -> None:
        """Deleting all vectors results in empty store."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        vecs = _random_embeddings(5, seed_start=800)
        metas = _sample_metadata(5, dialogue_id="all-delete")
        store.add(vecs, metas)

        deleted = store.delete_by_dialogue("all-delete")
        assert deleted == 5
        assert store.index.ntotal == 0
        assert store.get_stats()["total_vectors"] == 0
        assert store.get_stats()["unique_dialogues"] == 0

    def test_delete_rollback_on_error(self) -> None:
        """If deletion fails, metadata and index are rolled back."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(3, seed_start=900)
        metas = _sample_metadata(3, dialogue_id="rollback-test")
        store.add(vecs, metas)

        original_count = store.index.ntotal
        original_metadata_len = len(store._metadata)

        # Patch the rebuild method to raise an error
        with patch.object(
            store, "_rebuild_index_without", side_effect=RuntimeError("Rebuild error")
        ):
            with pytest.raises(RuntimeError, match="Rebuild error"):
                store.delete_by_dialogue("rollback-test")

        # Verify rollback: state should be unchanged
        assert store.index.ntotal == original_count
        assert len(store._metadata) == original_metadata_len
        assert store.get_stats()["total_vectors"] == 3


# ═══════════════════════════════════════════════════════════
# Test: Save + Load
# ═══════════════════════════════════════════════════════════


class TestSaveAndLoad:
    """Test persistence of index and metadata."""

    def test_save_and_load_roundtrip(self) -> None:
        """Save + load → index and metadata are restored correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(dimension=DIMENSION, auto_save=False)

            vecs = _random_embeddings(5, seed_start=1000)
            metas = _sample_metadata(5, dialogue_id="persist-test", entities=True)
            store.add(vecs, metas)

            # Save
            store.save(tmpdir)

            # Verify files exist
            assert os.path.exists(os.path.join(tmpdir, "index.faiss"))
            assert os.path.exists(os.path.join(tmpdir, "metadata.json"))
            assert os.path.exists(os.path.join(tmpdir, "chunk_id_map.json"))

            # Load into a new store
            store2 = VectorStore(dimension=DIMENSION, auto_save=False)
            store2.load(tmpdir)

            assert store2.index.ntotal == 5
            assert store2.get_stats()["total_vectors"] == 5
            assert len(store2._metadata) == 5
            assert len(store2._chunk_id_to_idx) == 5

            # Search should work on loaded store
            results = store2.search(vecs[0], k=1)
            assert len(results) == 1
            assert results[0].dialogue_id == "persist-test"

    def test_save_creates_parent_directories(self) -> None:
        """Save creates parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "nested", "dir")
            store = VectorStore(dimension=DIMENSION, auto_save=False)

            vecs = _random_embeddings(1, seed_start=1100)
            metas = _sample_metadata(1, dialogue_id="nested")
            store.add(vecs, metas)

            store.save(nested_path)
            assert os.path.exists(os.path.join(nested_path, "index.faiss"))

    def test_load_missing_files_raises_error(self) -> None:
        """Loading from a path without required files raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(dimension=DIMENSION, auto_save=False)
            with pytest.raises(FileNotFoundError):
                store.load(tmpdir)

    def test_save_and_load_preserves_metadata(self) -> None:
        """Metadata (including entities) is preserved through save/load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(dimension=DIMENSION, auto_save=False)

            meta = _sample_metadata(1, dialogue_id="meta-test", entities=True)
            vecs = _random_embeddings(1, seed_start=1200)
            store.add(vecs, meta)

            store.save(tmpdir)

            store2 = VectorStore(dimension=DIMENSION, auto_save=False)
            store2.load(tmpdir)

            results = store2.search(vecs[0], k=1)
            assert len(results) == 1
            assert len(results[0].entities) == 1
            assert results[0].entities[0]["type"] == "PER"

    def test_save_and_load_preserves_multiple_dialogues(self) -> None:
        """Multiple dialogues are preserved through save/load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(dimension=DIMENSION, auto_save=False)

            for d in range(3):
                vecs = _random_embeddings(3, seed_start=d * 50 + 1300)
                metas = _sample_metadata(3, dialogue_id=f"dialogue-{d}")
                store.add(vecs, metas)

            store.save(tmpdir)

            store2 = VectorStore(dimension=DIMENSION, auto_save=False)
            store2.load(tmpdir)

            assert store2.get_stats()["total_vectors"] == 9
            assert store2.get_stats()["unique_dialogues"] == 3


# ═══════════════════════════════════════════════════════════
# Test: Empty store
# ═══════════════════════════════════════════════════════════


class TestEmptyStore:
    """Test behavior of an empty vector store."""

    def test_empty_store_search_returns_empty(self) -> None:
        """Searching an empty store returns an empty list."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        query = _random_vector(seed=42)
        results = store.search(query, k=5)
        assert results == []

    def test_empty_store_stats(self) -> None:
        """Empty store has zero stats."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        stats = store.get_stats()
        assert stats["total_vectors"] == 0
        assert stats["unique_dialogues"] == 0
        assert stats["index_size_bytes"] == 0


# ═══════════════════════════════════════════════════════════
# Test: Metadata correctness
# ═══════════════════════════════════════════════════════════


class TestMetadataCorrectness:
    """Test that search results contain correct metadata."""

    def test_search_result_has_all_fields(self) -> None:
        """VectorSearchResult has all expected fields populated."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vec = _random_vector(seed=42)
        meta: Dict[str, Any] = {
            "chunk_id": "test-chunk-123",
            "dialogue_id": "test-dialogue-456",
            "turn_index": 5,
            "speaker": "Клиент",
            "text": "Hello, I need help",
            "chunk_type": "utterance",
            "entities": [{"text": "Moscow", "type": "LOC", "normal": "москва"}],
        }
        store.add([vec], [meta])

        results = store.search(vec, k=1)
        assert len(results) == 1

        r = results[0]
        assert r.chunk_id == "test-chunk-123"
        assert r.dialogue_id == "test-dialogue-456"
        assert r.turn_index == 5
        assert r.speaker == "Клиент"
        assert r.text == "Hello, I need help"
        assert r.chunk_type == "utterance"
        assert len(r.entities) == 1
        assert r.entities[0]["text"] == "Moscow"
        assert r.entities[0]["type"] == "LOC"

    def test_entities_populated_from_metadata(self) -> None:
        """VectorSearchResult entities are populated from metadata."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vec = _random_vector(seed=55)
        entities = [
            {"text": "Иванов", "type": "PER", "normal": "иванов"},
            {"text": "Москва", "type": "LOC", "normal": "москва"},
            {"text": "Билайн", "type": "ORG", "normal": "билайн"},
        ]
        meta: Dict[str, Any] = {
            "chunk_id": "ner-chunk",
            "dialogue_id": "ner-dialogue",
            "turn_index": 0,
            "speaker": "Клиент",
            "text": "Иванов из Москвы звонит в Билайн",
            "chunk_type": "utterance",
            "entities": entities,
        }
        store.add([vec], [meta])

        results = store.search(vec, k=1)
        assert len(results[0].entities) == 3
        assert results[0].entities[0]["type"] == "PER"
        assert results[0].entities[1]["type"] == "LOC"
        assert results[0].entities[2]["type"] == "ORG"


# ═══════════════════════════════════════════════════════════
# Test: L2 normalization
# ═══════════════════════════════════════════════════════════


class TestL2Normalization:
    """Test L2 normalization and cosine similarity correctness."""

    def test_normalize_produces_unit_vectors(self) -> None:
        """L2 normalization produces vectors with unit norm."""
        vecs = _random_embeddings(10, seed_start=2000)
        normalized = VectorStore._normalize(vecs)

        # Each normalized vector should have norm ≈ 1.0
        norms = np.linalg.norm(normalized, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_normalize_zero_vector_no_division_by_zero(self) -> None:
        """L2 normalization handles zero vectors without error."""
        zero_vec = [0.0] * DIMENSION
        normalized = VectorStore._normalize([zero_vec])

        # Should not raise; norm of the result should be 0 (0/1 = 0)
        assert np.all(np.isfinite(normalized))

    def test_cosine_similarity_score_range(self) -> None:
        """Cosine similarity scores are in [0, 1] for normalized vectors."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(20, seed_start=2100)
        metas = _sample_metadata(20, dialogue_id="sim-range")
        store.add(vecs, metas)

        query = _random_vector(seed=9999)
        results = store.search(query, k=20)

        for r in results:
            # Cosine similarity of normalized vectors can be negative in theory,
            # but for typical FRIDA embeddings it's positive.
            # We check [-1, 1] for mathematical correctness.
            assert -1.0 <= r.score <= 1.0, f"Score {r.score} out of range"

    def test_identical_vector_has_score_near_one(self) -> None:
        """Searching with an identical vector yields score ≈ 1.0."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vec = _random_vector(seed=77)
        meta = _sample_metadata(1, dialogue_id="identity")
        store.add([vec], meta)

        results = store.search(vec, k=1)
        assert len(results) == 1
        assert results[0].score > 0.999  # Should be very close to 1.0

    def test_opposite_vector_has_score_near_minus_one(self) -> None:
        """Searching with the opposite of a vector yields score ≈ -1.0."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vec = _random_vector(seed=88)
        meta = _sample_metadata(1, dialogue_id="opposite")
        store.add([vec], meta)

        # Negate the vector
        opposite = [-x for x in vec]
        results = store.search(opposite, k=1)
        assert len(results) == 1
        assert results[0].score < -0.999  # Should be very close to -1.0

    def test_orthogonal_vector_has_score_near_zero(self) -> None:
        """Orthogonal vectors have cosine similarity ≈ 0."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        # Create two orthogonal vectors
        rng = np.random.default_rng(42)
        v1 = rng.standard_normal(DIMENSION).astype(np.float32)
        v1 = v1 / np.linalg.norm(v1)

        # Make v2 orthogonal to v1 (Gram-Schmidt)
        v2 = rng.standard_normal(DIMENSION).astype(np.float32)
        v2 = v2 - np.dot(v2, v1) * v1
        v2 = v2 / np.linalg.norm(v2)

        # Verify orthogonality
        assert abs(float(np.dot(v1, v2))) < 1e-5

        meta1 = _sample_metadata(1, dialogue_id="ortho-1")
        meta2 = _sample_metadata(1, dialogue_id="ortho-2")

        store.add([v1.tolist()], meta1)
        store.add([v2.tolist()], meta2)

        # Search for v1 → v2 should have score ≈ 0
        results = store.search(v1.tolist(), k=2)
        # The second result (v2) should have score ≈ 0
        if len(results) == 2:
            assert abs(results[1].score) < 0.05


# ═══════════════════════════════════════════════════════════
# Test: Validation
# ═══════════════════════════════════════════════════════════


class TestValidation:
    """Test input validation in VectorStore."""

    def test_mismatched_embeddings_metadata_raises(self) -> None:
        """Adding with mismatched embeddings/metadata count raises ValueError."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        vecs = _random_embeddings(3, seed_start=2200)
        metas = _sample_metadata(2, dialogue_id="mismatch")

        with pytest.raises(ValueError, match="embeddings count"):
            store.add(vecs, metas)

    def test_wrong_dimension_raises(self) -> None:
        """Adding vectors with wrong dimension raises ValueError."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)
        wrong_vec = [0.1] * 768  # Wrong dimension
        meta = _sample_metadata(1, dialogue_id="wrong-dim")

        with pytest.raises(ValueError, match="dimension"):
            store.add([wrong_vec], meta)


# ═══════════════════════════════════════════════════════════
# Test: Performance
# ═══════════════════════════════════════════════════════════


class TestPerformance:
    """Test performance characteristics of VectorStore operations."""

    def test_search_1000_vectors_under_100ms(self) -> None:
        """Search on 1000 vectors completes in < 100ms."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(1000, seed_start=3000)
        metas = _sample_metadata(1000, dialogue_id="perf")
        store.add(vecs, metas)

        query = _random_vector(seed=3999)
        start = time.perf_counter()
        results = store.search(query, k=10)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(results) == 10
        assert elapsed_ms < 100, f"Search took {elapsed_ms:.1f}ms, expected < 100ms"

    def test_add_batch_100_vectors_fast(self) -> None:
        """Adding 100 vectors in a batch completes in reasonable time."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(100, seed_start=3100)
        metas = _sample_metadata(100, dialogue_id="add-perf")

        start = time.perf_counter()
        store.add(vecs, metas)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert store.index.ntotal == 100
        # Just verify it completes reasonably fast (< 1s)
        assert elapsed_ms < 1000, f"Batch add took {elapsed_ms:.1f}ms"


# ═══════════════════════════════════════════════════════════
# Test: VectorStoreMigration
# ═══════════════════════════════════════════════════════════


class TestVectorStoreMigration:
    """Test VectorStoreMigration class."""

    @pytest.mark.asyncio
    async def test_migration_with_mock_services(self) -> None:
        """Migration processes dialogues using mocked services."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        # Mock embedding service
        embedding_service = AsyncMock()
        embedding_service.embed_batch = AsyncMock(
            return_value=_random_embeddings(3, seed_start=4000)
        )

        # Mock chunker
        from app.models import Chunk, ChunkMetadata

        chunks = [
            Chunk(
                text=f"Chunk text {i}",
                metadata=ChunkMetadata(
                    dialogue_id="session-1",
                    turn_index=i,
                    speaker="Клиент",
                    chunk_type="utterance",
                    token_count=5,
                    char_count=12,
                    entities=[],
                ),
            )
            for i in range(3)
        ]
        chunker = MagicMock()
        chunker.chunk_dialogue = MagicMock(return_value=chunks)

        migration = VectorStoreMigration(
            vector_store=store,
            embedding_service=embedding_service,
            chunker=chunker,
        )

        # Override _get_dialogue_from_db to return a mock dialogue
        from app.models import ParsedDialog

        mock_dialogue = ParsedDialog(filename="test.rtf")
        migration._get_dialogue_from_db = AsyncMock(return_value=mock_dialogue)  # type: ignore[assignment]

        result = await migration.migrate_dialogues(["session-1"])

        assert result["total"] == 1
        assert result["migrated"] == 1
        assert result["failed"] == 0
        assert store.index.ntotal == 3

    @pytest.mark.asyncio
    async def test_migration_accumulates_errors(self) -> None:
        """Migration accumulates errors without stopping the batch."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        embedding_service = AsyncMock()
        chunker = MagicMock()

        migration = VectorStoreMigration(
            vector_store=store,
            embedding_service=embedding_service,
            chunker=chunker,
        )

        # Override to return None (not found)
        migration._get_dialogue_from_db = AsyncMock(return_value=None)  # type: ignore[assignment]

        result = await migration.migrate_dialogues(["s1", "s2", "s3"])

        assert result["total"] == 3
        assert result["migrated"] == 0
        assert result["failed"] == 3
        assert len(result["errors"]) == 3

    @pytest.mark.asyncio
    async def test_migration_progress_callback(self) -> None:
        """Migration invokes progress callback for each session."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        embedding_service = AsyncMock()
        embedding_service.embed_batch = AsyncMock(
            return_value=_random_embeddings(2, seed_start=4100)
        )

        from app.models import Chunk, ChunkMetadata, ParsedDialog

        chunks = [
            Chunk(
                text="Test",
                metadata=ChunkMetadata(
                    dialogue_id="s1",
                    turn_index=0,
                    speaker="Клиент",
                    chunk_type="utterance",
                    token_count=1,
                    char_count=4,
                    entities=[],
                ),
            ),
        ]
        chunker = MagicMock()
        chunker.chunk_dialogue = MagicMock(return_value=chunks)

        migration = VectorStoreMigration(
            vector_store=store,
            embedding_service=embedding_service,
            chunker=chunker,
        )

        mock_dialogue = ParsedDialog(filename="test.rtf")
        migration._get_dialogue_from_db = AsyncMock(return_value=mock_dialogue)  # type: ignore[assignment]

        progress_calls: List[tuple] = []
        def progress_cb(current: int, total: int) -> None:
            progress_calls.append((current, total))

        result = await migration.migrate_dialogues(
            ["s1", "s2"], progress_callback=progress_cb
        )

        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2)
        assert progress_calls[1] == (2, 2)

    @pytest.mark.asyncio
    async def test_migration_empty_dialogue_produces_no_chunks(self) -> None:
        """Empty dialogue produces no chunks but counts as migrated."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        embedding_service = AsyncMock()
        chunker = MagicMock()
        chunker.chunk_dialogue = MagicMock(return_value=[])

        migration = VectorStoreMigration(
            vector_store=store,
            embedding_service=embedding_service,
            chunker=chunker,
        )

        from app.models import ParsedDialog

        mock_dialogue = ParsedDialog(filename="empty.rtf")
        migration._get_dialogue_from_db = AsyncMock(return_value=mock_dialogue)  # type: ignore[assignment]

        result = await migration.migrate_dialogues(["empty-session"])

        assert result["migrated"] == 1
        assert result["failed"] == 0
        assert store.index.ntotal == 0


# ═══════════════════════════════════════════════════════════
# Test: VectorSearchResult model
# ═══════════════════════════════════════════════════════════


class TestVectorSearchResultModel:
    """Test VectorSearchResult Pydantic model."""

    def test_create_search_result(self) -> None:
        """VectorSearchResult can be created with all fields."""
        result = VectorSearchResult(
            chunk_id="chunk-1",
            text="Hello",
            dialogue_id="dialogue-1",
            turn_index=0,
            speaker="Клиент",
            score=0.95,
            chunk_type="utterance",
            entities=[{"text": "Moscow", "type": "LOC"}],
        )
        assert result.chunk_id == "chunk-1"
        assert result.score == 0.95
        assert len(result.entities) == 1

    def test_search_result_default_entities(self) -> None:
        """VectorSearchResult defaults entities to empty list."""
        result = VectorSearchResult(
            chunk_id="chunk-2",
            text="Hi",
            dialogue_id="d2",
            turn_index=1,
            speaker="Сотрудник",
            score=0.8,
            chunk_type="overlap",
        )
        assert result.entities == []

    def test_search_result_serialization(self) -> None:
        """VectorSearchResult can be serialized to dict/JSON."""
        result = VectorSearchResult(
            chunk_id="chunk-3",
            text="Test",
            dialogue_id="d3",
            turn_index=2,
            speaker="Клиент",
            score=0.99,
            chunk_type="utterance",
            entities=[],
        )
        d = result.model_dump()
        assert d["chunk_id"] == "chunk-3"
        assert d["score"] == 0.99

        json_str = result.model_dump_json()
        assert "chunk-3" in json_str


# ═══════════════════════════════════════════════════════════
# Test: Auto-save
# ═══════════════════════════════════════════════════════════


class TestAutoSave:
    """Test auto-save functionality."""

    def test_auto_save_on_add(self) -> None:
        """Auto-save triggers after add when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(
                dimension=DIMENSION,
                index_path=tmpdir,
                auto_save=True,
            )

            vecs = _random_embeddings(2, seed_start=5000)
            metas = _sample_metadata(2, dialogue_id="auto-save")
            store.add(vecs, metas)

            # Files should be written
            assert os.path.exists(os.path.join(tmpdir, "index.faiss"))
            assert os.path.exists(os.path.join(tmpdir, "metadata.json"))

    def test_no_auto_save_when_disabled(self) -> None:
        """Auto-save does not trigger when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(
                dimension=DIMENSION,
                index_path=tmpdir,
                auto_save=False,
            )

            vecs = _random_embeddings(2, seed_start=5100)
            metas = _sample_metadata(2, dialogue_id="no-auto-save")
            store.add(vecs, metas)

            # Files should NOT be written
            assert not os.path.exists(os.path.join(tmpdir, "index.faiss"))

    def test_no_auto_save_without_index_path(self) -> None:
        """Auto-save does not trigger without index_path."""
        store = VectorStore(dimension=DIMENSION, auto_save=True)

        vecs = _random_embeddings(2, seed_start=5200)
        metas = _sample_metadata(2, dialogue_id="no-path")
        # Should not raise even though auto_save is True
        store.add(vecs, metas)
        assert store.index.ntotal == 2


# ═══════════════════════════════════════════════════════════
# Test: Statistics
# ═══════════════════════════════════════════════════════════


class TestStatistics:
    """Test VectorStore statistics."""

    def test_stats_after_add(self) -> None:
        """Stats are correct after adding vectors."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(5, seed_start=6000)
        metas_d1 = _sample_metadata(3, dialogue_id="d1")
        metas_d2 = _sample_metadata(2, dialogue_id="d2")
        store.add(vecs[:3], metas_d1)
        store.add(vecs[3:], metas_d2)

        stats = store.get_stats()
        assert stats["total_vectors"] == 5
        assert stats["unique_dialogues"] == 2
        assert stats["index_size_bytes"] == 5 * DIMENSION * 4

    def test_stats_after_delete(self) -> None:
        """Stats are correct after deleting vectors."""
        store = VectorStore(dimension=DIMENSION, auto_save=False)

        vecs = _random_embeddings(5, seed_start=6100)
        metas_d1 = _sample_metadata(3, dialogue_id="delete-stats")
        metas_d2 = _sample_metadata(2, dialogue_id="keep-stats")
        store.add(vecs[:3], metas_d1)
        store.add(vecs[3:], metas_d2)

        store.delete_by_dialogue("delete-stats")

        stats = store.get_stats()
        assert stats["total_vectors"] == 2
        assert stats["unique_dialogues"] == 1
        assert stats["index_size_bytes"] == 2 * DIMENSION * 4

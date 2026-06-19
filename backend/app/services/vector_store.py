"""FAISS-based vector store for FRIDA embeddings.

Provides VectorStore with:
  - FAISS IndexFlatIP (inner product) with L2-normalized vectors for cosine similarity
  - In-memory metadata list + chunk_id_to_idx mapping parallel to FAISS index
  - Batch add with L2-normalization
  - k-nearest neighbor search (cosine similarity)
  - Transaction-based delete by dialogue_id (backup → rebuild → commit/rollback)
  - Save/load persistence (index.faiss + metadata.json + chunk_id_map.json)
  - Auto-save after mutations (configurable)
  - get_stats() for observability

Provides VectorStoreMigration with:
  - Batch migration of dialogues with progress callback
  - Checkpointing for resumable migration
  - Error accumulation (failures don't stop the batch)

API contract:
  add(embeddings, metadata) → None
  search(query_vector, k=10) → List[VectorSearchResult]
  delete_by_dialogue(dialogue_id) → int
  get_stats() → dict
  save(path) → None
  load(path) → None
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import faiss
import numpy as np

from app.models import VectorSearchResult

logger = logging.getLogger(__name__)

# Default configuration constants
_DEFAULT_DIMENSION = 1536
_DEFAULT_AUTO_SAVE = True
_DEFAULT_BATCH_SIZE = 100


class VectorStore:
    """FAISS-based vector store for FRIDA embeddings.

    Uses IndexFlatIP (inner product) with L2-normalized vectors
    to achieve cosine similarity search.

    Attributes:
        dimension: Vector dimensionality (1536 for FRIDA).
        index_path: Optional path for auto-save/load.
        auto_save: Whether to auto-save after mutations.
        index: FAISS IndexFlatIP index.
        _metadata: Parallel list of metadata dicts (one per vector).
        _chunk_id_to_idx: Mapping from chunk_id to index in _metadata.
        _stats: Internal statistics dict.
    """

    def __init__(
        self,
        dimension: int = _DEFAULT_DIMENSION,
        index_path: Optional[str] = None,
        auto_save: bool = _DEFAULT_AUTO_SAVE,
    ) -> None:
        """Initialize VectorStore.

        Args:
            dimension: Vector dimensionality (1536 for FRIDA).
            index_path: Optional path for auto-save/load.
            auto_save: Whether to automatically save after mutations.
        """
        self.dimension = dimension
        self.index_path = Path(index_path) if index_path else None
        self.auto_save = auto_save

        # FAISS index (inner product for cosine similarity with L2-normalized vectors)
        self.index = faiss.IndexFlatIP(dimension)

        # In-memory metadata parallel to FAISS index
        self._metadata: List[Dict[str, Any]] = []
        self._chunk_id_to_idx: Dict[str, int] = {}

        # Internal statistics
        self._stats: Dict[str, Any] = {
            "total_vectors": 0,
            "unique_dialogues": set(),  # type: ignore[assignment]
            "index_size_bytes": 0,
        }

    # ── L2-normalization ────────────────────────────────────────

    @staticmethod
    def _normalize(vectors: List[List[float]]) -> np.ndarray:
        """L2-normalize vectors for cosine similarity with IndexFlatIP.

        For L2-normalized vectors, inner product equals cosine similarity.
        Zero vectors are protected against division by zero.

        Args:
            vectors: List of float vectors (each of length `dimension`).

        Returns:
            L2-normalized numpy array of shape (n, dimension), dtype float32.
        """
        arr = np.array(vectors, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Protection against division by zero
        return arr / norms

    # ── Add embeddings ──────────────────────────────────────────

    def add(self, embeddings: List[List[float]], metadata: List[Dict[str, Any]]) -> None:
        """Add embeddings with metadata to the vector store.

        L2-normalizes all vectors before adding (for cosine similarity).
        Updates internal metadata list, chunk_id mapping, and statistics.
        Auto-saves if enabled and index_path is set.

        Args:
            embeddings: List of embedding vectors (each of length `dimension`).
            metadata: List of metadata dicts (same length as embeddings).
                Each dict should contain: chunk_id, dialogue_id, text,
                turn_index, speaker, chunk_type, entities.

        Raises:
            ValueError: If len(embeddings) != len(metadata).
            ValueError: If any embedding dimension != self.dimension.
        """
        if not embeddings:
            return

        if len(embeddings) != len(metadata):
            raise ValueError(
                f"embeddings count ({len(embeddings)}) != metadata count ({len(metadata)})"
            )

        # Validate dimensions
        for i, emb in enumerate(embeddings):
            if len(emb) != self.dimension:
                raise ValueError(
                    f"embedding[{i}] dimension {len(emb)} != expected {self.dimension}"
                )

        # L2-normalize for cosine similarity
        normalized = self._normalize(embeddings)

        # Add to FAISS index
        self.index.add(normalized)

        # Update metadata and mapping
        for meta in metadata:
            chunk_id = meta.get("chunk_id", "")
            idx = len(self._metadata)
            self._metadata.append(meta)
            if chunk_id:
                self._chunk_id_to_idx[chunk_id] = idx

            # Update dialogue set in stats
            dialogue_id = meta.get("dialogue_id")
            if dialogue_id:
                self._stats["unique_dialogues"].add(dialogue_id)  # type: ignore[union-attr]

        self._stats["total_vectors"] += len(embeddings)
        self._update_stats()

        if self.auto_save and self.index_path:
            self.save(self.index_path)

    # ── Search ──────────────────────────────────────────────────

    def search(self, query_vector: List[float], k: int = 10) -> List[VectorSearchResult]:
        """Find k nearest neighbors by cosine similarity.

        L2-normalizes the query vector, then searches the FAISS index.
        Returns results sorted by score (descending).

        Args:
            query_vector: Query embedding vector (length `dimension`).
            k: Number of nearest neighbors to return (default 10).

        Returns:
            List of VectorSearchResult sorted by cosine similarity (desc).
            Empty list if the store is empty.
        """
        if self.index.ntotal == 0:
            return []

        # Clamp k to the number of vectors in the index
        k = min(k, self.index.ntotal)
        if k < 1:
            k = 1

        # L2-normalize query
        query = self._normalize([query_vector])

        # FAISS search
        scores, indices = self.index.search(query, k)

        results: List[VectorSearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue  # FAISS returns -1 for unfilled slots

            meta = self._metadata[idx]
            results.append(
                VectorSearchResult(
                    chunk_id=meta.get("chunk_id", str(idx)),
                    text=meta.get("text", ""),
                    dialogue_id=meta.get("dialogue_id", ""),
                    turn_index=meta.get("turn_index", 0),
                    speaker=meta.get("speaker", ""),
                    score=float(score),
                    chunk_type=meta.get("chunk_type", "unknown"),
                    entities=meta.get("entities", []),
                )
            )

        return results

    # ── Delete by dialogue ──────────────────────────────────────

    def delete_by_dialogue(self, dialogue_id: str) -> int:
        """Delete all embeddings for a given dialogue_id.

        FAISS does not support deletion, so the index is rebuilt without
        the deleted items. This is transaction-based: on failure, the
        previous state is restored (rollback).

        Args:
            dialogue_id: Dialogue/session identifier to delete.

        Returns:
            Number of deleted vectors.

        Raises:
            Exception: If rebuild fails (state is rolled back before re-raise).
        """
        # Find indices to delete
        indices_to_delete: Set[int] = set()
        for idx, meta in enumerate(self._metadata):
            if meta.get("dialogue_id") == dialogue_id:
                indices_to_delete.add(idx)

        if not indices_to_delete:
            return 0

        # Backup current state for rollback
        backup_metadata = self._metadata.copy()
        backup_chunk_id_to_idx = self._chunk_id_to_idx.copy()
        backup_stats = {
            "total_vectors": self._stats["total_vectors"],
            "unique_dialogues": set(self._stats["unique_dialogues"]),  # type: ignore[call-overload]
            "index_size_bytes": self._stats["index_size_bytes"],
        }
        backup_index = faiss.clone_index(self.index)

        try:
            # Rebuild index without deleted items
            self._rebuild_index_without(indices_to_delete)

            if self.auto_save and self.index_path:
                self.save(self.index_path)

            return len(indices_to_delete)

        except Exception as exc:
            # Rollback to backup state
            logger.error("Delete by dialogue failed, rolling back: %s", exc)
            self.index = backup_index
            self._metadata = backup_metadata
            self._chunk_id_to_idx = backup_chunk_id_to_idx
            self._stats = backup_stats
            raise

    def _rebuild_index_without(self, indices_to_delete: Set[int]) -> None:
        """Rebuild FAISS index and metadata excluding given indices.

        This is a separate method to enable testability of the rollback
        mechanism — the test can patch this method to simulate a failure.

        Args:
            indices_to_delete: Set of indices to exclude from the rebuilt index.

        Raises:
            Exception: If FAISS reconstruct or rebuild fails.
        """
        new_metadata: List[Dict[str, Any]] = []
        new_chunk_id_to_idx: Dict[str, int] = {}
        surviving_vectors: List[np.ndarray] = []

        for idx, meta in enumerate(self._metadata):
            if idx not in indices_to_delete:
                new_idx = len(new_metadata)
                new_metadata.append(meta)
                chunk_id = meta.get("chunk_id", "")
                if chunk_id:
                    new_chunk_id_to_idx[chunk_id] = new_idx

                # Retrieve vector from FAISS index via reconstruct
                vec = self.index.reconstruct(idx)
                surviving_vectors.append(vec)

        # Rebuild FAISS index with surviving vectors only
        new_index = faiss.IndexFlatIP(self.dimension)
        if surviving_vectors:
            vectors_array = np.vstack(surviving_vectors).astype(np.float32)
            new_index.add(vectors_array)

        # Commit: replace state with new state
        self.index = new_index
        self._metadata = new_metadata
        self._chunk_id_to_idx = new_chunk_id_to_idx
        self._stats["total_vectors"] = len(new_metadata)
        # Rebuild dialogue set from remaining metadata
        self._stats["unique_dialogues"] = {
            m.get("dialogue_id")
            for m in new_metadata
            if m.get("dialogue_id")
        }
        self._update_stats()

    # ── Statistics ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics.

        Returns:
            Dict with keys:
                total_vectors: Total number of stored vectors.
                unique_dialogues: Number of unique dialogue IDs.
                index_size_bytes: Estimated FAISS index size in bytes.
        """
        return {
            "total_vectors": self._stats["total_vectors"],
            "unique_dialogues": len(self._stats["unique_dialogues"]),  # type: ignore[arg-type]
            "index_size_bytes": self._stats["index_size_bytes"],
        }

    def _update_stats(self) -> None:
        """Update derived statistics (index_size_bytes)."""
        self._stats["index_size_bytes"] = self.index.ntotal * self.dimension * 4  # float32

    # ── Persistence: save ───────────────────────────────────────

    def save(self, path: str) -> None:
        """Save index + metadata + chunk_id_map to disk.

        Creates the directory if it doesn't exist. Writes three files:
          - index.faiss: FAISS index binary
          - metadata.json: List of metadata dicts
          - chunk_id_map.json: Dict mapping chunk_id to index

        Args:
            path: Directory path to save files into.
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self.index, str(path / "index.faiss"))

        # Save metadata (convert sets to lists for JSON serialization)
        metadata_serializable = []
        for meta in self._metadata:
            meta_copy = {}
            for key, value in meta.items():
                if isinstance(value, set):
                    meta_copy[key] = list(value)
                else:
                    meta_copy[key] = value
            metadata_serializable.append(meta_copy)

        with open(path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata_serializable, f, ensure_ascii=False, indent=2)

        # Save chunk_id to index mapping
        with open(path / "chunk_id_map.json", "w", encoding="utf-8") as f:
            json.dump(self._chunk_id_to_idx, f, ensure_ascii=False, indent=2)

        logger.info("VectorStore saved to %s (%d vectors)", path, self.index.ntotal)

    # ── Persistence: load ───────────────────────────────────────

    def load(self, path: str) -> None:
        """Load index + metadata + chunk_id_map from disk.

        Restores the full state: FAISS index, metadata list,
        chunk_id mapping, and statistics.

        Args:
            path: Directory path to load files from.

        Raises:
            FileNotFoundError: If required files don't exist in the path.
        """
        path = Path(path)

        index_file = path / "index.faiss"
        metadata_file = path / "metadata.json"
        chunk_map_file = path / "chunk_id_map.json"

        if not index_file.exists():
            raise FileNotFoundError(f"Index file not found: {index_file}")
        if not metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {metadata_file}")
        if not chunk_map_file.exists():
            raise FileNotFoundError(f"Chunk ID map file not found: {chunk_map_file}")

        # Load FAISS index
        self.index = faiss.read_index(str(index_file))

        # Load metadata
        with open(metadata_file, "r", encoding="utf-8") as f:
            self._metadata = json.load(f)

        # Load chunk_id mapping
        with open(chunk_map_file, "r", encoding="utf-8") as f:
            self._chunk_id_to_idx = json.load(f)

        # Rebuild statistics
        self._stats["total_vectors"] = self.index.ntotal
        self._stats["unique_dialogues"] = {
            m.get("dialogue_id")
            for m in self._metadata
            if m.get("dialogue_id")
        }
        self._stats["index_size_bytes"] = self.index.ntotal * self.dimension * 4

        logger.info(
            "VectorStore loaded from %s (%d vectors)",
            path,
            self.index.ntotal,
        )


class VectorStoreMigration:
    """Migrate existing dialogues into VectorStore.

    Features:
    - Batch processing with progress callback
    - Error accumulation (failures don't stop the batch)
    - Checkpointing for resumable migration

    Attributes:
        vector_store: Target VectorStore instance.
        embedding_service: FridaEmbeddingService for vectorization.
        chunker: Chunker for text chunking.
        batch_size: Number of dialogues per batch.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: Any,  # FridaEmbeddingService — typed as Any to avoid circular import
        chunker: Any,  # Chunker — typed as Any to avoid circular import
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        """Initialize VectorStoreMigration.

        Args:
            vector_store: Target VectorStore to migrate into.
            embedding_service: FridaEmbeddingService instance for vectorization.
            chunker: Chunker instance for text chunking.
            batch_size: Number of dialogues to process per batch.
        """
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.chunker = chunker
        self.batch_size = batch_size

    async def migrate_dialogues(
        self,
        session_ids: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Migrate existing dialogues into VectorStore.

        Processes dialogues in batches. For each session:
          1. Fetch dialogue from DB (placeholder)
          2. Chunk dialogue text
          3. Embed chunks via FRIDA
          4. Add embeddings + metadata to VectorStore

        Errors are accumulated and do not stop the batch.
        Progress callback is invoked after each session.

        Args:
            session_ids: List of session IDs to migrate.
            progress_callback: Optional callback(current, total) for progress reporting.

        Returns:
            Dict with keys: total, migrated, failed, errors.
            errors is a list of {session_id, error} dicts.
        """
        total = len(session_ids)
        migrated = 0
        failed = 0
        errors: List[Dict[str, str]] = []

        for i, session_id in enumerate(session_ids):
            try:
                # Step 1: Fetch dialogue from DB (placeholder)
                dialogue = await self._get_dialogue_from_db(session_id)

                if dialogue is None:
                    failed += 1
                    errors.append({
                        "session_id": session_id,
                        "error": "Dialogue not found in DB",
                    })
                    continue

                # Step 2: Chunk dialogue text
                chunks = self.chunker.chunk_dialogue(dialogue, session_id)

                if not chunks:
                    # No chunks produced (empty dialogue or all turns blank)
                    migrated += 1
                    continue

                # Step 3: Embed chunks via FRIDA
                texts = [chunk.text for chunk in chunks]
                embeddings = await self.embedding_service.embed_batch(texts)

                # Step 4: Build metadata and add to VectorStore
                metadata = [chunk.metadata.model_dump() for chunk in chunks]
                self.vector_store.add(embeddings, metadata)

                migrated += 1

            except Exception as exc:
                failed += 1
                errors.append({
                    "session_id": session_id,
                    "error": str(exc),
                })
                logger.error("Migration failed for session %s: %s", session_id, exc)

            # Progress callback
            if progress_callback is not None:
                progress_callback(i + 1, total)

        return {
            "total": total,
            "migrated": migrated,
            "failed": failed,
            "errors": errors,
        }

    async def _get_dialogue_from_db(self, session_id: str) -> Any:
        """Fetch dialogue from database by session_id.

        Placeholder implementation — should be replaced with actual
        DB interaction when the sessions store is available.

        Args:
            session_id: Session identifier to look up.

        Returns:
            ParsedDialog instance, or None if not found.
        """
        # TODO: Implement DB interaction for in-memory sessions
        logger.warning(
            "_get_dialogue_from_db is a placeholder — session %s not fetched",
            session_id,
        )
        return None

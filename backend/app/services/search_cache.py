"""In-memory cache for dictionary search results (P2 optimization).

When a user clicks "Анализировать" multiple times on the same dialogue +
same set of dictionaries, the expensive ``run_hierarchical_search()`` call
(~1 second per call) is only executed once. Subsequent calls return the
cached ``SearchResult`` until the dialog or dictionary set changes.

Cache key strategy:
    The key is derived from a SHA-256 hash of:
      - the dialogue's turn texts (joined by speaker)
      - the sorted list of selected dictionary names
      - the sorted list of dictionary content (model_dump JSON)

This ensures that any change to either the dialogue or any dictionary
invalidates the cache for that combination.

The cache is process-local and bounded by ``max_entries`` (LRU eviction).
It is **not** shared across processes/workers — each uvicorn worker has
its own. This is sufficient for the P2 use case: a single user re-clicking
"Анализировать" hits the same worker.

TTL: entries expire after ``ttl_seconds`` (default 1 hour). This prevents
unbounded growth and ensures a dictionary edit (which mutates the
session's dictionary in-place) is eventually picked up if the user did
not refresh the session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from app.models import ParsedDialog, SearchResult

logger = logging.getLogger(__name__)


class SearchCache:
    """Thread-safe LRU cache mapping (dialog + dictionaries) → SearchResult.

    Attributes:
        _store: OrderedDict keyed by hash digest (LRU semantics).
        _lock: Reentrant lock for thread safety.
        max_entries: Maximum number of cached entries (LRU eviction).
        ttl_seconds: Time-to-live for cache entries in seconds.
    """

    def __init__(self, max_entries: int = 256, ttl_seconds: int = 3600) -> None:
        self._store: "OrderedDict[str, tuple[float, SearchResult]]" = OrderedDict()
        self._lock = threading.RLock()
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

    # ── Public API ──────────────────────────────────────────────

    def get(
        self,
        dialog: Optional[ParsedDialog],
        dictionary_names: Optional[list[str]] = None,
        dictionaries: Optional[list[Any]] = None,
    ) -> Optional[SearchResult]:
        """Return cached SearchResult for the (dialog + dictionaries) key.

        Returns None on cache miss, expired entry, or invalid input.
        """
        key = self._make_key(dialog, dictionary_names, dictionaries)
        if key is None:
            return None

        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            cached_at, result = entry
            if self._is_expired(cached_at):
                # Lazy eviction
                self._store.pop(key, None)
                return None

            # Mark as recently used (move to end of OrderedDict)
            self._store.move_to_end(key)
            return result

    def put(
        self,
        result: SearchResult,
        dialog: Optional[ParsedDialog],
        dictionary_names: Optional[list[str]] = None,
        dictionaries: Optional[list[Any]] = None,
    ) -> None:
        """Store a SearchResult for the (dialog + dictionaries) key."""
        key = self._make_key(dialog, dictionary_names, dictionaries)
        if key is None:
            return

        with self._lock:
            now = time.time()
            self._store[key] = (now, result)
            self._store.move_to_end(key)
            self._evict_if_needed()

    def invalidate(
        self,
        dialog: Optional[ParsedDialog],
        dictionary_names: Optional[list[str]] = None,
        dictionaries: Optional[list[Any]] = None,
    ) -> bool:
        """Remove a specific cache entry. Returns True if an entry was removed."""
        key = self._make_key(dialog, dictionary_names, dictionaries)
        if key is None:
            return False

        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> int:
        """Clear all cache entries. Returns the number of entries removed."""
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n

    def stats(self) -> dict[str, int]:
        """Return cache statistics: {entries, max_entries, ttl_seconds}."""
        with self._lock:
            return {
                "entries": len(self._store),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
            }

    # ── Internals ─────────────────────────────────────────────

    def _is_expired(self, cached_at: float) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - cached_at) > self.ttl_seconds

    def _evict_if_needed(self) -> None:
        """Evict oldest entries until the cache fits max_entries."""
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)  # Pop oldest (FIFO end)

    def _make_key(
        self,
        dialog: Optional[ParsedDialog],
        dictionary_names: Optional[list[str]],
        dictionaries: Optional[list[Any]],
    ) -> Optional[str]:
        """Build a stable SHA-256 cache key from dialog + dictionaries.

        Returns None if the dialog is missing (cannot cache).
        """
        if dialog is None or not dialog.turns:
            return None

        h = hashlib.sha256()

        # 1. Dialogue content: speaker + text per turn
        for turn in dialog.turns:
            h.update(turn.speaker.encode("utf-8"))
            h.update(b"\x00")
            h.update((turn.text or "").encode("utf-8"))
            h.update(b"\x01")

        # 2. Dictionary selection: sorted names
        names_sorted = sorted(dictionary_names) if dictionary_names else []
        for name in names_sorted:
            h.update(name.encode("utf-8"))
            h.update(b"\x02")

        # 3. Dictionary content: model_dump JSON (sorted by name)
        if dictionaries:
            # Sort by name for determinism (dictionaries dict can have arbitrary order)
            sorted_dicts = sorted(dictionaries, key=lambda d: getattr(d, "name", ""))
            for d in sorted_dicts:
                try:
                    payload = d.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
                    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    h.update(blob.encode("utf-8"))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("SearchCache: failed to hash dictionary %s: %s", d, exc)
                    # Skip this dictionary's content but continue
                h.update(b"\x03")

        return h.hexdigest()

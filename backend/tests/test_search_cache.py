"""Tests for SearchCache (P2 optimization).

Verifies:
  - Cache hit returns the same SearchResult object.
  - Cache miss → put → cache hit pattern.
  - LRU eviction when max_entries is exceeded.
  - TTL expiration (entries become stale after ttl_seconds).
  - Different dialogues or dictionaries produce different cache keys.
  - clear() and invalidate() semantics.
  - Thread safety (basic concurrent put/get).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    DialogueTurn,
    ParsedDialog,
    SearchResult,
)
from app.services.search_cache import SearchCache


def _make_dialog(text_a: str = "Здравствуйте", text_b: str = "Добрый день") -> ParsedDialog:
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(
                speaker="operator", text=text_a, turn_index=0, start_ms=0, end_ms=500,
            ),
            DialogueTurn(
                speaker="client", text=text_b, turn_index=1, start_ms=600, end_ms=1000,
            ),
        ],
    )


def _make_search_result(total: int = 5) -> SearchResult:
    return SearchResult(
        segments=[],
        total_matches=total,
        matches=[],
        matches_by_level={"1": total},
    )


class TestSearchCacheBasics:
    def test_cache_miss_returns_none(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        result = cache.get(_make_dialog(), None, None)
        assert result is None

    def test_put_then_get_returns_cached_value(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        dialog = _make_dialog()
        expected = _make_search_result(total=7)

        cache.put(expected, dialog=dialog, dictionary_names=["d1"], dictionaries=[])
        cached = cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[])

        assert cached is expected  # same object

    def test_different_dialogue_produces_different_key(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        dialog_a = _make_dialog(text_a="Здравствуйте")
        dialog_b = _make_dialog(text_a="Привет")

        result_a = _make_search_result(total=1)
        cache.put(result_a, dialog=dialog_a, dictionary_names=None, dictionaries=None)

        # dialog_b should miss
        assert cache.get(dialog=dialog_b, dictionary_names=None, dictionaries=None) is None
        # dialog_a should hit
        assert cache.get(dialog=dialog_a, dictionary_names=None, dictionaries=None) is result_a

    def test_different_dictionary_names_produce_different_keys(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        dialog = _make_dialog()

        result_a = _make_search_result(total=3)
        cache.put(result_a, dialog=dialog, dictionary_names=["d1"], dictionaries=[])

        assert cache.get(dialog=dialog, dictionary_names=["d2"], dictionaries=[]) is None
        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is result_a

    def test_dictionary_name_order_does_not_matter(self) -> None:
        """Sorted internally — ['d2', 'd1'] and ['d1', 'd2'] hit the same key."""
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        dialog = _make_dialog()

        result = _make_search_result(total=4)
        cache.put(result, dialog=dialog, dictionary_names=["d2", "d1"], dictionaries=[])

        assert cache.get(dialog=dialog, dictionary_names=["d1", "d2"], dictionaries=[]) is result


class TestSearchCacheEviction:
    def test_lru_eviction_removes_oldest(self) -> None:
        cache = SearchCache(max_entries=2, ttl_seconds=60)
        dialog = _make_dialog()

        r1 = _make_search_result(total=1)
        r2 = _make_search_result(total=2)
        r3 = _make_search_result(total=3)

        cache.put(r1, dialog=dialog, dictionary_names=["d1"], dictionaries=[])
        cache.put(r2, dialog=dialog, dictionary_names=["d2"], dictionaries=[])

        # Access r1 to mark it as recently used
        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is r1

        # Add r3 — this should evict r2 (least recently used), NOT r1
        cache.put(r3, dialog=dialog, dictionary_names=["d3"], dictionaries=[])

        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is r1
        assert cache.get(dialog=dialog, dictionary_names=["d2"], dictionaries=[]) is None
        assert cache.get(dialog=dialog, dictionary_names=["d3"], dictionaries=[]) is r3

    def test_clear_removes_all_entries(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        dialog = _make_dialog()

        cache.put(_make_search_result(), dialog=dialog, dictionary_names=["d1"], dictionaries=[])
        cache.put(_make_search_result(), dialog=dialog, dictionary_names=["d2"], dictionaries=[])

        n = cache.clear()
        assert n == 2
        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is None
        assert cache.get(dialog=dialog, dictionary_names=["d2"], dictionaries=[]) is None

    def test_invalidate_removes_specific_entry(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=60)
        dialog = _make_dialog()

        r1 = _make_search_result(total=1)
        cache.put(r1, dialog=dialog, dictionary_names=["d1"], dictionaries=[])

        removed = cache.invalidate(dialog=dialog, dictionary_names=["d1"], dictionaries=[])
        assert removed is True
        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is None

        # Second invalidate returns False (already gone)
        removed2 = cache.invalidate(dialog=dialog, dictionary_names=["d1"], dictionaries=[])
        assert removed2 is False


class TestSearchCacheTTL:
    def test_expired_entry_returns_none(self) -> None:
        """Entries older than ttl_seconds should miss on get."""
        cache = SearchCache(max_entries=10, ttl_seconds=1)  # 1-second TTL
        dialog = _make_dialog()
        cache.put(_make_search_result(), dialog=dialog, dictionary_names=["d1"], dictionaries=[])

        # Wait > 1 second
        time.sleep(1.2)

        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is None

    def test_zero_ttl_never_expires(self) -> None:
        cache = SearchCache(max_entries=10, ttl_seconds=0)
        dialog = _make_dialog()
        r = _make_search_result()
        cache.put(r, dialog=dialog, dictionary_names=["d1"], dictionaries=[])

        # Even after a short sleep, ttl=0 means no expiration
        time.sleep(0.05)
        assert cache.get(dialog=dialog, dictionary_names=["d1"], dictionaries=[]) is r


class TestSearchCacheStats:
    def test_stats_reports_entries_and_limits(self) -> None:
        cache = SearchCache(max_entries=5, ttl_seconds=120)
        dialog = _make_dialog()

        cache.put(_make_search_result(), dialog=dialog, dictionary_names=["d1"], dictionaries=[])
        cache.put(_make_search_result(), dialog=dialog, dictionary_names=["d2"], dictionaries=[])

        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["max_entries"] == 5
        assert stats["ttl_seconds"] == 120


class TestSearchCacheThreadSafety:
    def test_concurrent_put_get_no_crash(self) -> None:
        """Multiple threads putting/getting concurrently should not raise."""
        cache = SearchCache(max_entries=100, ttl_seconds=60)
        dialog = _make_dialog()
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                for i in range(50):
                    r = _make_search_result(total=idx * 100 + i)
                    cache.put(
                        r,
                        dialog=dialog,
                        dictionary_names=[f"d{idx}"],
                        dictionaries=[],
                    )
                    cache.get(
                        dialog=dialog,
                        dictionary_names=[f"d{idx}"],
                        dictionaries=[],
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # Each thread wrote 50 entries but to the same 5 keys (one per thread),
        # so the cache should have exactly 5 entries.
        assert cache.stats()["entries"] == 5

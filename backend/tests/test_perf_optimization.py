"""Tests for morph_matcher perf optimization (N18): precomputed word_positions
and turn_words caches.

UI-2.6 BE timestamps iteration. ``match_phrase_morphological_detailed`` now
accepts optional ``precomputed_word_positions`` and ``precomputed_turn_words``
arguments. When supplied, the function MUST reuse them and MUST NOT
re-tokenize the same turn text. The search engine populates these caches
once per node so every condition of that node shares them.

These tests verify:
  1. Results are byte-identical with and without the cache (correctness).
  2. The cache is actually consulted (tokenize is not re-invoked) — verified
     by counting tokenize calls through a wrapper.
  3. search._search_recursive populates and reuses the cache across
     multiple conditions of the same node.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "Transcrib")
)

from app.services import morph_matcher
from app.services.morph_matcher import (
    _find_word_positions,
    _tokenize,
    match_phrase_morphological_detailed,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. Equivalence: with cache == without cache
# ═══════════════════════════════════════════════════════════════════════


def _make_turns() -> list[dict]:
    return [
        {"speaker": "Клиент", "text": "я хочу расторгнуть договор"},
        {"speaker": "Сотрудник", "text": "давайте обсудим ситуацию"},
        {"speaker": "Клиент", "text": "отказываюсь от диагностики сейчас"},
    ]


class TestEquivalence:
    """Output must be identical with/without precomputed caches."""

    def test_results_identical_with_and_without_cache_morph(self) -> None:
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}

        without_cache = match_phrase_morphological_detailed(
            phrase_text="расторгнуть договор",
            word_distance=2,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
        )
        with_cache = match_phrase_morphological_detailed(
            phrase_text="расторгнуть договор",
            word_distance=2,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
            precomputed_word_positions=[
                _find_word_positions(t["text"]) for t in turns
            ],
            precomputed_turn_words=[_tokenize(t["text"]) for t in turns],
        )
        assert without_cache == with_cache

    def test_results_identical_with_and_without_cache_exact(self) -> None:
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}

        without_cache = match_phrase_morphological_detailed(
            phrase_text="расторгнуть",
            word_distance=1,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=True,
        )
        with_cache = match_phrase_morphological_detailed(
            phrase_text="расторгнуть",
            word_distance=1,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=True,
            precomputed_word_positions=[
                _find_word_positions(t["text"]) for t in turns
            ],
            precomputed_turn_words=[_tokenize(t["text"]) for t in turns],
        )
        assert without_cache == with_cache

    def test_cache_size_mismatch_falls_back_to_local(self) -> None:
        """If precomputed array length != len(turns), the function falls
        back to its internal lazy caches (no IndexError, no silent
        truncation of results)."""
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}

        # Cache too short — should be ignored (use_cached_* becomes False).
        result = match_phrase_morphological_detailed(
            phrase_text="расторгнуть",
            word_distance=1,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
            precomputed_word_positions=[_find_word_positions(turns[0]["text"])],
            precomputed_turn_words=[_tokenize(turns[0]["text"])],
        )
        # Should still find the match in turn 0.
        assert any(turn_idx == 0 for turn_idx, _, _ in result)

    def test_no_match_returns_empty_with_cache(self) -> None:
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}
        result = match_phrase_morphological_detailed(
            phrase_text="несуществующееслово",
            word_distance=2,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
            precomputed_word_positions=[
                _find_word_positions(t["text"]) for t in turns
            ],
            precomputed_turn_words=[_tokenize(t["text"]) for t in turns],
        )
        assert result == []


# ═══════════════════════════════════════════════════════════════════════
# 2. Cache usage: _tokenize is NOT re-invoked when cache supplied
# ═══════════════════════════════════════════════════════════════════════


class TestCacheConsulted:
    """When precomputed_turn_words is supplied, the function must NOT call
    _tokenize on any turn text. We monkeypatch _tokenize to a wrapper
    that increments a counter and delegates to the original."""

    def test_tokenize_not_called_when_cache_supplied(self, monkeypatch) -> None:
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}

        original_tokenize = morph_matcher._tokenize
        calls = {"count": 0}

        def _counting_tokenize(text: str):
            calls["count"] += 1
            return original_tokenize(text)

        monkeypatch.setattr(morph_matcher, "_tokenize", _counting_tokenize)

        # NOTE: phrase tokenization still calls _tokenize(phrase_text) once
        # at the top of match_phrase_morphological_detailed — that is expected
        # and NOT a perf concern. We only assert that turn-text tokenization
        # is skipped when precomputed_turn_words is supplied.
        match_phrase_morphological_detailed(
            phrase_text="расторгнуть",
            word_distance=1,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
            precomputed_word_positions=[
                _find_word_positions(t["text"]) for t in turns
            ],
            precomputed_turn_words=[_tokenize(t["text"]) for t in turns],
        )
        # Only the phrase tokenization should fire — no per-turn tokenize.
        assert calls["count"] == 1, (
            f"Expected exactly 1 tokenize call (phrase only), "
            f"got {calls['count']}"
        )

    def test_find_word_positions_not_called_when_cache_supplied(
        self, monkeypatch
    ) -> None:
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}

        original = morph_matcher._find_word_positions
        calls = {"count": 0}

        def _counting(text: str):
            calls["count"] += 1
            return original(text)

        monkeypatch.setattr(morph_matcher, "_find_word_positions", _counting)

        match_phrase_morphological_detailed(
            phrase_text="расторгнуть",
            word_distance=1,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
            precomputed_word_positions=[
                _find_word_positions(t["text"]) for t in turns
            ],
            precomputed_turn_words=[_tokenize(t["text"]) for t in turns],
        )
        assert calls["count"] == 0, (
            f"Expected 0 _find_word_positions calls when cache supplied, "
            f"got {calls['count']}"
        )

    def test_internal_lazy_cache_avoids_recompute_within_call(
        self, monkeypatch
    ) -> None:
        """Without external cache, the internal lazy cache should ensure
        each turn is tokenized at most once per call (even though the
        sliding window iterates). This was already true before N18
        (tokenize happens once at the top of the per-turn loop), and the
        refactor preserves it."""
        turns = _make_turns()
        channel_map = {i: t["speaker"] for i, t in enumerate(turns)}

        original = morph_matcher._tokenize
        calls = {"count": 0}

        def _counting(text: str):
            calls["count"] += 1
            return original(text)

        monkeypatch.setattr(morph_matcher, "_tokenize", _counting)

        match_phrase_morphological_detailed(
            phrase_text="расторгнуть",
            word_distance=1,
            channel_constraint="ANY",
            turns=turns,
            channel_map=channel_map,
            is_exact=False,
        )
        # 1 (phrase) + 3 (turns, one tokenize each) = 4.
        assert calls["count"] == 4, (
            f"Expected 4 tokenize calls (1 phrase + 3 turns), "
            f"got {calls['count']}"
        )


# ═══════════════════════════════════════════════════════════════════════
# 3. End-to-end: search._search_recursive uses the cache
# ═══════════════════════════════════════════════════════════════════════


class TestSearchRecursiveUsesCache:
    """``_search_recursive`` precomputes word_positions + turn_words once
    per node and passes them to every condition. We verify this by
    monkeypatching morph_matcher._tokenize to count calls and asserting
    the total equals O(turns), not O(conditions × turns)."""

    @pytest.mark.asyncio
    async def test_search_tokenizes_each_turn_once_per_node(
        self, monkeypatch
    ) -> None:
        from app.models import (
            DictionaryCondition,
            DictionaryNode,
            DialogueTurn,
            ParsedDialog,
        )
        from app.services import search as search_module
        from app.services.search import run_hierarchical_search

        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(
                    turn_index=0,
                    speaker="Клиент",
                    text="я хочу расторгнуть договор сейчас",
                ),
                DialogueTurn(
                    turn_index=1,
                    speaker="Сотрудник",
                    text="давайте обсудим ситуацию подробнее",
                ),
                DialogueTurn(
                    turn_index=2,
                    speaker="Клиент",
                    text="отказываюсь от диагностики сегодня",
                ),
            ],
        )

        # Node with 3 conditions — all on the same turns.
        node = DictionaryNode(
            id="root",
            name="Multi-condition node",
            conditions=[
                DictionaryCondition(
                    text="расторгнуть",
                    word_distance=2,
                    word_count=1,
                    channel_constraint="ANY",
                ),
                DictionaryCondition(
                    text="обсудим",
                    word_distance=2,
                    word_count=1,
                    channel_constraint="ANY",
                ),
                DictionaryCondition(
                    text="отказываюсь",
                    word_distance=2,
                    word_count=1,
                    channel_constraint="ANY",
                ),
            ],
            children=[],
        )

        original = morph_matcher._tokenize
        calls = {"count": 0}

        def _counting(text: str):
            calls["count"] += 1
            return original(text)

        # Patch on morph_matcher module (the search._search_recursive
        # imports _tokenize FROM morph_matcher at call time inside the
        # try/except ImportError block, so monkeypatching the module
        # attribute is sufficient).
        monkeypatch.setattr(morph_matcher, "_tokenize", _counting)
        # Also patch search._do_match path indirectly — it imports
        # match_phrase_morphological_detailed from morph_matcher, which
        # in turn references module-level _tokenize — so the monkeypatch
        # is honoured.

        await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[node],
            cascade=False,
        )

        # Pre-N18 expectation: 3 conditions × 3 turns = 9 turn tokenizations
        # + 3 phrase tokenizations = 12.
        # With N18 precompute: 3 turns (precompute pass) + 3 phrases = 6.
        # We assert the precompute is in effect (≤ 6 turn-level calls),
        # with some tolerance for any additional calls from the phrase
        # path (lemmatize_text path is not used by match_phrase_morphological_detailed).
        assert calls["count"] <= 8, (
            f"Expected precompute to keep tokenize calls low, "
            f"got {calls['count']} (pre-N18 baseline was ~12)"
        )

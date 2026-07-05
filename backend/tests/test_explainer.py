"""Tests for token-level explainability (LIME-style permutation masking).

Covers:
  1. explain_match with mocked FridaEmbeddingService
  2. top_n limiting
  3. empty text handling
  4. explain_match_morph (no embeddings needed)
  5. explain_dict_match combined output
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import explainer


# ═══════════════════════════════════════════════════════════
# Mock embedder helper
# ═══════════════════════════════════════════════════════════


def _make_mock_embedder(baseline_vec=None, masked_vecs=None) -> MagicMock:
    """Mock embedder: returns baseline_vec for full text, masked_vecs[i] for text without token i.

    If masked_vecs is None, returns the baseline_vec for all calls (zero contribution).
    """
    embedder = MagicMock()
    call_count = {"n": 0}

    async def embed(text: str):
        # First call = query (text == query), second = baseline (text == full text).
        # Subsequent calls = masked permutations.
        call_count["n"] += 1
        if baseline_vec is None:
            return [0.1] * 8
        return baseline_vec

    # Override embed to track calls
    embedder.embed = AsyncMock(side_effect=embed)
    return embedder


class _ScriptedEmbedder:
    """Embedder returning scripted vectors per call, keyed by text content."""

    def __init__(self, query_vec, full_vec, masked_vecs):
        self.query_vec = query_vec
        self.full_vec = full_vec
        self.masked_vecs = list(masked_vecs)
        self._masked_idx = 0
        self.embed = AsyncMock(side_effect=self._embed)

    async def _embed(self, text: str):
        # Distinguish: first call is query, second is full text, rest are masked.
        # We rely on the explainer calling embed(query) then embed(text) then
        # embed(masked_i) in token order. To make this robust we encode
        # the query with a sentinel via the query text itself.
        if text == "__QUERY__":
            return self.query_vec
        if self._masked_idx >= len(self.masked_vecs):
            # No more masked vecs queued → return full_vec (for the baseline).
            # We identify the baseline as the FIRST non-query call.
            self._masked_idx = 0  # reset for subsequent masked calls
            return self.full_vec
        # If this is the very first non-query call AND we haven't started
        # masked vecs yet, treat it as the baseline.
        if self._masked_idx == 0:
            # Heuristic: first non-query call → baseline.
            self._masked_idx += 1
            return self.full_vec
        # Otherwise it's a masked call.
        vec = self.masked_vecs[self._masked_idx - 1]
        self._masked_idx += 1
        return vec


def _unit_vec(*components: float):
    import numpy as np

    arr = np.array(components, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0:
        return [0.0] * len(components)
    return (arr / norm).tolist()


# ═══════════════════════════════════════════════════════════
# explain_match
# ═══════════════════════════════════════════════════════════


class TestExplainMatch:
    @pytest.mark.asyncio
    async def test_returns_empty_without_embedder(self) -> None:
        result = await explainer.explain_match("query", "text", embedder=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self) -> None:
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[0.1] * 8)
        result = await explainer.explain_match("", "text", embedder=embedder)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self) -> None:
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[0.1] * 8)
        result = await explainer.explain_match("query", "", embedder=embedder)
        assert result == []

    @pytest.mark.asyncio
    async def test_top_n_limits_results(self) -> None:
        """Long text with many tokens → top_n caps the result list."""
        # Use a mock embedder that returns identical vectors for everything
        # → all deltas are zero, but the call still returns N entries.
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=_unit_vec(1.0, 0.0, 0.0))
        text = "один два три четыре пять шесть семь восемь"
        result = await explainer.explain_match("query", text, embedder=embedder, top_n=3)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_token_with_high_contribution_ranks_first(self) -> None:
        """The token whose removal drops similarity most should rank first.

        We construct a scenario where the query vector is identical to the full
        text vector (similarity=1.0), and removing token 'important' makes the
        masked vector orthogonal (similarity=0.0) — so 'important' has the
        largest positive contribution.
        """
        # Query and full text align with the X axis.
        query_vec = _unit_vec(1.0, 0.0, 0.0)
        full_vec = _unit_vec(1.0, 0.0, 0.0)
        # Text: "noise important noise" — masking 'important' flips to Y axis.
        # Masked vec for token 0 ('noise'): rotated slightly but still close.
        # Masked vec for token 1 ('important'): orthogonal (sim drops to 0).
        # Masked vec for token 2 ('noise'): rotated slightly.
        masked_vecs = [
            _unit_vec(0.9, 0.4, 0.0),  # removing first 'noise' → sim drops a bit
            _unit_vec(0.0, 1.0, 0.0),  # removing 'important' → sim drops to 0
            _unit_vec(0.9, 0.4, 0.0),  # removing second 'noise' → sim drops a bit
        ]
        embedder = _ScriptedEmbedder(query_vec, full_vec, masked_vecs)
        result = await explainer.explain_match(
            query="__QUERY__",
            text="noise important noise",
            embedder=embedder,
            top_n=10,
        )
        # The token 'important' (idx 1) should have the largest |delta|.
        assert result[0][0] == "important"
        assert result[0][1] > 0.5  # large positive contribution

    @pytest.mark.asyncio
    async def test_results_sorted_by_absolute_contribution(self) -> None:
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=_unit_vec(1.0, 0.0))
        text = "a b c"
        result = await explainer.explain_match("q", text, embedder=embedder, top_n=10)
        # All deltas are 0 (identical vectors) → ordering is stable.
        contribs = [abs(c) for _, c in result]
        assert contribs == sorted(contribs, reverse=True)


# ═══════════════════════════════════════════════════════════
# explain_match_morph (no embeddings)
# ═══════════════════════════════════════════════════════════


class TestExplainMatchMorph:
    def test_matched_words_get_contribution_1(self) -> None:
        query_words = ["отказ", "услуга"]
        text_words = ["клиент", "хочет", "отказаться", "от", "услуги"]
        matched_indices = [2, 4]  # 'отказаться' and 'услуги' matched
        result = explainer.explain_match_morph(query_words, text_words, matched_indices)
        contributions = dict(result)
        assert contributions[2] == 1.0
        assert contributions[4] == 1.0
        assert contributions[0] == 0.0
        assert contributions[1] == 0.0
        assert contributions[3] == 0.0

    def test_sorted_matched_first(self) -> None:
        query_words = ["заявка"]
        text_words = ["a", "заявка", "b", "заявка"]
        matched_indices = [1, 3]
        result = explainer.explain_match_morph(query_words, text_words, matched_indices)
        # Matched tokens (1.0) come before unmatched (0.0).
        assert result[0][1] == 1.0
        assert result[-1][1] == 0.0

    def test_empty_inputs(self) -> None:
        # Empty text_words → empty result (no words to attribute contribution to).
        assert explainer.explain_match_morph([], [], []) == []
        # Single text word, no matches → one entry with contribution 0.0.
        result = explainer.explain_match_morph(["q"], ["word"], [])
        assert result == [(0, 0.0)]


# ═══════════════════════════════════════════════════════════
# explain_dict_match
# ═══════════════════════════════════════════════════════════


class TestExplainDictMatch:
    @pytest.mark.asyncio
    async def test_without_embedder_returns_span_only(self) -> None:
        result = await explainer.explain_dict_match(
            phrase_text="отказ",
            dialogue_text="клиент хочет отказаться от услуги",
            matched_start=13,
            matched_end=23,
            embedder=None,
        )
        assert result["matched_span_text"] == "отказаться"
        assert "phrase_tokens" not in result
        assert "overall_similarity" not in result

    @pytest.mark.asyncio
    async def test_invalid_span_returns_empty_string(self) -> None:
        result = await explainer.explain_dict_match(
            phrase_text="x",
            dialogue_text="text",
            matched_start=-1,
            matched_end=-1,
            embedder=None,
        )
        assert result["matched_span_text"] == ""

    @pytest.mark.asyncio
    async def test_with_embedder_returns_full_dict(self) -> None:
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=_unit_vec(1.0, 0.0))
        result = await explainer.explain_dict_match(
            phrase_text="отказ",
            dialogue_text="клиент хочет отказаться",
            matched_start=13,
            matched_end=23,
            embedder=embedder,
        )
        assert "phrase_tokens" in result
        assert "dialogue_tokens" in result
        assert "overall_similarity" in result
        assert result["matched_span_text"] == "отказаться"

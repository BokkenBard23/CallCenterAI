"""Tests for TopicModeler (community detection + BM25 labels).

Covers:
  1. Mock embedder + small synthetic corpus → communities found
  2. Labels extracted (non-empty for non-trivial clusters)
  3. Single-doc corpus → single community
  4. Empty corpus → []
  5. networkx unavailable → graceful fallback
  6. get_topic_for_document after fit
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.topics import TopicModeler

# networkx is an optional dependency — TopicModeler gracefully returns []
# when it's not installed. Skip tests that require community detection.
pytest.importorskip(
    "networkx",
    reason="networkx not installed — TopicModeler community detection disabled",
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _make_embedder(vectors):
    """Create a mock embedder with embed_batch returning the given vectors."""
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(return_value=vectors)
    return embedder


def _orthogonal_vec(dim: int, idx: int):
    """Unit vector along axis `idx` in a `dim`-dimensional space."""
    v = [0.0] * dim
    v[idx] = 1.0
    return v


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestTopicModelerFit:
    @pytest.mark.asyncio
    async def test_empty_corpus_returns_empty(self) -> None:
        modeler = TopicModeler()
        result = await modeler.fit([], embedder=MagicMock())
        assert result == []

    @pytest.mark.asyncio
    async def test_single_doc_single_community(self) -> None:
        """One document → one community of size 1."""
        embedder = _make_embedder([_orthogonal_vec(8, 0)])
        modeler = TopicModeler(minscore=0.3, approximate=False)
        result = await modeler.fit(["один документ про заявку"], embedder=embedder)
        assert len(result) == 1
        assert result[0]["size"] == 1
        assert 0 in result[0]["doc_indices"]

    @pytest.mark.asyncio
    async def test_two_clusters_discovered(self) -> None:
        """Two clearly separated embedding clusters → two communities."""
        # Cluster A: docs 0, 1 — embeddings along axis 0.
        # Cluster B: docs 2, 3 — embeddings along axis 1.
        docs = [
            "заявка на отключение услуги",
            "оформить заявку на расторжение",
            "перевести деньги на счёт",
            "возврат платежа за подписку",
        ]
        vectors = [
            _orthogonal_vec(8, 0),
            _orthogonal_vec(8, 0),
            _orthogonal_vec(8, 1),
            _orthogonal_vec(8, 1),
        ]
        embedder = _make_embedder(vectors)
        modeler = TopicModeler(minscore=0.3, approximate=False)
        result = await modeler.fit(docs, embedder=embedder)

        # Two communities.
        assert len(result) == 2
        sizes = sorted(t["size"] for t in result)
        assert sizes == [2, 2]

    @pytest.mark.asyncio
    async def test_labels_extracted(self) -> None:
        """Topic labels should be non-empty for non-trivial corpora."""
        docs = [
            "заявка на отключение услуги",
            "оформить заявку на расторжение",
            "заявка заявка заявка",
        ]
        # All same direction → single community.
        vectors = [_orthogonal_vec(8, 0) for _ in docs]
        embedder = _make_embedder(vectors)
        modeler = TopicModeler(minscore=0.3, approximate=False, topn=5)
        result = await modeler.fit(docs, embedder=embedder)
        assert len(result) >= 1
        for topic in result:
            assert isinstance(topic["label"], list)
            assert len(topic["label"]) > 0

    @pytest.mark.asyncio
    async def test_approximate_mode(self) -> None:
        """Approximate mode (FAISS-kNN edges) should also discover clusters."""
        docs = [
            "заявка отключение",
            "заявка расторжение",
            "платёж возврат",
            "платёж подписка",
        ]
        vectors = [
            _orthogonal_vec(8, 0),
            _orthogonal_vec(8, 0),
            _orthogonal_vec(8, 1),
            _orthogonal_vec(8, 1),
        ]
        embedder = _make_embedder(vectors)
        modeler = TopicModeler(minscore=0.3, approximate=True)
        result = await modeler.fit(docs, embedder=embedder)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_empty(self) -> None:
        embedder = MagicMock()
        embedder.embed_batch = AsyncMock(side_effect=RuntimeError("api down"))
        modeler = TopicModeler()
        result = await modeler.fit(["doc1", "doc2"], embedder=embedder)
        assert result == []

    @pytest.mark.asyncio
    async def test_networkx_unavailable_falls_back(self) -> None:
        """When networkx is not installed, fit returns []."""
        embedder = _make_embedder([_orthogonal_vec(8, 0)])
        modeler = TopicModeler()
        with patch.object(TopicModeler, "is_networkx_available", staticmethod(lambda: False)):
            result = await modeler.fit(["doc"], embedder=embedder)
        assert result == []


class TestGetTopicForDocument:
    @pytest.mark.asyncio
    async def test_returns_topic_after_fit(self) -> None:
        docs = ["заявка отключение", "платёж возврат"]
        vectors = [_orthogonal_vec(8, 0), _orthogonal_vec(8, 1)]
        embedder = _make_embedder(vectors)
        modeler = TopicModeler(minscore=0.3, approximate=False)
        await modeler.fit(docs, embedder=embedder)
        topic = modeler.get_topic_for_document(0)
        assert topic is not None
        assert 0 in topic["doc_indices"]

    def test_returns_none_before_fit(self) -> None:
        modeler = TopicModeler()
        assert modeler.get_topic_for_document(0) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_doc(self) -> None:
        docs = ["заявка"]
        embedder = _make_embedder([_orthogonal_vec(8, 0)])
        modeler = TopicModeler(minscore=0.3, approximate=False)
        await modeler.fit(docs, embedder=embedder)
        assert modeler.get_topic_for_document(999) is None


class TestNetworkxAvailable:
    def test_returns_bool(self) -> None:
        assert isinstance(TopicModeler.is_networkx_available(), bool)

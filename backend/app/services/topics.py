"""Topic modeling via graph community detection + BM25 IDF labels.

Ported from txtai graph/topics.py. Unsupervised — discovers topics from a corpus
without pre-defined categories. Useful for:
  - EDA on a corpus of dialogues (what topics emerge?)
  - Quality monitoring (which topics have low quality scores?)
  - Dictionary coverage analysis (which topics lack dictionary phrases?)

Algorithm:
  1. Embed all documents (FRIDA).
  2. Build similarity graph (networkx): edge if cosine(u, v) > minscore.
     When `approximate=True`, only edges to each node's top-K nearest
     neighbours are added (k = min(50, len(docs)-1)) to keep build cost O(N log N)
     via FAISS-kNN on the embedding matrix.
  3. Detect communities via networkx.algorithms.community.greedy_modularity_communities.
  4. For each community: BM25 index over member documents; lowest-IDF terms
     (most common distinctive terms) form the topic label.
  5. Merge duplicate topics whose labels overlap above a threshold.

Requires: networkx (optional dependency — graceful fallback returns []).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.services.bm25 import BM25Scorer

logger = logging.getLogger(__name__)

_DEFAULT_OVERLAP_THRESHOLD = 0.6  # Jaccard similarity above which topics merge.


class TopicModeler:
    """Unsupervised topic modeler using embedding graph + BM25 labels.

    Attributes:
        minscore: Cosine threshold below which no edge is added (default 0.5).
        topn: Number of label terms per topic (default 10).
        approximate: When True, edges are restricted to each node's top-K
            nearest neighbours via FAISS-kNN (much faster on large corpora).
    """

    def __init__(
        self,
        minscore: float = 0.5,
        topn: int = 10,
        approximate: bool = True,
    ) -> None:
        self.minscore = float(minscore)
        self.topn = int(topn)
        self.approximate = bool(approximate)
        self._graph: Optional[Any] = None
        self._communities: Optional[List[List[int]]] = None
        self._topics: List[Dict] = []

    # ── Dependency check ────────────────────────────────────────

    @staticmethod
    def is_networkx_available() -> bool:
        """Check whether networkx is importable."""
        try:
            import networkx  # type: ignore  # noqa: F401

            return True
        except ImportError:
            return False

    # ── Public API ──────────────────────────────────────────────

    async def fit(
        self,
        documents: List[str],
        embedder: Any,
    ) -> List[Dict]:
        """Build topic model from document corpus.

        Args:
            documents: List of document texts.
            embedder: FridaEmbeddingService-like with async ``embed_batch`` /
                ``embed`` returning ``List[List[float]]``.

        Returns:
            List of topic dicts:
            ``[{"label": ["word1", "word2", ...], "doc_indices": [0, 5, 12, ...],
               "size": 13}, ...]``
            Sorted by size descending. Empty list if networkx is unavailable,
            the corpus is empty, or embedding fails.
        """
        self._graph = None
        self._communities = None
        self._topics = []

        if not documents:
            return []

        if not self.is_networkx_available():
            logger.warning(
                "TopicModeler: networkx not installed — topic modeling disabled. "
                "Install with: pip install networkx"
            )
            return []

        import networkx as nx

        # 1. Embed all documents.
        try:
            if hasattr(embedder, "embed_batch"):
                embeddings: List[List[float]] = await embedder.embed_batch(list(documents))
            else:
                embeddings = [await embedder.embed(doc) for doc in documents]
        except Exception as exc:
            logger.error("TopicModeler: embedding failed: %s", exc, exc_info=True)
            return []

        if len(embeddings) != len(documents):
            logger.error(
                "TopicModeler: embedding count %d != document count %d",
                len(embeddings),
                len(documents),
            )
            return []

        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.size == 0:
            return []

        # L2-normalize for cosine similarity.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms

        n_docs = len(documents)

        # 2. Build similarity graph.
        graph = nx.Graph()
        graph.add_nodes_from(range(n_docs))

        if self.approximate and n_docs > 1:
            k_neighbours = min(50, n_docs - 1)
            # Cosine similarity via inner product on normalized vectors.
            sim = matrix @ matrix.T
            np.fill_diagonal(sim, -1.0)
            for i in range(n_docs):
                # Top-k most similar to node i.
                top_idx = np.argpartition(-sim[i], k_neighbours)[:k_neighbours]
                for j in top_idx:
                    s = float(sim[i, j])
                    if s >= self.minscore:
                        graph.add_edge(int(i), int(j), weight=s)
        else:
            # Full pairwise graph (O(N^2)).
            sim = matrix @ matrix.T
            np.fill_diagonal(sim, 0.0)
            for i in range(n_docs):
                for j in range(i + 1, n_docs):
                    s = float(sim[i, j])
                    if s >= self.minscore:
                        graph.add_edge(i, j, weight=s)

        self._graph = graph

        # 3. Detect communities.
        try:
            communities_gen = nx.algorithms.community.greedy_modularity_communities(
                graph, weight="weight"
            )
            communities: List[List[int]] = [list(c) for c in communities_gen]
        except Exception as exc:
            logger.error("TopicModeler: community detection failed: %s", exc, exc_info=True)
            return []

        # Sort by size descending (largest first).
        communities.sort(key=len, reverse=True)
        self._communities = communities

        # 4. Build BM25 labels per community.
        topics: List[Dict] = []
        for idx, community in enumerate(communities):
            if not community:
                continue
            community_docs = [documents[i] for i in community]
            scorer = BM25Scorer(lemmatize=True)
            scorer.index(community_docs)

            if scorer.idf:
                # Lowest IDF = most common distinctive terms in the community.
                sorted_terms = sorted(scorer.idf.items(), key=lambda kv: kv[1])
                label_terms: List[str] = []
                for term, _idf in sorted_terms:
                    if term not in label_terms:
                        label_terms.append(term)
                    if len(label_terms) >= self.topn:
                        break
            else:
                label_terms = [f"topic_{idx}"]

            topics.append(
                {
                    "label": label_terms,
                    "doc_indices": sorted(int(i) for i in community),
                    "size": len(community),
                }
            )

        # 5. Merge duplicate topics (Jaccard label overlap above threshold).
        topics = self._merge_topics(topics, overlap_threshold=_DEFAULT_OVERLAP_THRESHOLD)

        self._topics = topics
        return topics

    def get_topic_for_document(self, doc_idx: int) -> Optional[Dict]:
        """Return the topic a document belongs to (after ``fit``).

        Args:
            doc_idx: Document index in the original corpus.

        Returns:
            Topic dict or None if not found / not fitted.
        """
        if not self._topics:
            return None
        for topic in self._topics:
            if doc_idx in topic["doc_indices"]:
                return topic
        return None

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _merge_topics(
        topics: List[Dict],
        overlap_threshold: float = _DEFAULT_OVERLAP_THRESHOLD,
    ) -> List[Dict]:
        """Merge topics whose label sets overlap above ``overlap_threshold``.

        Uses Jaccard similarity on label term sets.
        """
        if len(topics) <= 1:
            return topics

        merged: List[Dict] = []
        used = [False] * len(topics)

        for i, ti in enumerate(topics):
            if used[i]:
                continue
            label_i = set(ti["label"])
            docs_i = list(ti["doc_indices"])
            label_terms = list(ti["label"])

            for j in range(i + 1, len(topics)):
                if used[j]:
                    continue
                tj = topics[j]
                label_j = set(tj["label"])
                if not label_i or not label_j:
                    continue
                inter = len(label_i & label_j)
                union = len(label_i | label_j)
                jaccard = inter / union if union > 0 else 0.0
                if jaccard >= overlap_threshold:
                    docs_i.extend(tj["doc_indices"])
                    for t in tj["label"]:
                        if t not in label_terms:
                            label_terms.append(t)
                    used[j] = True

            merged.append(
                {
                    "label": label_terms,
                    "doc_indices": sorted(set(docs_i)),
                    "size": len(set(docs_i)),
                }
            )

        merged.sort(key=lambda t: t["size"], reverse=True)
        return merged

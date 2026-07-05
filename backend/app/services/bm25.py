"""BM25 sparse scorer with configurable k1/b and Robertson IDF.

Ported from txtai scoring/bm25.py. Russian-aware: uses razdel for tokenization
(we already depend on it) + optional pymorphy3 lemmatization + configurable stop-words.

Used as a third signal in hybrid_search.py fusion (alongside FAISS cosine + morph BOW).
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Default Russian stop-words (~40 most common)
# Kept conservative — only high-frequency function words that carry
# no discriminative signal for call-center dialogue search.
# ═══════════════════════════════════════════════════════════════
_DEFAULT_RU_STOPWORDS: Set[str] = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со",
    "как", "а", "то", "все", "она", "так", "его", "но", "да",
    "ты", "к", "у", "же", "вы", "за", "бы", "по", "только",
    "ее", "мне", "было", "вот", "от", "меня", "о", "из", "ему",
    "теперь", "когда", "даже", "ну", "вдруг", "ли", "если",
}


def _razdel_tokens(text: str) -> List[str]:
    """Tokenize text via razdel — same library as Chunker for consistency."""
    try:
        from razdel import tokenize as razdel_tokenize

        return [t.text.lower() for t in razdel_tokenize(text)]
    except Exception as exc:  # pragma: no cover — razdel is a hard dep
        logger.warning("razdel.tokenize failed in BM25, regex fallback: %s", exc)
        import re

        return re.findall(r"[а-яёa-z0-9]+", text.lower())


# Lazy pymorphy3 — reused from morph_matcher if available.
@lru_cache(maxsize=50000)
def _lemma_cached(word: str) -> str:
    """Lemmatize a single token; cached. Falls back to the word itself."""
    try:
        from app.services.morph_matcher import get_lemma

        return get_lemma(word)
    except Exception:  # pragma: no cover — morph_matcher always importable in app
        return word


class BM25Scorer:
    """BM25 scorer (Robertson IDF, configurable k1/b).

    Index a corpus of documents, then score queries against them.
    Supports Russian lemmatization via pymorphy3 (optional, off by default for speed).

    Formula (Robertson):
        idf(t)   = log(1 + (N - df + 0.5) / (df + 0.5))   # always >= 0
        score(t) = idf(t) * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
        score(q,d) = Σ_t score(t)
    """

    def __init__(
        self,
        k1: float = 1.2,
        b: float = 0.75,
        lemmatize: bool = False,
        stop_words: Optional[Set[str]] = None,
    ) -> None:
        """Initialize BM25Scorer.

        Args:
            k1: Term-frequency saturation parameter (default 1.2).
            b: Length-normalization parameter (default 0.75, range 0..1).
            lemmatize: If True, lemmatize tokens via pymorphy3 (slower but
                matches morph_matcher behaviour). Default False for speed.
            stop_words: Set of stop-words to filter. Defaults to a small
                Russian list defined in this module.
        """
        self.k1 = k1
        self.b = b
        self.lemmatize = lemmatize
        self.stop_words: Set[str] = stop_words if stop_words is not None else set(_DEFAULT_RU_STOPWORDS)

        # index state
        self.doc_tokens: List[List[str]] = []
        self.doc_freqs: List[Counter] = []  # per-doc term frequencies
        self.idf: Dict[str, float] = {}
        self.avgdl: float = 0.0
        self.total_docs: int = 0
        self._total_tokens: int = 0

    # ── Tokenization ────────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        """razdel tokenize → lowercase → stop-word removal → optional lemmatization."""
        tokens = _razdel_tokens(text)
        if self.lemmatize:
            tokens = [_lemma_cached(t) for t in tokens]
        # Stop-word removal AFTER lemmatization so stop-words match lemmas too
        return [t for t in tokens if t and t not in self.stop_words]

    # ── Indexing ────────────────────────────────────────────────

    def index(self, documents: Iterable[str]) -> None:
        """Build BM25 index from corpus. Resets any previous index.

        Args:
            documents: Iterable of document strings.
        """
        # Reset state
        self.doc_tokens = []
        self.doc_freqs = []
        self.idf = {}
        self.avgdl = 0.0
        self.total_docs = 0
        self._total_tokens = 0

        # Document frequency: number of docs containing each term
        df: Counter = Counter()

        for doc in documents:
            if doc is None:
                doc = ""
            tokens = self._tokenize(doc)
            self.doc_tokens.append(tokens)
            freq = Counter(tokens)
            self.doc_freqs.append(freq)
            self._total_tokens += len(tokens)
            for term in freq:  # unique terms only
                df[term] += 1
            self.total_docs += 1

        # Compute avgdl
        self.avgdl = (self._total_tokens / self.total_docs) if self.total_docs > 0 else 0.0

        # Robertson IDF — never negative (the `1 +` inside log guarantees it).
        N = self.total_docs
        for term, dfreq in df.items():
            self.idf[term] = math.log(1.0 + (N - dfreq + 0.5) / (dfreq + 0.5))

        logger.debug(
            "BM25 index built: %d docs, %d unique terms, avgdl=%.2f",
            self.total_docs,
            len(self.idf),
            self.avgdl,
        )

    # ── Scoring ─────────────────────────────────────────────────

    def score(self, query: str, top_k: int = 50) -> List[Tuple[int, float]]:
        """Score query against indexed docs. Returns sorted descending.

        Args:
            query: Query text.
            top_k: Maximum number of results to return.

        Returns:
            List of (doc_idx, score) tuples sorted by score descending.
            Empty if index is empty or query has no indexed terms.
        """
        if not self.is_indexed:
            return []

        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        # Aggregate query term frequencies (a term repeated in query is counted).
        q_freq: Counter = Counter(query_terms)

        scores: List[Tuple[int, float]] = []
        for doc_idx in range(self.total_docs):
            s = self._score_doc(q_freq, doc_idx)
            if s > 0.0:
                scores.append((doc_idx, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        if top_k is not None and top_k >= 0:
            scores = scores[:top_k]
        return scores

    def score_document(self, query: str, doc_idx: int) -> float:
        """Score a single document against query (incremental use).

        Args:
            query: Query text.
            doc_idx: Document index in the corpus.

        Returns:
            BM25 score (0.0 if doc has no matching terms or index is empty).
        """
        if not self.is_indexed:
            return 0.0
        if doc_idx < 0 or doc_idx >= self.total_docs:
            return 0.0

        query_terms = self._tokenize(query)
        if not query_terms:
            return 0.0

        q_freq: Counter = Counter(query_terms)
        return self._score_doc(q_freq, doc_idx)

    def _score_doc(self, q_freq: Counter, doc_idx: int) -> float:
        """Compute BM25 score for a single doc given query term frequencies."""
        doc_freq = self.doc_freqs[doc_idx]
        dl = len(self.doc_tokens[doc_idx])
        # Guard against div-by-zero when avgdl is 0 (e.g. all docs empty)
        denom_avgdl = self.avgdl if self.avgdl > 0 else 1.0
        score = 0.0
        for term, qf in q_freq.items():
            idf = self.idf.get(term)
            if idf is None:
                continue
            freq = doc_freq.get(term, 0)
            if freq == 0:
                continue
            # Standard BM25 saturation term.
            k = self.k1 * (1.0 - self.b + self.b * (dl / denom_avgdl))
            score += idf * (freq * (self.k1 + 1.0)) / (freq + k)
        return score

    # ── Status ─────────────────────────────────────────────────

    @property
    def is_indexed(self) -> bool:
        """True if the index contains at least one document."""
        return self.total_docs > 0

    def get_stats(self) -> Dict[str, object]:
        """Return observability stats."""
        return {
            "total_docs": self.total_docs,
            "total_unique_terms": len(self.idf),
            "total_tokens": self._total_tokens,
            "avgdl": round(self.avgdl, 4),
            "k1": self.k1,
            "b": self.b,
            "lemmatize": self.lemmatize,
        }

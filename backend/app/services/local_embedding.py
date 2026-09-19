"""Local TF-IDF embedding service (offline fallback for FRIDA).

Provides :class:`LocalTfidfEmbeddingService` — a fully offline embedding
provider that implements the same async interface as
:class:`app.services.embedding.FridaEmbeddingService`:

  - ``await embed(text) -> List[float]``
  - ``await embed_batch(texts) -> List[List[float]]`` (alias: ``embed_texts``)
  - ``await is_available() -> bool`` (always True — no network needed)
  - ``get_stats() -> dict``

Design (approved one-run completion plan, Wave 1):
  - Pure numpy + collections.Counter — NO sklearn, NO model downloads,
    NO network access.
  - Russian tokenization via razdel (already in requirements).
  - TF-IDF is fitted on the corpus at index time (``embed_batch`` performs
    an incremental ``partial_fit`` before transforming, so every indexing
    pass extends the vocabulary/IDF statistics; query ``embed`` only
    transforms — it never mutates the fitted state).
  - Vector dimensionality = vocabulary size, capped at ``dimension``
    (default 1536, aligned with ``settings.vector_store_dimension`` so the
    FAISS VectorStore accepts the vectors without any changes).
  - **Stable coordinates (append-only vocabulary):** once a token receives
    a vector index, that index NEVER changes — new tokens are appended at
    the end of the vocabulary (within one ``partial_fit`` call the new
    tokens are added in sorted order, so fitting the same corpus as a
    single batch is fully deterministic). There is no re-sorting at any
    point after init, which means FAISS vectors stored earlier remain
    aligned with query vectors computed later in the same session.
  - **Frozen IDF:** the IDF weight of each token is computed once — at the
    moment the token first enters the vocabulary — and never changes after
    that. Combined with stable indices this gives the actual guarantee:
    *a previously embedded text re-embedded later in the same session
    yields the exact same vector*, so exact-match queries keep cosine 1.0
    no matter how much the corpus grows afterwards.
  - ``save()``/``load()`` persist the vocabulary **in insertion order**
    (plus frozen IDF weights and corpus statistics) next to the FAISS
    index, so a restarted process reproduces the same vector space.

Known trade-offs (documented, accepted):
  - IDF values do NOT improve as the corpus grows: a token that later
    becomes common keeps the (higher) IDF it had at first fit. This is
    the price of the immutability guarantee above and matches the
    "freeze at first fit" policy chosen for a local fallback provider.
  - When the vocabulary reaches ``dimension``, it freezes: new unseen
    tokens are ignored (deterministic, keeps previously stored vectors
    meaningful).

This module is the "local" leg of ``EMBEDDING_PROVIDER=frida|local|auto``
(see :mod:`app.services.embedding_factory`).
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Vocabulary file name used for persistence (stored inside the vector store
# index directory so the TF-IDF space and the FAISS index live together).
VOCAB_FILENAME = "local_tfidf_vocab.json"

# Control-character sanitization (mirrors FridaEmbeddingService._sanitize_text).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_DEFAULT_DIMENSION = 1536
_DEFAULT_MAX_TEXT_LENGTH = 5000
_DEFAULT_MIN_TOKEN_LENGTH = 2


def _tokenize(text: str, min_token_length: int = _DEFAULT_MIN_TOKEN_LENGTH) -> List[str]:
    """Tokenize Russian/English text via razdel.

    Lowercases tokens and keeps only alphabetic tokens of at least
    ``min_token_length`` characters. Digits/punctuation are dropped —
    standard practice for TF-IDF on dialogue transcripts.

    Args:
        text: Input text.
        min_token_length: Minimum token length to keep.

    Returns:
        List of lowercase tokens.
    """
    from razdel import tokenize as razdel_tokenize

    tokens: List[str] = []
    for tok in razdel_tokenize(text):
        word = tok.text.lower().strip()
        # Keep only alphabetic tokens (Cyrillic + Latin), drop numbers/punct
        if len(word) >= min_token_length and any(ch.isalpha() for ch in word):
            tokens.append(word)
    return tokens


class LocalTfidfEmbeddingService:
    """Offline TF-IDF embedding service (FRIDA fallback).

    Same async interface as FridaEmbeddingService, but computes vectors
    locally: no API calls, no downloads, no network. See module docstring
    for design details and trade-offs.
    """

    provider_name = "local"

    def __init__(
        self,
        dimension: int = _DEFAULT_DIMENSION,
        max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH,
        min_token_length: int = _DEFAULT_MIN_TOKEN_LENGTH,
    ) -> None:
        """Initialize the local TF-IDF embedding service.

        Args:
            dimension: Vector dimensionality (= max vocabulary size).
                Must match the VectorStore dimension (1536 by default).
            max_text_length: Maximum text length in characters (sanitization).
            min_token_length: Minimum token length to keep during tokenization.
        """
        self.dimension = dimension
        self.max_text_length = max_text_length
        self.min_token_length = min_token_length

        # Vocabulary in INSERTION order (append-only: a token's index never
        # changes once assigned) + token → index map.
        self._vocab: List[str] = []
        self._token_to_idx: Dict[str, int] = {}

        # Frozen IDF weights: computed once when a token first enters the
        # vocabulary, never recomputed — keeps earlier vectors reproducible.
        self._idf_frozen: Dict[str, float] = {}

        # Corpus statistics for IDF: document frequency per token and
        # total number of fitted documents.
        self._df: Counter[str] = Counter()
        self._n_docs = 0

        # Observability counters.
        self._total_embed_calls = 0
        self._total_fit_calls = 0

    # ── Sanitization ───────────────────────────────────────────

    def _sanitize(self, text: str) -> str:
        """Remove control characters and truncate to max_text_length."""
        text = _CONTROL_CHARS_RE.sub("", text)
        return text[: self.max_text_length]

    # ── Fitting ────────────────────────────────────────────────

    @property
    def vocab_size(self) -> int:
        """Current vocabulary size (= number of non-zero-capable dims)."""
        return len(self._vocab)

    def partial_fit(self, texts: List[str]) -> int:
        """Incrementally fit the TF-IDF model on new documents.

        Updates document-frequency counters and extends the vocabulary.
        The vocabulary is strictly **append-only**: new tokens are appended
        at the end (sorted within this batch of additions, capped at
        ``dimension``); existing token indices are NEVER reassigned, so
        vectors embedded earlier stay valid. The IDF weight of each new
        token is frozen at the moment it enters the vocabulary.

        Args:
            texts: List of corpus documents (dialogue chunks, dictionary
                phrases, etc.).

        Returns:
            Number of new tokens added to the vocabulary.
        """
        if not texts:
            return 0

        new_tokens: set[str] = set()
        for text in texts:
            tokens = set(_tokenize(self._sanitize(text), self.min_token_length))
            self._df.update(tokens)
            self._n_docs += 1
            new_tokens.update(tok for tok in tokens if tok not in self._token_to_idx)

        # Cap vocabulary at dimension; freeze growth beyond the cap
        # (deterministic — previously emitted vectors stay meaningful).
        capacity = self.dimension - len(self._vocab)
        if capacity <= 0:
            if new_tokens:
                logger.warning(
                    "LocalTfidfEmbeddingService: vocabulary frozen at %d tokens "
                    "(dimension cap) — %d new token(s) ignored",
                    self.dimension,
                    len(new_tokens),
                )
            return 0

        # Append-only: sort only the NEW tokens (determinism per batch),
        # then append them without touching existing indices.
        added = sorted(new_tokens)[:capacity]
        for tok in added:
            self._token_to_idx[tok] = len(self._vocab)
            self._vocab.append(tok)
            # Freeze the IDF weight at first fit (df/n_docs already include
            # the current batch — counters were updated above).
            self._idf_frozen[tok] = self._idf(tok)
        self._total_fit_calls += 1

        if len(added) < len(new_tokens):
            logger.warning(
                "LocalTfidfEmbeddingService: vocabulary cap reached — "
                "%d of %d new token(s) dropped",
                len(new_tokens) - len(added),
                len(new_tokens),
            )
        return len(added)

    # Alias for explicit full-fit semantics (same incremental op).
    fit = partial_fit

    def _idf(self, token: str) -> float:
        """Smoothed inverse document frequency (sklearn-style).

        idf(t) = ln((1 + N) / (1 + df(t))) + 1

        The +1 smoothing avoids division by zero for unseen tokens and
        keeps the formula identical to scikit-learn's TfidfVectorizer.

        NOTE: this is the *current-stats* IDF. It is used to compute a
        token's weight ONCE (frozen at first fit, see ``partial_fit``);
        ``transform`` always uses the frozen value so that previously
        stored vectors stay reproducible as the corpus grows.
        """
        df = self._df.get(token, 0)
        return math.log((1.0 + self._n_docs) / (1.0 + df)) + 1.0

    # ── Transform ──────────────────────────────────────────────

    def transform(self, text: str) -> List[float]:
        """Vectorize a single text into the fitted TF-IDF space.

        Unseen tokens are ignored (standard TF-IDF behaviour). The result
        is L2-normalized so FAISS IndexFlatIP yields cosine similarity.
        Returns a zero vector when the text contains no known tokens
        (VectorStore._normalize protects against zero norms).

        Args:
            text: Input text.

        Returns:
            List of ``dimension`` floats (L2-normalized TF-IDF vector).
        """
        vector = np.zeros(self.dimension, dtype=np.float32)
        tokens = _tokenize(self._sanitize(text), self.min_token_length)
        if not tokens:
            return vector.tolist()

        counts = Counter(tokens)
        total = len(tokens)
        for token, count in counts.items():
            idx = self._token_to_idx.get(token)
            if idx is None:
                continue  # OOV token (not fitted or vocab frozen)
            tf = count / total
            # Frozen IDF (assigned at first fit) — never drifts, so earlier
            # vectors remain comparable to later query vectors.
            weight = self._idf_frozen.get(token)
            if weight is None:  # defensive: vocab token without frozen idf
                weight = self._idf(token)
            vector[idx] = tf * weight

        norm = float(np.linalg.norm(vector))
        if norm > 0.0:
            vector /= norm
        return vector.tolist()

    # ── Public API (FridaEmbeddingService-compatible) ──────────

    async def embed(self, text: str) -> List[float]:
        """Embed a single text (transform only — no fitting)."""
        self._total_embed_calls += 1
        return self.transform(text)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts (fit on them first, then transform).

        The incremental fit at index time is what makes the local provider
        a real semantic-search backend: every indexed corpus grows the
        TF-IDF space. Query-side ``embed`` never mutates the state.
        """
        if not texts:
            return []
        self.partial_fit(texts)
        self._total_embed_calls += len(texts)
        return [self.transform(t) for t in texts]

    # Alias for dict_mining.py compatibility (embed_texts → embed_batch).
    embed_texts = embed_batch

    async def is_available(self) -> bool:
        """Local provider is always available (no network dependency)."""
        return True

    def get_stats(self) -> Dict[str, object]:
        """Service statistics for observability."""
        return {
            "provider": self.provider_name,
            "dimension": self.dimension,
            "vocab_size": self.vocab_size,
            "n_docs_fitted": self._n_docs,
            "total_embed_calls": self._total_embed_calls,
            "total_fit_calls": self._total_fit_calls,
        }

    # ── Persistence ─────────────────────────────────────────────

    def save(self, path: str) -> None:
        """Persist the fitted vocabulary + statistics to a directory.

        Writes ``local_tfidf_vocab.json`` into ``path`` so that a restarted
        process (with the same FAISS index) reproduces the same vector
        space. The vocabulary is persisted **in insertion order** (token
        indices are position-dependent — reordering would invalidate every
        stored vector), together with the frozen IDF weights and corpus
        statistics. Without this file, persisted vectors are only valid
        within the original session — the file is the recovery mechanism.

        Args:
            path: Directory path (same directory as the FAISS index).
        """
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        payload = {
            "dimension": self.dimension,
            "vocab": self._vocab,
            "idf_frozen": self._idf_frozen,
            "df": dict(self._df),
            "n_docs": self._n_docs,
        }
        vocab_file = target / VOCAB_FILENAME
        with open(vocab_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        logger.info(
            "LocalTfidfEmbeddingService: vocabulary saved to %s (%d tokens)",
            vocab_file,
            self.vocab_size,
        )

    def load(self, path: str) -> bool:
        """Restore the fitted vocabulary + statistics from a directory.

        Restore the vocabulary **in the saved insertion order** — never
        re-sort: token indices are position-dependent and any reordering
        would misalign previously stored FAISS vectors. Frozen IDF weights
        are restored too (files saved by older versions without the
        ``idf_frozen`` key fall back to recomputing IDF from the stored
        corpus statistics, which reproduces the old file's semantics).

        Args:
            path: Directory containing ``local_tfidf_vocab.json``.

        Returns:
            True if the vocabulary was restored, False if no file exists.
        """
        vocab_file = Path(path) / VOCAB_FILENAME
        if not vocab_file.exists():
            return False

        with open(vocab_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if payload.get("dimension") != self.dimension:
            logger.warning(
                "LocalTfidfEmbeddingService: saved dimension %s != current %s "
                "— ignoring saved vocabulary",
                payload.get("dimension"),
                self.dimension,
            )
            return False

        self._vocab = list(payload.get("vocab", []))
        self._token_to_idx = {tok: i for i, tok in enumerate(self._vocab)}
        self._df = Counter(payload.get("df", {}))
        self._n_docs = int(payload.get("n_docs", 0))
        idf_saved = payload.get("idf_frozen")
        if isinstance(idf_saved, dict):
            self._idf_frozen = {str(tok): float(w) for tok, w in idf_saved.items()}
        else:
            # Legacy file (pre-frozen-IDF format): recompute from stats.
            self._idf_frozen = {tok: self._idf(tok) for tok in self._vocab}
        logger.info(
            "LocalTfidfEmbeddingService: vocabulary loaded from %s "
            "(%d tokens, %d docs)",
            vocab_file,
            self.vocab_size,
            self._n_docs,
        )
        return True

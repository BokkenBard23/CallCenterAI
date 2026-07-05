"""Token-level explainability via permutation masking (LIME-style).

Ported from txtai embeddings/search/explain.py. For each token in a text,
removes it and measures the delta in similarity to the query. Tokens whose
removal causes the largest drop in similarity are the most important for the match.

Use cases:
  - Dictionary editor UI: highlight WHICH tokens in a phrase drove the match
  - Debug false positives: see which words are causing spurious matches
  - Quality assurance: verify morphological matching is token-aware
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Reuse our authoritative tokenizer so explanations are consistent with
# morph_matcher / bm25 token boundaries.
try:
    from app.services.morph_matcher import _tokenize as _morph_tokenize
except Exception:  # pragma: no cover — morph_matcher always importable in app
    _morph_tokenize = None  # type: ignore[assignment]


def _tokenize_for_explain(text: str) -> List[str]:
    """Tokenize text for explanation, falling back to razdel then regex."""
    if _morph_tokenize is not None:
        try:
            return _morph_tokenize(text)
        except Exception as exc:  # pragma: no cover
            logger.debug("morph_matcher._tokenize failed in explainer: %s", exc)
    try:
        from razdel import tokenize as razdel_tokenize

        return [t.text.lower() for t in razdel_tokenize(text)]
    except Exception:  # pragma: no cover
        import re

        return re.findall(r"[а-яёa-z0-9]+", text.lower())


async def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity for two equal-length float vectors."""
    arr_a = np.asarray(a, dtype=np.float32)
    arr_b = np.asarray(b, dtype=np.float32)
    if arr_a.size == 0 or arr_b.size == 0 or arr_a.size != arr_b.size:
        return 0.0
    na = float(np.linalg.norm(arr_a))
    nb = float(np.linalg.norm(arr_b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(arr_a, arr_b) / (na * nb))


async def explain_match(
    query: str,
    text: str,
    embedder: Optional[Any] = None,
    top_n: int = 10,
) -> List[Tuple[str, float]]:
    """Explain which tokens in `text` contribute most to similarity with `query`.

    For each token in text, computes similarity(query, text_without_token) and
    returns delta = similarity(query, text) - similarity(query, text_without_token).
    Positive delta = token contributed to match; negative = token hurt match.

    Args:
        query: Query phrase.
        text: Candidate text (e.g., a dialogue turn).
        embedder: FridaEmbeddingService-like instance with async `embed(text) -> List[float]`.
            If None, the caller MUST supply one — we do not auto-create a network
            client here (would require API key + httpx pool).
        top_n: Return top-N tokens by absolute contribution.

    Returns:
        List of (token, contribution) sorted by absolute contribution descending.
        Empty if text has no tokens or embedder is unavailable.
    """
    if not query or not text:
        return []

    if embedder is None:
        logger.warning("explain_match called without embedder — returning []")
        return []

    tokens = _tokenize_for_explain(text)
    if not tokens:
        return []

    try:
        query_vec = await embedder.embed(query)
        baseline_vec = await embedder.embed(text)
    except Exception as exc:
        logger.error("explain_match: embedding failed: %s", exc, exc_info=True)
        return []

    baseline_sim = await _cosine_sim(query_vec, baseline_vec)

    contributions: List[Tuple[str, float]] = []
    for i in range(len(tokens)):
        # Build text without token i (preserves token order with whitespace join).
        masked_tokens = tokens[:i] + tokens[i + 1:]
        masked_text = " ".join(masked_tokens)
        if not masked_text.strip():
            # Removing this token empties the text — full contribution = baseline.
            contributions.append((tokens[i], baseline_sim))
            continue

        try:
            masked_vec = await embedder.embed(masked_text)
        except Exception as exc:
            logger.warning("explain_match: embedding masked text failed at i=%d: %s", i, exc)
            continue

        masked_sim = await _cosine_sim(query_vec, masked_vec)
        delta = baseline_sim - masked_sim
        contributions.append((tokens[i], float(delta)))

    # Sort by absolute contribution descending.
    contributions.sort(key=lambda kv: abs(kv[1]), reverse=True)

    if top_n is not None and top_n >= 0:
        contributions = contributions[:top_n]
    return contributions


def explain_match_morph(
    query_words: List[str],
    text_words: List[str],
    matched_indices: List[int],
) -> List[Tuple[int, float]]:
    """Morph-level explainability (no embeddings needed).

    For morph BOW matching: returns per-word contribution based on
    whether the word is in the query lemmatized set. Faster than embedding-based,
    uses our existing morph_matcher lemmatization.

    Args:
        query_words: Query tokenized into words.
        text_words: Text tokenized into words.
        matched_indices: Indices in text_words that matched (from morph_matcher).

    Returns:
        [(word_idx, contribution), ...] where contribution is 1.0 for matched,
        0.0 for unmatched. Sorted by contribution descending (matched first).
    """
    matched_set = set(matched_indices)
    contributions: List[Tuple[int, float]] = [
        (idx, 1.0 if idx in matched_set else 0.0)
        for idx in range(len(text_words))
    ]
    # Sort: matched (1.0) first, then by original index for stable ordering.
    contributions.sort(key=lambda kv: (-kv[1], kv[0]))
    return contributions


async def explain_dict_match(
    phrase_text: str,
    dialogue_text: str,
    matched_start: int,
    matched_end: int,
    embedder: Optional[Any] = None,
) -> dict:
    """Combined explanation for a dictionary match.

    Args:
        phrase_text: The dictionary phrase that matched.
        dialogue_text: The dialogue turn text.
        matched_start: Character offset of the match start in dialogue_text.
        matched_end: Character offset of the match end in dialogue_text.
        embedder: FridaEmbeddingService-like instance. Optional — when None,
            `phrase_tokens` and `overall_similarity` are omitted.

    Returns:
        Dict with keys:
          - phrase_tokens: [(token, contribution), ...] (only if embedder supplied)
          - dialogue_tokens: [(token, contribution), ...] (only if embedder supplied)
          - matched_span_text: dialogue_text[matched_start:matched_end]
          - overall_similarity: float (only if embedder supplied)
    """
    result: dict = {}

    # Clamp span to valid range; non-fatal if offsets are -1 (not computed).
    if 0 <= matched_start < matched_end <= len(dialogue_text):
        result["matched_span_text"] = dialogue_text[matched_start:matched_end]
    else:
        result["matched_span_text"] = ""

    if embedder is None:
        return result

    try:
        phrase_contribs = await explain_match(
            query=phrase_text,
            text=dialogue_text,
            embedder=embedder,
            top_n=10,
        )
    except Exception as exc:
        logger.error("explain_dict_match: phrase explain failed: %s", exc, exc_info=True)
        phrase_contribs = []

    try:
        query_vec = await embedder.embed(phrase_text)
        text_vec = await embedder.embed(dialogue_text)
        overall = await _cosine_sim(query_vec, text_vec)
    except Exception as exc:
        logger.error("explain_dict_match: similarity failed: %s", exc, exc_info=True)
        overall = 0.0

    result["phrase_tokens"] = phrase_contribs
    result["dialogue_tokens"] = phrase_contribs  # tokens of dialogue_text (same call)
    result["overall_similarity"] = float(overall)
    return result

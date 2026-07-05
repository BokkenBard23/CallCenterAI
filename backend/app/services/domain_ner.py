"""Domain-specific NER via GLiNER (zero-shot, label-agnostic).

GLiNER allows extracting entities with custom labels (e.g., "тариф", "сим-карта",
"заявка", "договор", "обращение") without model retraining. Supplements Natasha
(which handles standard PER/LOC/ORG).

Used in chunker.py to enrich ChunkMetadata.entities with domain entities,
which boosts hybrid search relevance for call-center domain queries.

GLiNER is optional — if the library or model isn't installed, falls back to
Natasha-only entities with a logged warning.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default domain entity labels for telecom / call-center.
DEFAULT_DOMAIN_LABELS: List[str] = [
    "тариф",
    "сим-карта",
    "заявка",
    "договор",
    "обращение",
    "услуга",
    "абонент",
    "номер",
    "счёт",
    "платёж",
    "баланс",
    "подписка",
    "промо",
    "акция",
    "скидка",
]

# Lazy-loaded GLiNER model (heavy — don't import at module level).
_gliner_model = None  # type: Optional[object]
_gliner_available: Optional[bool] = None


def is_gliner_available() -> bool:
    """Check if GLiNER library and a model can be loaded.

    Returns:
        True if the `gliner` Python package is importable. Model loading is
        deferred to first call of `extract_domain_entities`.
    """
    global _gliner_available
    if _gliner_available is None:
        try:
            import gliner  # type: ignore  # noqa: F401

            _gliner_available = True
        except ImportError:
            _gliner_available = False
            logger.info(
                "GLiNER not installed — domain NER falls back to Natasha only. "
                "Install with: pip install gliner"
            )
    return _gliner_available


@lru_cache(maxsize=1)
def _get_gliner_model() -> Optional[object]:
    """Load GLiNER model (lazy, cached).

    Returns:
        GLiNER model instance, or None if unavailable.
    """
    global _gliner_model
    if _gliner_model is None:
        if not is_gliner_available():
            return None
        try:
            from gliner import GLiNER  # type: ignore

            # Multilingual small model with Russian support.
            _gliner_model = GLiNER.from_pretrained("urchade/gliner_multi")
            logger.info("GLiNER model loaded: urchade/gliner_multi")
        except Exception as exc:
            logger.warning("GLiNER model load failed: %s. Domain NER disabled.", exc)
            _gliner_available = False
            return None
    return _gliner_model


def extract_domain_entities(
    text: str,
    labels: Optional[List[str]] = None,
    threshold: float = 0.5,
) -> List[Dict]:
    """Extract domain entities from text using GLiNER.

    Args:
        text: Input text.
        labels: Entity labels to detect (default: DEFAULT_DOMAIN_LABELS).
        threshold: Confidence threshold (0..1).

    Returns:
        List of entity dicts:
        ``[{"text": "тариф Безлимит", "label": "тариф", "start": 12, "end": 26, "score": 0.92}, ...]``

        Falls back to ``[]`` if GLiNER is unavailable or the call fails.
    """
    if not text or not text.strip():
        return []

    model = _get_gliner_model()
    if model is None:
        return []

    labels = labels if labels is not None else DEFAULT_DOMAIN_LABELS
    try:
        entities = model.predict_entities(text, labels, threshold=threshold)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("GLiNER predict_entities failed: %s", exc)
        return []

    result: List[Dict] = []
    for e in entities:
        result.append(
            {
                "text": e.get("text", ""),
                "label": e.get("label", ""),
                "start": int(e.get("start", -1)),
                "end": int(e.get("end", -1)),
                "score": float(e.get("score", 0.0)),
                # Mark the source so downstream chunkers can merge with Natasha.
                "source": "gliner",
            }
        )
    return result


def reset_gliner_cache() -> None:
    """Reset GLiNER availability + model caches (for tests / hot-reload).

    Not intended for production use.
    """
    global _gliner_model, _gliner_available
    _gliner_model = None
    _gliner_available = None
    _get_gliner_model.cache_clear()

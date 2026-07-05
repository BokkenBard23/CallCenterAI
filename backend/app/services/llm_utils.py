"""Generic LLM output parsing utilities.

Extracted from Callytics pattern + our LLMResultHandler. Reusable across
all LLM analysis tasks for robust JSON extraction and schema-driven
validation with fallback.

This module replaces ad-hoc ``json.loads`` + regex snippets scattered across
:mod:`app.services.llm`. The legacy helpers (``_extract_json_object``,
``_safe_parse_model``) are intentionally preserved in ``llm.py`` to avoid
breaking existing imports — new code should use the helpers here.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex finds balanced {...} with one level of nesting in arbitrary text.
# Note: this handles one level of nested {} — sufficient for typical LLM
# JSON payloads where nested objects are flat dicts. Deeper nesting is
# recovered by the json.loads attempts on each candidate match.
_JSON_OBJECT_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[(?:[^\[\]]|(?:\[[^\[\]]*\]))*\]", re.DOTALL)


def extract_json(text: str, prefer: str = "object") -> Optional[Any]:
    """Extract the last valid JSON object or array from arbitrary LLM output.

    Handles:
      - markdown fences ```` ```json ... ``` ````
      - surrounding prose / chatty preambles
      - multiple JSON fragments (returns the LAST valid one — Callytics
        pattern, where LLMs occasionally emit a thought block followed
        by the final answer)

    Args:
        text: Raw LLM response text.
        prefer: ``"object"`` (default) or ``"array"`` — which shape to look
            for first. When the first shape yields no match, the other is
            tried as a fallback.

    Returns:
        Parsed JSON (dict or list) or ``None`` if no valid JSON found.
    """
    if not text:
        return None

    # Strip markdown fences around the whole response.
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    if prefer == "array":
        patterns = (_JSON_ARRAY_RE, _JSON_OBJECT_RE)
    else:
        patterns = (_JSON_OBJECT_RE, _JSON_ARRAY_RE)

    for pattern in patterns:
        matches = pattern.findall(cleaned)
        # Last valid wins — mirrors the Callytics behaviour where the final
        # JSON block is the authoritative answer.
        for match in reversed(matches):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    # Last resort: try parsing the whole cleaned text.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def extract_json_array(text: str) -> list:
    """Extract a JSON array from LLM output. Returns ``[]`` if not found."""
    result = extract_json(text, prefer="array")
    if isinstance(result, list):
        return result
    return []


def safe_parse_model(
    text: str,
    model_class: Type[T],
    default: Optional[T] = None,
) -> T:
    """Parse LLM output into a Pydantic model with fallback.

    Tries: ``extract_json`` → ``model_class.model_validate``.
    On failure: returns ``default`` if provided, otherwise attempts to
    instantiate ``model_class()`` with defaults. If the model has required
    fields and no ``default`` was provided, raises ``ValueError``.

    Args:
        text: Raw LLM response text.
        model_class: Pydantic model class to validate against.
        default: Optional fallback instance.

    Returns:
        Validated model instance, or ``default`` / default-constructed
        instance on failure.
    """
    data = extract_json(text)
    if data is None:
        logger.warning(
            "LLM output contained no parseable JSON for %s. Input preview: %.200s",
            model_class.__name__,
            text,
        )
        return default if default is not None else _instantiate_default(model_class)
    try:
        return model_class.model_validate(data)
    except ValidationError as e:
        logger.warning(
            "LLM output failed %s validation: %s. Input preview: %.200s",
            model_class.__name__,
            e,
            text,
        )
        return default if default is not None else _instantiate_default(model_class)


def _instantiate_default(model_class: Type[T]) -> T:
    """Try to instantiate ``model_class`` with defaults.

    Raises:
        ValueError: If the model has required fields and no default was
            provided to :func:`safe_parse_model`.
    """
    try:
        return model_class()
    except ValidationError as e:
        raise ValueError(
            f"Cannot default-instantiate {model_class.__name__} "
            f"(has required fields); pass default= explicitly"
        ) from e

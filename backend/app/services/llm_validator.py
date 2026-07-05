"""Generic LLM result validator with fallback.

Generalises the Callytics :class:`LLMResultHandler` pattern into a
schema-driven validator usable for ANY Pydantic model. Provides:

* :meth:`validate` — extract JSON → enum-normalise → ``model_validate``,
  with fallback to a default instance on failure.
* :meth:`validate_list` — list output with length-mismatch tolerance
  (pad / truncate to ``expected_length``).
* :meth:`validate_with_fallback` — explicit fallback strategy
  (``default`` / ``raise`` / ``log_and_default``).

The validator is stateless per call; enum mappings and the default
instance are configured at construction time so a single validator
can be reused across many LLM responses for the same model class.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.services.llm_utils import extract_json, safe_parse_model

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMResultValidator:
    """Generic validator for LLM outputs with configurable fallback.

    Example::

        validator = LLMResultValidator(
            model_class=SentimentAnalysisResult,
            default=SentimentAnalysisResult(
                utterances=[], overall_sentiment="neutral",
                sentiment_trajectory="stable",
            ),
            enum_mappings={
                "overall_sentiment": {
                    "позитивный": "positive",
                    "нейтральный": "neutral",
                    "негативный": "negative",
                    "смешанный": "mixed",
                },
            },
        )
        result = validator.validate(raw_llm_output)
    """

    def __init__(
        self,
        model_class: Type[T],
        default: Optional[T] = None,
        enum_mappings: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        """Initialize validator.

        Args:
            model_class: Target Pydantic model class.
            default: Default instance returned on validation failure.
                Required when the model has required fields and the
                ``default`` / ``log_and_default`` fallback strategy is
                used (otherwise :class:`ValueError` is raised at fallback
                time).
            enum_mappings: Optional enum normalisation map. Outer key is
                the target field name on the model; inner map translates
                raw LLM values (e.g. Russian) to canonical enum values.
                Applied to top-level string fields only.
        """
        self.model_class: Type[T] = model_class
        self.default: Optional[T] = default
        self.enum_mappings: Dict[str, Dict[str, str]] = enum_mappings or {}

    # ── Public API ────────────────────────────────────────────

    def validate(self, llm_output: str) -> T:
        """Parse and validate LLM output. Returns ``default`` on failure.

        Pipeline:
            1. ``extract_json`` (markdown-stripping, brace-matching).
            2. Apply enum mappings to top-level string fields.
            3. ``model_validate``.
            4. On any failure: log a warning and return ``self.default``
               (or raise :class:`ValueError` if no default was configured).
        """
        data = extract_json(llm_output)
        if data is None:
            logger.warning(
                "LLMResultValidator(%s): no JSON extracted — using default",
                self.model_class.__name__,
            )
            return self._fallback(llm_output, reason="json_extract_failed")

        if not isinstance(data, dict):
            logger.warning(
                "LLMResultValidator(%s): JSON is %s, expected dict — using default",
                self.model_class.__name__, type(data).__name__,
            )
            return self._fallback(llm_output, reason="non_object_json")

        normalised = self._apply_enum_mappings(data)
        try:
            return self.model_class.model_validate(normalised)
        except ValidationError as exc:
            logger.warning(
                "LLMResultValidator(%s): validation failed: %s — using default",
                self.model_class.__name__, exc,
            )
            return self._fallback(llm_output, reason="validation_failed")

    def validate_list(
        self,
        llm_output: str,
        expected_length: int,
        default_item_factory: Optional[Callable[[], T]] = None,
    ) -> List[T]:
        """Parse a JSON array output with length-mismatch tolerance.

        * If the LLM returns fewer items than ``expected_length``, the
          list is padded with items from ``default_item_factory`` (or
          ``self.default`` if no factory is given).
        * If more items are returned, the list is truncated.
        * If the output is not a JSON array, returns a list of
          ``expected_length`` default items.
        * Invalid items are skipped and replaced with defaults so the
          returned list always has exactly ``expected_length`` entries
          (when ``expected_length >= 0``).
        """
        if expected_length < 0:
            raise ValueError(
                f"expected_length must be >= 0, got {expected_length}"
            )

        data = extract_json(llm_output, prefer="array")
        if not isinstance(data, list):
            logger.warning(
                "LLMResultValidator(%s).validate_list: output is not a JSON "
                "array — returning %d default items",
                self.model_class.__name__, expected_length,
            )
            return self._pad_to_length([], expected_length, default_item_factory)

        validated: List[T] = []
        for item in data[:expected_length]:
            if not isinstance(item, dict):
                validated.append(self._make_default_item(default_item_factory))
                continue
            normalised = self._apply_enum_mappings(item)
            try:
                validated.append(self.model_class.model_validate(normalised))
            except ValidationError as exc:
                logger.debug(
                    "LLMResultValidator(%s).validate_list: skipping invalid "
                    "item %r: %s",
                    self.model_class.__name__, item, exc,
                )
                validated.append(self._make_default_item(default_item_factory))

        return self._pad_to_length(validated, expected_length, default_item_factory)

    def validate_with_fallback(
        self,
        llm_output: str,
        fallback_strategy: str = "default",
    ) -> T:
        """Validate with an explicit fallback strategy.

        Args:
            llm_output: Raw LLM response text.
            fallback_strategy: One of:

                * ``"default"`` — return ``self.default`` (or raise
                  :class:`ValueError` if not configured). No extra logging.
                * ``"raise"`` — re-raise the underlying
                  :class:`ValidationError` / :class:`ValueError`.
                * ``"log_and_default"`` — log full error context (for
                  hardened profile) and return ``self.default``.

        Returns:
            Validated model instance or default.

        Raises:
            ValidationError: when ``fallback_strategy="raise"`` and the
                model fails to validate.
            ValueError: when an unknown strategy is given or when no
                default is configured and a fallback is required.
        """
        if fallback_strategy not in {"default", "raise", "log_and_default"}:
            raise ValueError(
                f"Unknown fallback_strategy: {fallback_strategy!r}. "
                f"Expected one of: default, raise, log_and_default."
            )

        data = extract_json(llm_output)
        if data is None:
            return self._dispatch_fallback(
                llm_output, fallback_strategy,
                reason="json_extract_failed",
                exc=None,
            )
        if not isinstance(data, dict):
            return self._dispatch_fallback(
                llm_output, fallback_strategy,
                reason="non_object_json",
                exc=None,
            )

        normalised = self._apply_enum_mappings(data)
        try:
            return self.model_class.model_validate(normalised)
        except ValidationError as exc:
            return self._dispatch_fallback(
                llm_output, fallback_strategy,
                reason="validation_failed",
                exc=exc,
            )

    # ── Internal helpers ──────────────────────────────────────

    def _apply_enum_mappings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply enum mappings to top-level string fields of ``data``.

        Returns a shallow copy so the input dict is not mutated.
        Non-string values and unknown keys are left untouched.
        """
        if not self.enum_mappings:
            return dict(data)
        out = dict(data)
        for field, mapping in self.enum_mappings.items():
            if field not in out:
                continue
            value = out[field]
            if not isinstance(value, str):
                continue
            normalised = mapping.get(value.strip().lower())
            if normalised is not None:
                out[field] = normalised
            else:
                # Also try case-insensitive match against mapping keys
                for k, v in mapping.items():
                    if value.strip().lower() == k.lower():
                        out[field] = v
                        break
        return out

    def _fallback(self, raw_output: str, reason: str) -> T:
        """Return the configured default or raise if none is set."""
        if self.default is not None:
            return self.default
        raise ValueError(
            f"LLMResultValidator({self.model_class.__name__}): validation "
            f"failed ({reason}) and no default was configured. "
            f"Raw output preview: {raw_output[:200]!r}"
        )

    def _dispatch_fallback(
        self,
        raw_output: str,
        strategy: str,
        reason: str,
        exc: Optional[Exception],
    ) -> T:
        if strategy == "raise":
            if exc is not None:
                raise exc
            raise ValueError(
                f"LLMResultValidator({self.model_class.__name__}): "
                f"validation failed ({reason}) and strategy='raise'. "
                f"Raw output preview: {raw_output[:200]!r}"
            )
        if strategy == "log_and_default":
            logger.error(
                "LLMResultValidator(%s): validation failed (%s). "
                "Raw output preview: %.400s. Exception: %s",
                self.model_class.__name__, reason, raw_output, exc,
            )
            return self._fallback(raw_output, reason)
        # strategy == "default"
        logger.debug(
            "LLMResultValidator(%s): using default (%s).",
            self.model_class.__name__, reason,
        )
        return self._fallback(raw_output, reason)

    def _make_default_item(
        self, default_item_factory: Optional[Callable[[], T]],
    ) -> T:
        if default_item_factory is not None:
            return default_item_factory()
        if self.default is not None:
            # Pydantic models are mutable — return a deep copy so callers
            # can mutate list items independently.
            return self.default.model_copy(deep=True)
        raise ValueError(
            f"LLMResultValidator({self.model_class.__name__}): cannot build "
            f"default list item — neither default_item_factory nor default "
            f"was configured."
        )

    def _pad_to_length(
        self,
        items: List[T],
        expected_length: int,
        default_item_factory: Optional[Callable[[], T]],
    ) -> List[T]:
        if len(items) == expected_length:
            return items
        if len(items) > expected_length:
            return items[:expected_length]
        padded = list(items)
        while len(padded) < expected_length:
            padded.append(self._make_default_item(default_item_factory))
        return padded


__all__ = ["LLMResultValidator", "safe_parse_model"]

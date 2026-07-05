"""Tests for the generic LLMResultValidator.

Covers:
  - validate() happy path (valid JSON → model instance)
  - validate() with markdown-fenced JSON
  - validate() with extra prose around JSON
  - validate() enum mapping (RU → EN normalisation)
  - validate() non-dict JSON (array) → default
  - validate() non-JSON output → default
  - validate() missing default raises ValueError
  - validate_list() happy path
  - validate_list() length mismatch (pad + truncate)
  - validate_list() non-array output → list of defaults
  - validate_list() invalid items replaced with defaults
  - validate_with_fallback() default strategy
  - validate_with_fallback() raise strategy
  - validate_with_fallback() log_and_default strategy
  - validate_with_fallback() unknown strategy raises ValueError
"""

from __future__ import annotations

import json
import logging
from typing import List

import pytest
from pydantic import BaseModel, Field

from app.services.llm_validator import LLMResultValidator


# ═══════════════════════════════════════════════════════════
# Test models
# ═══════════════════════════════════════════════════════════


class _Item(BaseModel):
    """Simple model with one required + one optional field."""

    name: str = ""
    sentiment: str = "neutral"


class _FullItem(BaseModel):
    """Model with a required field (no default)."""

    value: int


class _SentimentResult(BaseModel):
    """Model that mirrors a real analysis result with an enum-like field."""

    overall_sentiment: str = "neutral"
    trajectory: str = "stable"
    confidence: float = 0.5


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def sentiment_validator() -> LLMResultValidator[_SentimentResult]:
    """Validator with RU→EN enum mapping for overall_sentiment."""
    return LLMResultValidator(
        model_class=_SentimentResult,
        default=_SentimentResult(),
        enum_mappings={
            "overall_sentiment": {
                "позитивный": "positive",
                "нейтральный": "neutral",
                "негативный": "negative",
                "смешанный": "mixed",
            },
        },
    )


@pytest.fixture
def item_validator() -> LLMResultValidator[_Item]:
    """Plain validator for _Item with a default instance."""
    return LLMResultValidator(
        model_class=_Item,
        default=_Item(name="default", sentiment="neutral"),
    )


# ═══════════════════════════════════════════════════════════
# 1. validate() — happy path
# ═══════════════════════════════════════════════════════════


class TestValidateHappyPath:
    def test_valid_json_returns_model(self, sentiment_validator: LLMResultValidator) -> None:
        raw = json.dumps({
            "overall_sentiment": "positive",
            "trajectory": "improving",
            "confidence": 0.9,
        })
        result = sentiment_validator.validate(raw)
        assert isinstance(result, _SentimentResult)
        assert result.overall_sentiment == "positive"
        assert result.trajectory == "improving"
        assert result.confidence == 0.9

    def test_markdown_fenced_json(self, item_validator: LLMResultValidator) -> None:
        raw = '```json\n{"name": "Alice", "sentiment": "positive"}\n```'
        result = item_validator.validate(raw)
        assert result.name == "Alice"
        assert result.sentiment == "positive"

    def test_extra_prose_around_json(self, item_validator: LLMResultValidator) -> None:
        raw = (
            "Вот результат:\n"
            '{"name": "Bob", "sentiment": "negative"}\n'
            "Надеюсь, это поможет."
        )
        result = item_validator.validate(raw)
        assert result.name == "Bob"
        assert result.sentiment == "negative"

    def test_missing_optional_uses_model_defaults(
        self, sentiment_validator: LLMResultValidator,
    ) -> None:
        raw = json.dumps({"overall_sentiment": "negative"})
        result = sentiment_validator.validate(raw)
        assert result.overall_sentiment == "negative"
        # trajectory + confidence fall back to model defaults
        assert result.trajectory == "stable"
        assert result.confidence == 0.5


# ═══════════════════════════════════════════════════════════
# 2. validate() — enum mapping
# ═══════════════════════════════════════════════════════════


class TestEnumMapping:
    def test_ru_to_en_normalisation(self, sentiment_validator: LLMResultValidator) -> None:
        raw = json.dumps({"overall_sentiment": "позитивный"})
        result = sentiment_validator.validate(raw)
        assert result.overall_sentiment == "positive"

    def test_case_insensitive_mapping(self, sentiment_validator: LLMResultValidator) -> None:
        raw = json.dumps({"overall_sentiment": "НЕГАТИВНЫЙ"})
        result = sentiment_validator.validate(raw)
        assert result.overall_sentiment == "negative"

    def test_unknown_value_left_untouched(
        self, sentiment_validator: LLMResultValidator,
    ) -> None:
        """Values not in the mapping are passed through (model may reject)."""
        raw = json.dumps({"overall_sentiment": "weird"})
        # The model accepts any string for overall_sentiment (str field),
        # so the value passes through unchanged.
        result = sentiment_validator.validate(raw)
        assert result.overall_sentiment == "weird"

    def test_no_enum_mappings_passes_through(self, item_validator: LLMResultValidator) -> None:
        raw = json.dumps({"name": "X", "sentiment": "curious"})
        result = item_validator.validate(raw)
        assert result.sentiment == "curious"

    def test_enum_mapping_skips_non_string_values(
        self, sentiment_validator: LLMResultValidator,
    ) -> None:
        """If the LLM returns a non-string for a mapped field, it's left
        alone (and likely fails validation → default)."""
        raw = json.dumps({"overall_sentiment": 42})
        result = sentiment_validator.validate(raw)
        # 42 is not a string → mapping skipped → pydantic may coerce or reject.
        # _SentimentResult.overall_sentiment is `str`, pydantic coerces 42 → "42".
        assert isinstance(result, _SentimentResult)


# ═══════════════════════════════════════════════════════════
# 3. validate() — fallback on failure
# ═══════════════════════════════════════════════════════════


class TestValidateFallback:
    def test_non_json_returns_default(self, item_validator: LLMResultValidator) -> None:
        result = item_validator.validate("this is not json at all")
        assert result.name == "default"

    def test_empty_string_returns_default(self, item_validator: LLMResultValidator) -> None:
        result = item_validator.validate("")
        assert result.name == "default"

    def test_json_array_returns_default(self, item_validator: LLMResultValidator) -> None:
        """A JSON array with no inner object → default.

        Note: ``extract_json`` is greedy — if the array contains an
        object (e.g. ``[{"name": "X"}]``), it extracts that object and
        validation succeeds. To force the default path we use a bare
        array of scalars with no nested object.
        """
        result = item_validator.validate('["just", "strings"]')
        assert result.name == "default"

    def test_validation_failure_returns_default(
        self, item_validator: LLMResultValidator,
    ) -> None:
        # _Item accepts everything (all fields have defaults), so we need
        # a validator whose model actually rejects something. Use _FullItem
        # which requires `value: int`.
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=_FullItem(value=-1),
        )
        raw = json.dumps({"value": "not-an-int-or-coercible"})
        # pydantic 2 will reject "not-an-int-or-coercible" as int
        result = validator.validate(raw)
        assert result.value == -1  # default

    def test_no_default_raises_value_error(self) -> None:
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=None,
        )
        with pytest.raises(ValueError, match="no default was configured"):
            validator.validate("not json")


# ═══════════════════════════════════════════════════════════
# 4. validate_list()
# ═══════════════════════════════════════════════════════════


class TestValidateList:
    def test_happy_path(self, item_validator: LLMResultValidator) -> None:
        raw = json.dumps([
            {"name": "A", "sentiment": "positive"},
            {"name": "B", "sentiment": "negative"},
            {"name": "C", "sentiment": "neutral"},
        ])
        result = item_validator.validate_list(raw, expected_length=3)
        assert len(result) == 3
        assert result[0].name == "A"
        assert result[1].name == "B"
        assert result[2].name == "C"

    def test_pad_when_fewer_items(self, item_validator: LLMResultValidator) -> None:
        raw = json.dumps([{"name": "A"}])
        result = item_validator.validate_list(raw, expected_length=3)
        assert len(result) == 3
        assert result[0].name == "A"
        assert result[1].name == "default"  # padded
        assert result[2].name == "default"

    def test_truncate_when_more_items(self, item_validator: LLMResultValidator) -> None:
        raw = json.dumps([
            {"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"},
        ])
        result = item_validator.validate_list(raw, expected_length=2)
        assert len(result) == 2
        assert result[0].name == "A"
        assert result[1].name == "B"

    def test_zero_expected_length(self, item_validator: LLMResultValidator) -> None:
        raw = json.dumps([{"name": "A"}])
        result = item_validator.validate_list(raw, expected_length=0)
        assert result == []

    def test_non_array_returns_defaults(self, item_validator: LLMResultValidator) -> None:
        result = item_validator.validate_list("not json", expected_length=2)
        assert len(result) == 2
        assert all(item.name == "default" for item in result)

    def test_object_instead_of_array_returns_defaults(
        self, item_validator: LLMResultValidator,
    ) -> None:
        raw = json.dumps({"name": "X"})
        result = item_validator.validate_list(raw, expected_length=2)
        assert len(result) == 2
        assert all(item.name == "default" for item in result)

    def test_invalid_items_replaced_with_defaults(
        self, item_validator: LLMResultValidator,
    ) -> None:
        """Items that fail validation are skipped, but the list is padded
        with defaults so the result still has expected_length entries."""
        # Use _FullItem for actual validation failures.
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=_FullItem(value=-1),
        )
        raw = json.dumps([
            {"value": 1},
            {"value": "bad"},  # invalid → default
            {"value": 3},
        ])
        result = validator.validate_list(raw, expected_length=3)
        assert len(result) == 3
        assert result[0].value == 1
        assert result[1].value == -1  # default
        assert result[2].value == 3

    def test_default_item_factory_used_when_no_default(self) -> None:
        """When no default is set, default_item_factory builds pad items."""
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=None,
        )
        raw = json.dumps([{"value": 1}])

        def factory() -> _FullItem:
            return _FullItem(value=99)

        result = validator.validate_list(raw, expected_length=3, default_item_factory=factory)
        assert len(result) == 3
        assert result[0].value == 1
        assert result[1].value == 99  # factory
        assert result[2].value == 99

    def test_negative_length_raises(self, item_validator: LLMResultValidator) -> None:
        with pytest.raises(ValueError, match="expected_length"):
            item_validator.validate_list("[]", expected_length=-1)

    def test_no_default_no_factory_raises_on_pad(self) -> None:
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=None,
        )
        raw = json.dumps([{"value": 1}])
        with pytest.raises(ValueError, match="neither default_item_factory nor default"):
            validator.validate_list(raw, expected_length=3)

    def test_pad_items_are_deep_copies(self, item_validator: LLMResultValidator) -> None:
        """Padded items must be independent (mutable models)."""
        raw = json.dumps([])
        result = item_validator.validate_list(raw, expected_length=3)
        # Mutate one — others must be unaffected.
        result[0].name = "changed"
        assert result[1].name == "default"
        assert result[2].name == "default"


# ═══════════════════════════════════════════════════════════
# 5. validate_with_fallback() — strategies
# ═══════════════════════════════════════════════════════════


class TestValidateWithFallbackStrategies:
    def test_default_strategy_returns_default_on_failure(
        self, item_validator: LLMResultValidator,
    ) -> None:
        result = item_validator.validate_with_fallback(
            "not json", fallback_strategy="default",
        )
        assert result.name == "default"

    def test_default_strategy_returns_validated_on_success(
        self, item_validator: LLMResultValidator,
    ) -> None:
        raw = json.dumps({"name": "X"})
        result = item_validator.validate_with_fallback(
            raw, fallback_strategy="default",
        )
        assert result.name == "X"

    def test_raise_strategy_raises_on_validation_failure(self) -> None:
        from pydantic import ValidationError
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=_FullItem(value=-1),
        )
        raw = json.dumps({"value": "not-an-int"})
        with pytest.raises(ValidationError):
            validator.validate_with_fallback(raw, fallback_strategy="raise")

    def test_raise_strategy_raises_on_json_failure(self) -> None:
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=_FullItem(value=-1),
        )
        with pytest.raises(ValueError, match="json_extract_failed"):
            validator.validate_with_fallback("not json", fallback_strategy="raise")

    def test_log_and_default_returns_default(
        self, item_validator: LLMResultValidator, caplog,
    ) -> None:
        with caplog.at_level(logging.ERROR):
            result = item_validator.validate_with_fallback(
                "not json", fallback_strategy="log_and_default",
            )
        assert result.name == "default"
        # An ERROR log was emitted
        assert any(
            "validation failed" in rec.message.lower() or
            "json_extract_failed" in rec.message.lower()
            for rec in caplog.records
        )

    def test_unknown_strategy_raises(self, item_validator: LLMResultValidator) -> None:
        with pytest.raises(ValueError, match="Unknown fallback_strategy"):
            item_validator.validate_with_fallback("x", fallback_strategy="bogus")

    def test_log_and_default_on_validation_failure(
        self, item_validator: LLMResultValidator, caplog,
    ) -> None:
        """log_and_default logs ValidationError details."""
        # _Item accepts everything → use _FullItem
        validator: LLMResultValidator[_FullItem] = LLMResultValidator(
            model_class=_FullItem,
            default=_FullItem(value=-1),
        )
        raw = json.dumps({"value": "bad"})
        with caplog.at_level(logging.ERROR):
            result = validator.validate_with_fallback(
                raw, fallback_strategy="log_and_default",
            )
        assert result.value == -1
        assert any("validation_failed" in rec.message for rec in caplog.records)


# ═══════════════════════════════════════════════════════════
# 6. Real-model integration (SentimentAnalysisResult)
# ═══════════════════════════════════════════════════════════


class TestRealModelIntegration:
    def test_sentiment_analysis_result_validation(self) -> None:
        from app.models import SentimentAnalysisResult
        default = SentimentAnalysisResult(
            utterances=[], overall_sentiment="neutral",
        )
        validator: LLMResultValidator[SentimentAnalysisResult] = LLMResultValidator(
            model_class=SentimentAnalysisResult,
            default=default,
        )
        raw = json.dumps({
            "utterances": [
                {"turn_index": 0, "speaker": "Клиент", "sentiment": "negative", "confidence": 0.9},
            ],
            "overall_sentiment": "negative",
            "sentiment_trajectory": "stable",
        })
        result = validator.validate(raw)
        assert isinstance(result, SentimentAnalysisResult)
        assert result.overall_sentiment == "negative"
        assert len(result.utterances) == 1

    def test_real_model_fallback_on_garbage(self) -> None:
        from app.models import ConflictAnalysisResult
        default = ConflictAnalysisResult(has_conflict=False)
        validator: LLMResultValidator[ConflictAnalysisResult] = LLMResultValidator(
            model_class=ConflictAnalysisResult,
            default=default,
        )
        result = validator.validate("garbage not json")
        assert result.has_conflict is False
        assert result is default

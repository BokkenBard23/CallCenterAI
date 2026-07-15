"""Comprehensive tests for LLMResultHandler (IP-3.1).

Covers:
  - Valid JSON with all fields
  - Markdown-wrapped JSON
  - Invalid JSON / non-JSON responses
  - Missing fields (default substitution)
  - Wrong enum values (fallback with warning)
  - Russian enum values (normalisation)
  - Mixed valid/invalid fields
  - Empty response
  - Non-JSON response (plain text)
  - key_points type validation
  - String field type validation
  - Backward compatibility: _parse_llm_response still exists
  - analyze_dialogue contract unchanged
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from app.models import (
    ClientSentiment,
    LLMResult,
    Resolution,
    _CLIENT_SENTIMENT_RU_MAP,
    _RESOLUTION_RU_MAP,
)
from app.services.llm import (
    LLMResultHandler,
    ValidatedLLMResult,
    _parse_llm_response,
    analyze_dialogue,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def handler() -> LLMResultHandler:
    """Fresh LLMResultHandler instance."""
    return LLMResultHandler()


def _valid_response(**overrides: Any) -> str:
    """Build a valid JSON response string with optional overrides."""
    data = {
        "summary": "Краткое резюме",
        "restructured_dialogue": "Клиент: Здравствуйте\nСотрудник: Добрый день",
        "topic": "Подключение услуги",
        "result": "решено",
        "key_points": ["точка 1", "точка 2"],
        "client_sentiment": "positive",
        "resolution": "resolved",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 1. Valid JSON with all fields
# ═══════════════════════════════════════════════════════════

class TestValidJsonAllFields:
    """Happy path: all fields present and valid."""

    def test_all_fields_parsed(self, handler: LLMResultHandler) -> None:
        raw = _valid_response()
        result = handler.validate_and_parse(raw)
        assert result.summary == "Краткое резюме"
        assert result.restructured_dialogue.startswith("Клиент:")
        assert result.topic == "Подключение услуги"
        assert result.result == "решено"
        assert result.key_points == ["точка 1", "точка 2"]
        assert result.client_sentiment == "positive"
        assert result.resolution == "resolved"
        assert result.invalid_fields == []

    def test_all_english_sentiment_values(self, handler: LLMResultHandler) -> None:
        for member in ClientSentiment:
            raw = _valid_response(client_sentiment=member.value)
            result = handler.validate_and_parse(raw)
            assert result.client_sentiment == member.value
            assert result.invalid_fields == []

    def test_all_english_resolution_values(self, handler: LLMResultHandler) -> None:
        for member in Resolution:
            raw = _valid_response(resolution=member.value)
            result = handler.validate_and_parse(raw)
            assert result.resolution == member.value
            assert result.invalid_fields == []


# ═══════════════════════════════════════════════════════════
# 2. Markdown-wrapped JSON
# ═══════════════════════════════════════════════════════════

class TestMarkdownWrappedJson:
    """JSON inside ```json ... ``` markdown blocks."""

    def test_json_code_block(self, handler: LLMResultHandler) -> None:
        raw = '```json\n' + _valid_response() + '\n```'
        result = handler.validate_and_parse(raw)
        assert result.topic == "Подключение услуги"
        assert result.client_sentiment == "positive"

    def test_plain_code_block(self, handler: LLMResultHandler) -> None:
        raw = '```\n' + _valid_response() + '\n```'
        result = handler.validate_and_parse(raw)
        assert result.topic == "Подключение услуги"

    def test_code_block_with_extra_text(self, handler: LLMResultHandler) -> None:
        raw = 'Here is the result:\n```json\n' + _valid_response() + '\n```\nDone.'
        result = handler.validate_and_parse(raw)
        assert result.topic == "Подключение услуги"


# ═══════════════════════════════════════════════════════════
# 3. Invalid JSON / non-JSON responses
# ═══════════════════════════════════════════════════════════

class TestInvalidJson:
    """Malformed or non-JSON responses."""

    def test_non_json_text(self, handler: LLMResultHandler) -> None:
        raw = "This is just plain text, not JSON."
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "neutral"
        assert result.summary == ""
        assert len(result.invalid_fields) == 1
        assert result.invalid_fields[0]["field"] == "raw_response"

    def test_broken_json(self, handler: LLMResultHandler) -> None:
        raw = '{"topic": "test", "client_sentiment": "positive"'
        result = handler.validate_and_parse(raw)
        # Should fallback to defaults since JSON is broken
        assert result.client_sentiment == "neutral"

    def test_json_array_instead_of_object(self, handler: LLMResultHandler) -> None:
        raw = '["not", "an", "object"]'
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "neutral"

    def test_empty_string(self, handler: LLMResultHandler) -> None:
        result = handler.validate_and_parse("")
        assert result.summary == ""
        assert result.client_sentiment == "neutral"
        assert result.resolution == "unresolved"
        assert len(result.invalid_fields) == 1

    def test_whitespace_only(self, handler: LLMResultHandler) -> None:
        result = handler.validate_and_parse("   \n\t  ")
        assert result.client_sentiment == "neutral"


# ═══════════════════════════════════════════════════════════
# 4. Missing fields
# ═══════════════════════════════════════════════════════════

class TestMissingFields:
    """Fields absent from the JSON response get safe defaults."""

    def test_missing_client_sentiment(self, handler: LLMResultHandler) -> None:
        raw = json.dumps({"topic": "test", "resolution": "resolved"})
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "neutral"
        assert any(f["field"] == "client_sentiment" for f in result.invalid_fields)

    def test_missing_resolution(self, handler: LLMResultHandler) -> None:
        raw = json.dumps({"topic": "test", "client_sentiment": "positive"})
        result = handler.validate_and_parse(raw)
        assert result.resolution == "unresolved"
        assert any(f["field"] == "resolution" for f in result.invalid_fields)

    def test_missing_all_enum_fields(self, handler: LLMResultHandler) -> None:
        raw = json.dumps({"topic": "test"})
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "neutral"
        assert result.resolution == "unresolved"

    def test_missing_summary(self, handler: LLMResultHandler) -> None:
        raw = json.dumps({"topic": "test"})
        result = handler.validate_and_parse(raw)
        assert result.summary == ""

    def test_missing_key_points(self, handler: LLMResultHandler) -> None:
        raw = json.dumps({"topic": "test"})
        result = handler.validate_and_parse(raw)
        assert result.key_points == []

    def test_completely_empty_json(self, handler: LLMResultHandler) -> None:
        raw = "{}"
        result = handler.validate_and_parse(raw)
        assert result.summary == ""
        assert result.topic == ""
        assert result.key_points == []
        assert result.client_sentiment == "neutral"
        assert result.resolution == "unresolved"


# ═══════════════════════════════════════════════════════════
# 5. Wrong enum values
# ═══════════════════════════════════════════════════════════

class TestWrongEnumValues:
    """Invalid enum values trigger fallback + warning log."""

    def test_invalid_sentiment(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(client_sentiment="angry")
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "neutral"
        assert any(
            f["field"] == "client_sentiment" and f["reason"] == "invalid_value"
            for f in result.invalid_fields
        )

    def test_invalid_resolution(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(resolution="cancelled")
        result = handler.validate_and_parse(raw)
        assert result.resolution == "unresolved"
        assert any(
            f["field"] == "resolution" and f["reason"] == "invalid_value"
            for f in result.invalid_fields
        )

    def test_non_string_enum_value(self, handler: LLMResultHandler) -> None:
        raw = _valid_response()
        # Manually construct with non-string enum
        data = json.loads(raw)
        data["client_sentiment"] = 42
        result = handler.validate_and_parse(json.dumps(data))
        assert result.client_sentiment == "neutral"
        assert any(
            f["field"] == "client_sentiment" and f["reason"] == "wrong_type"
            for f in result.invalid_fields
        )

    def test_case_insensitive_enum(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(client_sentiment="Positive", resolution="RESOLVED")
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "positive"
        assert result.resolution == "resolved"


# ═══════════════════════════════════════════════════════════
# 6. Russian enum values
# ═══════════════════════════════════════════════════════════

class TestRussianEnumValues:
    """Russian-language enum values are normalised to English canonical."""

    @pytest.mark.parametrize(
        "ru_value,expected",
        list(_CLIENT_SENTIMENT_RU_MAP.items()),
    )
    def test_russian_sentiment(
        self, handler: LLMResultHandler, ru_value: str, expected: str
    ) -> None:
        raw = _valid_response(client_sentiment=ru_value)
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == expected
        assert result.invalid_fields == []

    @pytest.mark.parametrize(
        "ru_value,expected",
        list(_RESOLUTION_RU_MAP.items()),
    )
    def test_russian_resolution(
        self, handler: LLMResultHandler, ru_value: str, expected: str
    ) -> None:
        raw = _valid_response(resolution=ru_value)
        result = handler.validate_and_parse(raw)
        assert result.resolution == expected
        assert result.invalid_fields == []

    def test_russian_case_insensitive(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(client_sentiment="Позитивный")
        result = handler.validate_and_parse(raw)
        assert result.client_sentiment == "positive"


# ═══════════════════════════════════════════════════════════
# 7. Mixed valid/invalid fields
# ═══════════════════════════════════════════════════════════

class TestMixedValidInvalid:
    """Some fields valid, others invalid — valid ones preserved."""

    def test_valid_topic_invalid_sentiment(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(client_sentiment="furious")
        result = handler.validate_and_parse(raw)
        assert result.topic == "Подключение услуги"
        assert result.client_sentiment == "neutral"

    def test_valid_resolution_missing_sentiment(self, handler: LLMResultHandler) -> None:
        data = {
            "topic": "test",
            "resolution": "escalated",
            "summary": "ok",
        }
        result = handler.validate_and_parse(json.dumps(data))
        assert result.resolution == "escalated"
        assert result.client_sentiment == "neutral"


# ═══════════════════════════════════════════════════════════
# 8. key_points type validation
# ═══════════════════════════════════════════════════════════

class TestKeyPointsValidation:
    """key_points field type checking."""

    def test_key_points_valid_list(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(key_points=["a", "b", "c"])
        result = handler.validate_and_parse(raw)
        assert result.key_points == ["a", "b", "c"]

    def test_key_points_non_list(self, handler: LLMResultHandler) -> None:
        data = json.loads(_valid_response())
        data["key_points"] = "not a list"
        result = handler.validate_and_parse(json.dumps(data))
        assert result.key_points == []
        assert any(
            f["field"] == "key_points" and f["reason"] == "wrong_type"
            for f in result.invalid_fields
        )

    def test_key_points_with_non_string_items(self, handler: LLMResultHandler) -> None:
        data = json.loads(_valid_response())
        data["key_points"] = ["valid", 42, True]
        result = handler.validate_and_parse(json.dumps(data))
        assert result.key_points == ["valid", "42", "True"]

    def test_key_points_missing(self, handler: LLMResultHandler) -> None:
        data = json.loads(_valid_response())
        del data["key_points"]
        result = handler.validate_and_parse(json.dumps(data))
        assert result.key_points == []


# ═══════════════════════════════════════════════════════════
# 9. String field type validation
# ═══════════════════════════════════════════════════════════

class TestStringFieldValidation:
    """Non-string values for string fields get replaced with empty string."""

    def test_summary_non_string(self, handler: LLMResultHandler) -> None:
        data = json.loads(_valid_response())
        data["summary"] = 12345
        result = handler.validate_and_parse(json.dumps(data))
        assert result.summary == ""
        assert any(f["field"] == "summary" for f in result.invalid_fields)

    def test_topic_non_string(self, handler: LLMResultHandler) -> None:
        data = json.loads(_valid_response())
        data["topic"] = None
        result = handler.validate_and_parse(json.dumps(data))
        assert result.topic == ""

    def test_restructured_dialogue_non_string(self, handler: LLMResultHandler) -> None:
        data = json.loads(_valid_response())
        data["restructured_dialogue"] = []
        result = handler.validate_and_parse(json.dumps(data))
        assert result.restructured_dialogue == ""


# ═══════════════════════════════════════════════════════════
# 10. ValidatedLLMResult structure
# ═══════════════════════════════════════════════════════════

class TestValidatedLLMResult:
    """ValidatedLLMResult attributes and structure."""

    def test_all_attributes_present(self, handler: LLMResultHandler) -> None:
        result = handler.validate_and_parse(_valid_response())
        assert hasattr(result, "summary")
        assert hasattr(result, "restructured_dialogue")
        assert hasattr(result, "topic")
        assert hasattr(result, "result")
        assert hasattr(result, "key_points")
        assert hasattr(result, "client_sentiment")
        assert hasattr(result, "resolution")
        assert hasattr(result, "invalid_fields")

    def test_invalid_fields_is_list(self, handler: LLMResultHandler) -> None:
        result = handler.validate_and_parse(_valid_response())
        assert isinstance(result.invalid_fields, list)

    def test_invalid_field_structure(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(client_sentiment="bad_value")
        result = handler.validate_and_parse(raw)
        assert len(result.invalid_fields) == 1
        field_info = result.invalid_fields[0]
        assert "field" in field_info
        assert "received" in field_info
        assert "fallback" in field_info
        assert "reason" in field_info
        assert field_info["field"] == "client_sentiment"
        assert field_info["received"] == "bad_value"
        assert field_info["fallback"] == "neutral"
        assert field_info["reason"] == "invalid_value"


# ═══════════════════════════════════════════════════════════
# 11. Enum model tests
# ═══════════════════════════════════════════════════════════

class TestEnumModels:
    """ClientSentiment and Resolution enum correctness."""

    def test_client_sentiment_values(self) -> None:
        assert ClientSentiment.positive.value == "positive"
        assert ClientSentiment.neutral.value == "neutral"
        assert ClientSentiment.negative.value == "negative"
        assert ClientSentiment.mixed.value == "mixed"

    def test_resolution_values(self) -> None:
        assert Resolution.resolved.value == "resolved"
        assert Resolution.unresolved.value == "unresolved"
        assert Resolution.escalated.value == "escalated"
        assert Resolution.partial.value == "partial"

    def test_russian_sentiment_map_completeness(self) -> None:
        assert len(_CLIENT_SENTIMENT_RU_MAP) == len(ClientSentiment)
        for v in _CLIENT_SENTIMENT_RU_MAP.values():
            assert v in [e.value for e in ClientSentiment]

    def test_russian_resolution_map_completeness(self) -> None:
        assert len(_RESOLUTION_RU_MAP) == len(Resolution)
        for v in _RESOLUTION_RU_MAP.values():
            assert v in [e.value for e in Resolution]


# ═══════════════════════════════════════════════════════════
# 12. Backward compatibility
# ═══════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """_parse_llm_response still exists and LLMResult fields unchanged."""

    def test_parse_llm_response_still_callable(self) -> None:
        raw = json.dumps({"topic": "test"})
        result = _parse_llm_response(raw)
        assert result["topic"] == "test"

    def test_parse_llm_response_markdown(self) -> None:
        raw = '```json\n{"topic": "test"}\n```'
        result = _parse_llm_response(raw)
        assert result["topic"] == "test"

    def test_llm_result_fields_unchanged(self) -> None:
        """LLMResult model fields remain str, not enum types."""
        llm = LLMResult(
            summary="test",
            restructured_dialogue="",
            topic="t",
            result="r",
            key_points=["a"],
            client_sentiment="positive",
            resolution="resolved",
            provider="ollama",
            model="llama3.2",
        )
        assert isinstance(llm.client_sentiment, str)
        assert isinstance(llm.resolution, str)
        assert llm.client_sentiment == "positive"
        assert llm.resolution == "resolved"

    def test_llm_result_defaults(self) -> None:
        """LLMResult model has safe defaults."""
        llm = LLMResult()
        assert llm.summary == ""
        assert llm.client_sentiment == ""
        assert llm.resolution == ""
        assert llm.key_points == []
        assert llm.provider == "none"


# ═══════════════════════════════════════════════════════════
# 13. analyze_dialogue contract
# ═══════════════════════════════════════════════════════════

class TestAnalyzeDialogueContract:
    """analyze_dialogue returns LLMResult with validated fields."""

    @pytest.mark.asyncio
    async def test_analyze_dialogue_returns_llm_result(self) -> None:
        mock_response = _valid_response()
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            result = await analyze_dialogue("dialogue text", provider_id="ollama")
            assert isinstance(result, LLMResult)
            assert result.client_sentiment == "positive"
            assert result.resolution == "resolved"
            assert result.topic == "Подключение услуги"

    @pytest.mark.asyncio
    async def test_analyze_dialogue_invalid_enum_fallback(self) -> None:
        mock_response = _valid_response(client_sentiment="unknown_value")
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            result = await analyze_dialogue("dialogue text", provider_id="ollama")
            assert isinstance(result, LLMResult)
            assert result.client_sentiment == "neutral"  # fallback default

    @pytest.mark.asyncio
    async def test_analyze_dialogue_russian_enum(self) -> None:
        mock_response = _valid_response(
            client_sentiment="позитивный",
            resolution="решено",
        )
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            result = await analyze_dialogue("dialogue text", provider_id="ollama")
            assert result.client_sentiment == "positive"
            assert result.resolution == "resolved"

    @pytest.mark.asyncio
    async def test_analyze_dialogue_unknown_provider(self) -> None:
        """Unknown provider is skipped in fallback chain; tries other providers.

        With graceful degradation, unknown providers are not errors — they're
        skipped and the fallback chain tries remaining providers. If a
        configured provider is available, it succeeds; otherwise returns
        degraded result with provider='none'.
        """
        result = await analyze_dialogue("text", provider_id="nonexistent")
        assert isinstance(result, LLMResult)
        # Result may be from a working provider (e.g. qwen36, beeline, ollama)
        # or degraded (provider='none') if no providers are configured.
        assert result.provider in (
            "qwen36", "qwen36_fast", "coding", "beeline",
            "ollama", "yandexgpt", "gigachat", "none",
        )

    @pytest.mark.asyncio
    async def test_analyze_dialogue_broken_json(self) -> None:
        """Broken JSON from LLM → safe defaults in LLMResult."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value="not json at all")
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            result = await analyze_dialogue("dialogue text", provider_id="ollama")
            assert isinstance(result, LLMResult)
            assert result.client_sentiment == "neutral"
            assert result.resolution == "unresolved"
            assert result.summary == ""


# ═══════════════════════════════════════════════════════════
# 14. Warning log verification
# ═══════════════════════════════════════════════════════════

class TestWarningLogs:
    """Invalid responses produce WARNING-level log entries."""

    def test_invalid_enum_logs_warning(
        self, handler: LLMResultHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            raw = _valid_response(client_sentiment="angry")
            handler.validate_and_parse(raw)
        assert any(
            "invalid value" in rec.message and "client_sentiment" in rec.message
            for rec in caplog.records
        )

    def test_missing_field_logs_warning(
        self, handler: LLMResultHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            raw = json.dumps({"topic": "test"})
            handler.validate_and_parse(raw)
        assert any(
            "missing field" in rec.message and "client_sentiment" in rec.message
            for rec in caplog.records
        )

    def test_non_string_enum_logs_warning(
        self, handler: LLMResultHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            data = json.loads(_valid_response())
            data["resolution"] = 999
            handler.validate_and_parse(json.dumps(data))
        assert any(
            "non-string" in rec.message and "resolution" in rec.message
            for rec in caplog.records
        )

    def test_broken_json_logs_warning(
        self, handler: LLMResultHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            handler.validate_and_parse("not json at all")
        assert any(
            "failed to extract JSON" in rec.message
            for rec in caplog.records
        )


# ═══════════════════════════════════════════════════════════
# 15. Edge cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Various edge-case scenarios."""

    def test_json_with_extra_whitespace(self, handler: LLMResultHandler) -> None:
        raw = "  \n  " + _valid_response() + "  \n  "
        result = handler.validate_and_parse(raw)
        assert result.topic == "Подключение услуги"

    def test_unicode_in_fields(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(topic="テスト", summary="Ünïcödé")
        result = handler.validate_and_parse(raw)
        assert result.topic == "テスト"
        assert result.summary == "Ünïcödé"

    def test_very_long_summary(self, handler: LLMResultHandler) -> None:
        long_summary = "x" * 10000
        raw = _valid_response(summary=long_summary)
        result = handler.validate_and_parse(raw)
        assert len(result.summary) == 10000

    def test_empty_key_points_list(self, handler: LLMResultHandler) -> None:
        raw = _valid_response(key_points=[])
        result = handler.validate_and_parse(raw)
        assert result.key_points == []

    def test_nested_json_in_response(self, handler: LLMResultHandler) -> None:
        """Inner JSON objects should still parse (only top-level is used)."""
        data = {
            "topic": "test",
            "client_sentiment": "negative",
            "resolution": "unresolved",
            "key_points": ["a"],
            "nested": {"inner": "value"},
        }
        result = handler.validate_and_parse(json.dumps(data))
        assert result.client_sentiment == "negative"

    def test_none_raw_response(self, handler: LLMResultHandler) -> None:
        result = handler.validate_and_parse(None)  # type: ignore[arg-type]
        assert result.client_sentiment == "neutral"

    def test_handler_reusable(self, handler: LLMResultHandler) -> None:
        """Same handler instance can be used for multiple calls."""
        r1 = handler.validate_and_parse(_valid_response())
        r2 = handler.validate_and_parse(json.dumps({"topic": "other"}))
        assert r1.client_sentiment == "positive"
        assert r2.client_sentiment == "neutral"

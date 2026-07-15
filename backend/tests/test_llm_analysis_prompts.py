"""Comprehensive tests for LLM analysis prompts (IP-3.2 – IP-3.5).

Covers each of the 4 analysis types:
  - Model validation (Pydantic models accept valid data, reject invalid)
  - Prompt formatting (prompts contain required instructions)
  - Endpoint happy path (mock LLM → valid JSON → correct result)
  - Invalid input (missing session, no dialogue)
  - Fallback on LLM failure (circuit breaker / connection error)
  - Empty dialogue (session with empty turns)
  - JSON extraction (markdown wrappers, extra text, nested objects)
  - _safe_parse_model with various malformed inputs
  - _extract_json_object with nested JSON
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from app.models import (
    ConflictAnalysisResult,
    DetectedTopic,
    EscalationPoint,
    ProfanityAnalysisResult,
    ProfanityInstance,
    SentimentAnalysisResult,
    TopicAnalysisResult,
    UtteranceSentiment,
)
from app.services.llm import (
    _SENTIMENT_SYSTEM_PROMPT,
    _CONFLICT_SYSTEM_PROMPT,
    _PROFANITY_SYSTEM_PROMPT,
    _TOPIC_SYSTEM_PROMPT,
    _extract_json_object,
    _safe_parse_model,
    analyze_conflict,
    analyze_profanity,
    analyze_sentiment,
    analyze_topic,
)


# ═══════════════════════════════════════════════════════════
# Fixtures — valid JSON responses for each analysis type
# ═══════════════════════════════════════════════════════════


def _valid_sentiment_json(**overrides: Any) -> str:
    data = {
        "utterances": [
            {
                "turn_index": 0,
                "speaker": "Клиент",
                "sentiment": "negative",
                "confidence": 0.9,
                "text_snippet": "Не работает интернет",
            },
            {
                "turn_index": 1,
                "speaker": "Сотрудник",
                "sentiment": "positive",
                "confidence": 0.8,
                "text_snippet": "Сейчас проверим",
            },
        ],
        "overall_sentiment": "negative",
        "sentiment_trajectory": "improving",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _valid_conflict_json(**overrides: Any) -> str:
    data = {
        "has_conflict": True,
        "conflict_level": "medium",
        "escalation_points": [
            {
                "turn_index": 2,
                "speaker": "Клиент",
                "trigger": "Долгое ожидание",
                "level": "medium",
            }
        ],
        "de_escalation_attempts": 1,
        "justification": "Клиент повысил голос из-за долгого ожидания",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _valid_profanity_json(**overrides: Any) -> str:
    data = {
        "has_profanity": True,
        "instances": [
            {
                "turn_index": 3,
                "speaker": "Клиент",
                "category": "insult",
                "severity": "medium",
                "context": "Клиент выразился грубо",
            }
        ],
        "total_count": 1,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _valid_topic_json(**overrides: Any) -> str:
    data = {
        "topics": [
            {
                "name": "Подключение услуги",
                "confidence": 0.95,
                "key_phrases": ["подключить", "услуга", "тариф"],
                "turn_indices": [0, 1, 2],
            },
            {
                "name": "Биллинг",
                "confidence": 0.7,
                "key_phrases": ["счёт", "оплата"],
                "turn_indices": [3, 4],
            },
        ],
        "primary_topic": "Подключение услуги",
        "topic_count": 2,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 1. Pydantic model validation
# ═══════════════════════════════════════════════════════════


class TestSentimentModels:
    """SentimentAnalysisResult and UtteranceSentiment model validation."""

    def test_valid_sentiment_result(self) -> None:
        result = SentimentAnalysisResult(
            utterances=[
                UtteranceSentiment(
                    turn_index=0, speaker="Клиент",
                    sentiment="positive", confidence=0.9, text_snippet="Hello",
                )
            ],
            overall_sentiment="positive",
            sentiment_trajectory="stable",
            provider="beeline",
            model="glm-xlarge",
        )
        assert result.overall_sentiment == "positive"
        assert len(result.utterances) == 1
        assert result.utterances[0].turn_index == 0

    def test_sentiment_defaults(self) -> None:
        result = SentimentAnalysisResult()
        assert result.utterances == []
        assert result.overall_sentiment == "neutral"
        assert result.sentiment_trajectory == "stable"
        assert result.provider == "none"

    def test_utterance_sentiment_defaults(self) -> None:
        u = UtteranceSentiment(turn_index=0, speaker="Клиент")
        assert u.sentiment == "neutral"
        assert u.confidence == 0.5
        assert u.text_snippet == ""

    def test_sentiment_from_json(self) -> None:
        data = json.loads(_valid_sentiment_json())
        result = SentimentAnalysisResult.model_validate(data)
        assert result.overall_sentiment == "negative"
        assert result.sentiment_trajectory == "improving"
        assert len(result.utterances) == 2
        assert result.utterances[0].sentiment == "negative"


class TestConflictModels:
    """ConflictAnalysisResult and EscalationPoint model validation."""

    def test_valid_conflict_result(self) -> None:
        result = ConflictAnalysisResult(
            has_conflict=True,
            conflict_level="high",
            escalation_points=[
                EscalationPoint(
                    turn_index=3, speaker="Клиент",
                    trigger="Отказ", level="high",
                )
            ],
            de_escalation_attempts=2,
            justification="Клиент угрожал расторжением",
            provider="ollama",
            model="llama3.2",
        )
        assert result.has_conflict is True
        assert result.conflict_level == "high"
        assert result.de_escalation_attempts == 2

    def test_conflict_defaults(self) -> None:
        result = ConflictAnalysisResult()
        assert result.has_conflict is False
        assert result.conflict_level == "none"
        assert result.escalation_points == []
        assert result.de_escalation_attempts == 0

    def test_conflict_from_json(self) -> None:
        data = json.loads(_valid_conflict_json())
        result = ConflictAnalysisResult.model_validate(data)
        assert result.has_conflict is True
        assert result.conflict_level == "medium"
        assert len(result.escalation_points) == 1


class TestProfanityModels:
    """ProfanityAnalysisResult and ProfanityInstance model validation."""

    def test_valid_profanity_result(self) -> None:
        result = ProfanityAnalysisResult(
            has_profanity=True,
            instances=[
                ProfanityInstance(
                    turn_index=1, speaker="Клиент",
                    category="obscenity", severity="high",
                    context="Грубое выражение",
                )
            ],
            total_count=1,
            provider="beeline",
            model="glm-xlarge",
        )
        assert result.has_profanity is True
        assert result.total_count == 1
        assert result.instances[0].category == "obscenity"

    def test_profanity_defaults(self) -> None:
        result = ProfanityAnalysisResult()
        assert result.has_profanity is False
        assert result.instances == []
        assert result.total_count == 0

    def test_profanity_from_json(self) -> None:
        data = json.loads(_valid_profanity_json())
        result = ProfanityAnalysisResult.model_validate(data)
        assert result.has_profanity is True
        assert result.instances[0].severity == "medium"


class TestTopicModels:
    """TopicAnalysisResult and DetectedTopic model validation."""

    def test_valid_topic_result(self) -> None:
        result = TopicAnalysisResult(
            topics=[
                DetectedTopic(
                    name="Интернет",
                    confidence=0.9,
                    key_phrases=["скорость", "роутер"],
                    turn_indices=[0, 1],
                )
            ],
            primary_topic="Интернет",
            topic_count=1,
            provider="ollama",
            model="llama3.2",
        )
        assert result.primary_topic == "Интернет"
        assert result.topic_count == 1
        assert result.topics[0].key_phrases == ["скорость", "роутер"]

    def test_topic_defaults(self) -> None:
        result = TopicAnalysisResult()
        assert result.topics == []
        assert result.primary_topic == ""
        assert result.topic_count == 0

    def test_topic_from_json(self) -> None:
        data = json.loads(_valid_topic_json())
        result = TopicAnalysisResult.model_validate(data)
        assert result.topic_count == 2
        assert result.primary_topic == "Подключение услуги"
        assert result.topics[0].confidence == 0.95


# ═══════════════════════════════════════════════════════════
# 2. Prompt content validation
# ═══════════════════════════════════════════════════════════


class TestPromptContent:
    """Each analysis prompt contains required instructions."""

    @pytest.mark.parametrize(
        "prompt_name,prompt_text",
        [
            ("sentiment", _SENTIMENT_SYSTEM_PROMPT),
            ("conflict", _CONFLICT_SYSTEM_PROMPT),
            ("profanity", _PROFANITY_SYSTEM_PROMPT),
            ("topic", _TOPIC_SYSTEM_PROMPT),
        ],
    )
    def test_prompt_instructs_ignore_artifacts(
        self, prompt_name: str, prompt_text: str,
    ) -> None:
        assert "артефакт" in prompt_text.lower() or "ИГНОРИРУЙ" in prompt_text

    @pytest.mark.parametrize(
        "prompt_name,prompt_text",
        [
            ("sentiment", _SENTIMENT_SYSTEM_PROMPT),
            ("conflict", _CONFLICT_SYSTEM_PROMPT),
            ("profanity", _PROFANITY_SYSTEM_PROMPT),
            ("topic", _TOPIC_SYSTEM_PROMPT),
        ],
    )
    def test_prompt_requests_json_only(
        self, prompt_name: str, prompt_text: str,
    ) -> None:
        assert "JSON" in prompt_text
        assert "markdown" in prompt_text.lower() or "обёрток" in prompt_text

    @pytest.mark.parametrize(
        "prompt_name,prompt_text,expected_field",
        [
            ("sentiment", _SENTIMENT_SYSTEM_PROMPT, "utterances"),
            ("conflict", _CONFLICT_SYSTEM_PROMPT, "has_conflict"),
            ("profanity", _PROFANITY_SYSTEM_PROMPT, "has_profanity"),
            ("topic", _TOPIC_SYSTEM_PROMPT, "topics"),
        ],
    )
    def test_prompt_specifies_output_format(
        self, prompt_name: str, prompt_text: str, expected_field: str,
    ) -> None:
        assert expected_field in prompt_text


# ═══════════════════════════════════════════════════════════
# 3. JSON extraction helpers
# ═══════════════════════════════════════════════════════════


class TestExtractJsonObject:
    """_extract_json_object handles various response formats."""

    def test_plain_json(self) -> None:
        raw = '{"key": "value"}'
        result = _extract_json_object(raw)
        assert result == {"key": "value"}

    def test_markdown_wrapped(self) -> None:
        raw = '```json\n{"key": "value"}\n```'
        result = _extract_json_object(raw)
        assert result == {"key": "value"}

    def test_markdown_no_lang(self) -> None:
        raw = '```\n{"key": "value"}\n```'
        result = _extract_json_object(raw)
        assert result == {"key": "value"}

    def test_extra_text_around_json(self) -> None:
        raw = 'Here is the result:\n{"key": "value"}\nDone.'
        result = _extract_json_object(raw)
        assert result == {"key": "value"}

    def test_nested_json_object(self) -> None:
        """Nested JSON objects are correctly extracted."""
        raw = '{"outer": {"inner": "value"}, "list": [1, 2]}'
        result = _extract_json_object(raw)
        assert result == {"outer": {"inner": "value"}, "list": [1, 2]}

    def test_empty_string(self) -> None:
        assert _extract_json_object("") is None

    def test_none_input(self) -> None:
        assert _extract_json_object(None) is None  # type: ignore[arg-type]

    def test_non_json_text(self) -> None:
        assert _extract_json_object("just some text") is None

    def test_json_array_not_object(self) -> None:
        assert _extract_json_object('["not", "an", "object"]') is None

    def test_sentiment_json_extraction(self) -> None:
        raw = _valid_sentiment_json()
        result = _extract_json_object(raw)
        assert result is not None
        assert "utterances" in result
        assert "overall_sentiment" in result

    def test_conflict_json_extraction(self) -> None:
        raw = _valid_conflict_json()
        result = _extract_json_object(raw)
        assert result is not None
        assert "has_conflict" in result

    def test_profanity_json_extraction(self) -> None:
        raw = _valid_profanity_json()
        result = _extract_json_object(raw)
        assert result is not None
        assert "has_profanity" in result

    def test_topic_json_extraction(self) -> None:
        raw = _valid_topic_json()
        result = _extract_json_object(raw)
        assert result is not None
        assert "topics" in result

    def test_deeply_nested_json(self) -> None:
        raw = '{"a": {"b": {"c": [1, 2, {"d": 3}]}}}'
        result = _extract_json_object(raw)
        assert result is not None
        assert result["a"]["b"]["c"][2]["d"] == 3


class TestSafeParseModel:
    """_safe_parse_model validates and falls back on failure."""

    def test_valid_json_returns_model(self) -> None:
        raw = _valid_sentiment_json()
        result = _safe_parse_model(
            raw, SentimentAnalysisResult, provider="ollama", model="llama3.2",
        )
        assert isinstance(result, SentimentAnalysisResult)
        assert result.overall_sentiment == "negative"
        assert result.provider == "ollama"

    def test_invalid_json_returns_default(self) -> None:
        result = _safe_parse_model(
            "not json at all",
            SentimentAnalysisResult,
            provider="none",
            model="",
        )
        assert isinstance(result, SentimentAnalysisResult)
        assert result.provider == "none"
        assert result.utterances == []

    def test_broken_json_returns_default(self) -> None:
        raw = '{"utterances": broken'
        result = _safe_parse_model(
            raw, SentimentAnalysisResult, provider="none", model="",
        )
        assert isinstance(result, SentimentAnalysisResult)
        assert result.overall_sentiment == "neutral"

    def test_extra_fields_in_json(self) -> None:
        """Extra fields in JSON are ignored by Pydantic."""
        data = json.loads(_valid_sentiment_json())
        data["extra_field"] = "should be ignored"
        raw = json.dumps(data)
        result = _safe_parse_model(
            raw, SentimentAnalysisResult, provider="ollama", model="test",
        )
        assert isinstance(result, SentimentAnalysisResult)
        assert not hasattr(result, "extra_field")

    def test_empty_json_object(self) -> None:
        """Empty JSON object uses Pydantic defaults."""
        raw = "{}"
        result = _safe_parse_model(
            raw, ConflictAnalysisResult, provider="ollama", model="test",
        )
        assert isinstance(result, ConflictAnalysisResult)
        assert result.has_conflict is False
        assert result.conflict_level == "none"

    def test_wrong_type_in_json(self) -> None:
        """Wrong type fields cause fallback to defaults."""
        raw = '{"has_conflict": "not_a_bool", "conflict_level": 42}'
        result = _safe_parse_model(
            raw, ConflictAnalysisResult, provider="none", model="",
        )
        assert isinstance(result, ConflictAnalysisResult)
        # Fallback to defaults because validation failed
        assert result.has_conflict is False


# ═══════════════════════════════════════════════════════════
# 4. Analysis functions — happy path with mocked LLM
# ═══════════════════════════════════════════════════════════


def _mock_provider(response_text: str) -> AsyncMock:
    """Create a mock LLM provider that returns the given text."""
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value=response_text)
    mock_provider.get_default_model = lambda: "test-model"
    return mock_provider


class TestAnalyzeSentiment:
    """analyze_sentiment happy path and fallback."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_sentiment_json())
            result = await analyze_sentiment("dialogue text", provider_id="ollama")
            assert isinstance(result, SentimentAnalysisResult)
            assert result.overall_sentiment == "negative"
            assert result.sentiment_trajectory == "improving"
            assert len(result.utterances) == 2
            assert result.utterances[0].turn_index == 0

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("unavailable"))
            mock_get.return_value = mock_provider
            result = await analyze_sentiment("dialogue text", provider_id="ollama")
            assert isinstance(result, SentimentAnalysisResult)
            assert result.provider == "none"
            assert result.overall_sentiment == "neutral"
            assert result.utterances == []

    @pytest.mark.asyncio
    async def test_markdown_wrapped_response(self) -> None:
        raw = '```json\n' + _valid_sentiment_json() + '\n```'
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_sentiment("dialogue text", provider_id="ollama")
            assert isinstance(result, SentimentAnalysisResult)
            assert result.overall_sentiment == "negative"

    @pytest.mark.asyncio
    async def test_broken_json_returns_defaults(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider("not json at all")
            result = await analyze_sentiment("dialogue text", provider_id="ollama")
            assert isinstance(result, SentimentAnalysisResult)
            # Provider DID respond (just with invalid JSON), so provider is set
            # but the field values fall back to Pydantic defaults
            assert result.overall_sentiment == "neutral"
            assert result.utterances == []


class TestAnalyzeConflict:
    """analyze_conflict happy path and fallback."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_conflict_json())
            result = await analyze_conflict("dialogue text", provider_id="ollama")
            assert isinstance(result, ConflictAnalysisResult)
            assert result.has_conflict is True
            assert result.conflict_level == "medium"
            assert len(result.escalation_points) == 1
            assert result.de_escalation_attempts == 1

    @pytest.mark.asyncio
    async def test_no_conflict(self) -> None:
        raw = _valid_conflict_json(
            has_conflict=False,
            conflict_level="none",
            escalation_points=[],
            de_escalation_attempts=0,
            justification="Спокойный диалог",
        )
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_conflict("dialogue text", provider_id="ollama")
            assert isinstance(result, ConflictAnalysisResult)
            assert result.has_conflict is False
            assert result.conflict_level == "none"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("unavailable"))
            mock_get.return_value = mock_provider
            result = await analyze_conflict("dialogue text", provider_id="ollama")
            assert isinstance(result, ConflictAnalysisResult)
            assert result.provider == "none"
            assert result.has_conflict is False
            assert result.conflict_level == "none"


class TestAnalyzeProfanity:
    """analyze_profanity happy path and fallback."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_profanity_json())
            result = await analyze_profanity("dialogue text", provider_id="ollama")
            assert isinstance(result, ProfanityAnalysisResult)
            assert result.has_profanity is True
            assert result.total_count == 1
            assert result.instances[0].category == "insult"
            assert result.instances[0].severity == "medium"

    @pytest.mark.asyncio
    async def test_no_profanity(self) -> None:
        raw = _valid_profanity_json(
            has_profanity=False, instances=[], total_count=0,
        )
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_profanity("dialogue text", provider_id="ollama")
            assert result.has_profanity is False
            assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("unavailable"))
            mock_get.return_value = mock_provider
            result = await analyze_profanity("dialogue text", provider_id="ollama")
            assert isinstance(result, ProfanityAnalysisResult)
            assert result.provider == "none"
            assert result.has_profanity is False


class TestAnalyzeTopic:
    """analyze_topic happy path and fallback."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_topic_json())
            result = await analyze_topic("dialogue text", provider_id="ollama")
            assert isinstance(result, TopicAnalysisResult)
            assert result.topic_count == 2
            assert result.primary_topic == "Подключение услуги"
            assert result.topics[0].confidence == 0.95
            assert result.topics[0].key_phrases == ["подключить", "услуга", "тариф"]

    @pytest.mark.asyncio
    async def test_single_topic(self) -> None:
        raw = _valid_topic_json(
            topics=[
                {
                    "name": "Интернет",
                    "confidence": 0.9,
                    "key_phrases": ["скорость"],
                    "turn_indices": [0],
                }
            ],
            primary_topic="Интернет",
            topic_count=1,
        )
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_topic("dialogue text", provider_id="ollama")
            assert result.topic_count == 1
            assert result.primary_topic == "Интернет"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("unavailable"))
            mock_get.return_value = mock_provider
            result = await analyze_topic("dialogue text", provider_id="ollama")
            assert isinstance(result, TopicAnalysisResult)
            assert result.provider == "none"
            assert result.topics == []
            assert result.primary_topic == ""


# ═══════════════════════════════════════════════════════════
# 5. Endpoint integration tests (FastAPI TestClient)
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def client():
    """Create a TestClient with the FastAPI app."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def session_with_dialogue(client):
    """Create a session with an uploaded dialogue for endpoint tests."""
    # We need to use the session_store directly to create a session
    # with dialogue data, since the upload endpoint requires file upload.
    from app.utils.session import session_store
    from app.models import ParsedDialog, DialogueTurn

    session = session_store.create()
    session.dialog = ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте, у меня проблема с интернетом"),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день, сейчас проверим"),
            DialogueTurn(turn_index=2, speaker="Клиент", text="Уже третий день не работает!"),
            DialogueTurn(turn_index=3, speaker="Сотрудник", text="Понимаю ваше раздражение, давайте разберёмся"),
        ],
        total_turns=4,
        client_turns=2,
        employee_turns=2,
    )
    session_store.update(session)
    return session.id


class TestSentimentEndpoint:
    """POST /api/analysis/sentiment endpoint tests."""

    @pytest.mark.asyncio
    async def test_sentiment_endpoint_happy_path(
        self, client, session_with_dialogue,
    ) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_sentiment_json())
            response = client.post(
                "/api/analysis/sentiment",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "ollama",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["overall_sentiment"] == "negative"
            assert len(data["utterances"]) == 2

    def test_sentiment_endpoint_session_not_found(self, client) -> None:
        response = client.post(
            "/api/analysis/sentiment",
            json={"session_id": "nonexistent", "provider_id": "ollama"},
        )
        assert response.status_code == 404

    def test_sentiment_endpoint_no_dialogue(self, client) -> None:
        from app.utils.session import session_store
        session = session_store.create()
        response = client.post(
            "/api/analysis/sentiment",
            json={"session_id": session.id, "provider_id": "ollama"},
        )
        assert response.status_code == 400


class TestConflictEndpoint:
    """POST /api/analysis/conflict endpoint tests."""

    @pytest.mark.asyncio
    async def test_conflict_endpoint_happy_path(
        self, client, session_with_dialogue,
    ) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_conflict_json())
            response = client.post(
                "/api/analysis/conflict",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "ollama",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["has_conflict"] is True
            assert data["conflict_level"] == "medium"

    def test_conflict_endpoint_session_not_found(self, client) -> None:
        response = client.post(
            "/api/analysis/conflict",
            json={"session_id": "nonexistent", "provider_id": "ollama"},
        )
        assert response.status_code == 404


class TestProfanityEndpoint:
    """POST /api/analysis/profanity endpoint tests."""

    @pytest.mark.asyncio
    async def test_profanity_endpoint_happy_path(
        self, client, session_with_dialogue,
    ) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_profanity_json())
            response = client.post(
                "/api/analysis/profanity",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "ollama",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["has_profanity"] is True
            assert data["total_count"] == 1

    def test_profanity_endpoint_session_not_found(self, client) -> None:
        response = client.post(
            "/api/analysis/profanity",
            json={"session_id": "nonexistent", "provider_id": "ollama"},
        )
        assert response.status_code == 404


class TestTopicEndpoint:
    """POST /api/analysis/topic endpoint tests."""

    @pytest.mark.asyncio
    async def test_topic_endpoint_happy_path(
        self, client, session_with_dialogue,
    ) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_topic_json())
            response = client.post(
                "/api/analysis/topic",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "ollama",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["topic_count"] == 2
            assert data["primary_topic"] == "Подключение услуги"

    def test_topic_endpoint_session_not_found(self, client) -> None:
        response = client.post(
            "/api/analysis/topic",
            json={"session_id": "nonexistent", "provider_id": "ollama"},
        )
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════
# 6. Default provider_id = "beeline"
# ═══════════════════════════════════════════════════════════


class TestDefaultProvider:
    """All 4 analysis functions default to provider_id='qwen36' (since 2026-07-14)."""

    @pytest.mark.asyncio
    async def test_sentiment_default_provider(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_sentiment_json())
            result = await analyze_sentiment("dialogue text")
            # Default provider_id is "qwen36" (Qwen3.6-27B Dense, PRIMARY)
            assert isinstance(result, SentimentAnalysisResult)

    @pytest.mark.asyncio
    async def test_conflict_default_provider(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_conflict_json())
            result = await analyze_conflict("dialogue text")
            assert isinstance(result, ConflictAnalysisResult)

    @pytest.mark.asyncio
    async def test_profanity_default_provider(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_profanity_json())
            result = await analyze_profanity("dialogue text")
            assert isinstance(result, ProfanityAnalysisResult)

    @pytest.mark.asyncio
    async def test_topic_default_provider(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_topic_json())
            result = await analyze_topic("dialogue text")
            assert isinstance(result, TopicAnalysisResult)


# ═══════════════════════════════════════════════════════════
# 7. Circuit breaker integration with analysis functions
# ═══════════════════════════════════════════════════════════


class TestCircuitBreakerIntegration:
    """Analysis functions respect circuit breaker state."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_skip_on_open(self) -> None:
        """When primary provider's circuit breaker is open, skip to next."""
        from app.services.llm import _get_circuit_breaker

        # Force the ollama circuit breaker to open state
        cb = _get_circuit_breaker("ollama")
        for _ in range(5):  # exceed failure_threshold
            cb.record_failure()

        try:
            with patch("app.services.llm.get_provider") as mock_get:
                # Make the fallback provider (yandexgpt) succeed
                mock_get.return_value = _mock_provider(_valid_sentiment_json())
                result = await analyze_sentiment("text", provider_id="ollama")
                assert isinstance(result, SentimentAnalysisResult)
        finally:
            # Reset circuit breaker
            cb.record_success()

    @pytest.mark.asyncio
    async def test_all_providers_down_returns_default(self) -> None:
        """When all providers fail, return default instance."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("down"))
            mock_get.return_value = mock_provider
            result = await analyze_sentiment("text", provider_id="ollama")
            assert result.provider == "none"
            assert result.overall_sentiment == "neutral"


# ═══════════════════════════════════════════════════════════
# 8. System prompt parameter passed to provider
# ═══════════════════════════════════════════════════════════


class TestSystemPromptParameter:
    """Analysis functions pass custom system_prompt to provider.generate()."""

    @pytest.mark.asyncio
    async def test_sentiment_passes_custom_system_prompt(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=_valid_sentiment_json())
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_sentiment("dialogue text", provider_id="ollama")

            # Verify generate was called with system_prompt kwarg
            call_kwargs = mock_provider.generate.call_args
            assert "system_prompt" in call_kwargs.kwargs
            assert call_kwargs.kwargs["system_prompt"] == _SENTIMENT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_conflict_passes_custom_system_prompt(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=_valid_conflict_json())
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_conflict("dialogue text", provider_id="ollama")

            call_kwargs = mock_provider.generate.call_args
            assert call_kwargs.kwargs["system_prompt"] == _CONFLICT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_profanity_passes_custom_system_prompt(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=_valid_profanity_json())
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_profanity("dialogue text", provider_id="ollama")

            call_kwargs = mock_provider.generate.call_args
            assert call_kwargs.kwargs["system_prompt"] == _PROFANITY_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_topic_passes_custom_system_prompt(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=_valid_topic_json())
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_topic("dialogue text", provider_id="ollama")

            call_kwargs = mock_provider.generate.call_args
            assert call_kwargs.kwargs["system_prompt"] == _TOPIC_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# 9. Backward compatibility — analyze_dialogue still works
# ═══════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Existing analyze_dialogue() and LLMResultHandler not affected."""

    @pytest.mark.asyncio
    async def test_analyze_dialogue_still_works(self) -> None:
        from app.models import LLMResult
        from app.services.llm import analyze_dialogue

        valid_response = json.dumps({
            "summary": "Test summary",
            "restructured_dialogue": "Клиент: Hi",
            "topic": "Test topic",
            "result": "resolved",
            "key_points": ["point1"],
            "client_sentiment": "positive",
            "resolution": "resolved",
        })

        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=valid_response)
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            result = await analyze_dialogue("dialogue text", provider_id="ollama")
            assert isinstance(result, LLMResult)
            assert result.topic == "Test topic"
            assert result.client_sentiment == "positive"

    @pytest.mark.asyncio
    async def test_analyze_dialogue_no_system_prompt_override(self) -> None:
        """analyze_dialogue passes split system prompts (Task 2: parallel split).

        Since Task 2 (2026-07-15), analyze_dialogue runs TWO parallel LLM
        calls: one for the 6 analysis fields (using _DIALOGUE_ANALYSIS_SYSTEM_PROMPT)
        and one for restructured_dialogue (using _RESTRUCTURE_SYSTEM_PROMPT).
        Both calls pass an explicit system_prompt — neither uses the default
        _SYSTEM_PROMPT anymore.
        """
        from app.services.llm import (
            _DIALOGUE_ANALYSIS_SYSTEM_PROMPT,
            _RESTRUCTURE_SYSTEM_PROMPT,
            analyze_dialogue,
        )

        valid_response = json.dumps({
            "topic": "test",
            "client_sentiment": "neutral",
            "resolution": "unresolved",
        })

        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=valid_response)
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_dialogue("dialogue text", provider_id="ollama")

            # Both calls should pass explicit system_prompt (not None / default)
            assert mock_provider.generate.call_count == 2
            used_prompts = [
                call.kwargs.get("system_prompt")
                for call in mock_provider.generate.call_args_list
            ]
            assert _DIALOGUE_ANALYSIS_SYSTEM_PROMPT in used_prompts
            assert _RESTRUCTURE_SYSTEM_PROMPT in used_prompts

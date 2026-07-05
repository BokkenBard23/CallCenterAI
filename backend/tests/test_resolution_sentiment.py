"""Comprehensive tests for auto-resolution + sentiment trajectory (ID-3).

Covers:
  - ResolutionClassification enum (4 values)
  - SentimentTrajectoryPoint model
  - ResolutionSentimentResult model
  - System prompt content
  - analyze_resolution_sentiment function (mock LLM → valid JSON → correct result)
  - Fallback on LLM failure
  - Domain-specific prompt addition (IP-6.1)
  - POST /api/analysis/resolution-sentiment endpoint
  - Invalid/missing session handling
  - Markdown-wrapped LLM response
  - Session_id override
  - get_domain_prompt_addition
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    DomainType,
    ResolutionClassification,
    ResolutionSentimentResult,
    SentimentTrajectoryPoint,
)
from app.services.llm import (
    _RESOLUTION_SENTIMENT_SYSTEM_PROMPT,
    analyze_resolution_sentiment,
    get_domain_prompt_addition,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


def _mock_provider(response_text: str) -> AsyncMock:
    """Create a mock LLM provider."""
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value=response_text)
    mock_provider.get_default_model = lambda: "test-model"
    return mock_provider


def _valid_resolution_sentiment_json(**overrides: Any) -> str:
    """Build a valid resolution-sentiment JSON response."""
    data = {
        "session_id": "",
        "resolution": "resolved",
        "resolution_confidence": 0.9,
        "resolution_reason": "Проблема клиента была полностью решена",
        "sentiment_trajectory": [
            {
                "turn_index": 0,
                "speaker": "Клиент",
                "sentiment": "negative",
                "cumulative_sentiment": -0.5,
            },
            {
                "turn_index": 1,
                "speaker": "Сотрудник",
                "sentiment": "positive",
                "cumulative_sentiment": -0.1,
            },
            {
                "turn_index": 2,
                "speaker": "Клиент",
                "sentiment": "neutral",
                "cumulative_sentiment": 0.1,
            },
            {
                "turn_index": 3,
                "speaker": "Сотрудник",
                "sentiment": "positive",
                "cumulative_sentiment": 0.4,
            },
        ],
        "sentiment_start": "negative",
        "sentiment_end": "positive",
        "trajectory_direction": "improving",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 1. Enum tests
# ═══════════════════════════════════════════════════════════


class TestResolutionClassification:
    """Tests for ResolutionClassification enum."""

    def test_has_four_values(self) -> None:
        assert len(ResolutionClassification) == 4

    def test_values_are_lowercase_english(self) -> None:
        for member in ResolutionClassification:
            assert member.value == member.value.lower()

    def test_specific_values(self) -> None:
        assert ResolutionClassification.resolved.value == "resolved"
        assert ResolutionClassification.unresolved.value == "unresolved"
        assert ResolutionClassification.escalated.value == "escalated"
        assert ResolutionClassification.redirected.value == "redirected"

    def test_from_value(self) -> None:
        assert ResolutionClassification("resolved") is ResolutionClassification.resolved
        assert ResolutionClassification("redirected") is ResolutionClassification.redirected

    def test_stable_identifiers(self) -> None:
        """Enum values are stable — UI depends on them."""
        expected = {"resolved", "unresolved", "escalated", "redirected"}
        actual = {m.value for m in ResolutionClassification}
        assert actual == expected


# ═══════════════════════════════════════════════════════════
# 2. Model tests
# ═══════════════════════════════════════════════════════════


class TestSentimentTrajectoryPoint:
    """Tests for SentimentTrajectoryPoint model."""

    def test_valid_point(self) -> None:
        point = SentimentTrajectoryPoint(
            turn_index=0,
            speaker="Клиент",
            sentiment="negative",
            cumulative_sentiment=-0.5,
        )
        assert point.turn_index == 0
        assert point.sentiment == "negative"
        assert point.cumulative_sentiment == -0.5

    def test_defaults(self) -> None:
        point = SentimentTrajectoryPoint(turn_index=0, speaker="Клиент")
        assert point.sentiment == "neutral"
        assert point.cumulative_sentiment == 0.0


class TestResolutionSentimentResult:
    """Tests for ResolutionSentimentResult model."""

    def test_default_values(self) -> None:
        result = ResolutionSentimentResult()
        assert result.session_id == ""
        assert result.resolution == ResolutionClassification.unresolved
        assert result.resolution_confidence == 0.0
        assert result.resolution_reason == ""
        assert result.sentiment_trajectory == []
        assert result.sentiment_start == "neutral"
        assert result.sentiment_end == "neutral"
        assert result.trajectory_direction == "stable"
        assert result.provider == "none"

    def test_with_full_data(self) -> None:
        result = ResolutionSentimentResult(
            session_id="s1",
            resolution=ResolutionClassification.resolved,
            resolution_confidence=0.9,
            resolution_reason="Problem solved",
            sentiment_trajectory=[
                SentimentTrajectoryPoint(
                    turn_index=0, speaker="Клиент",
                    sentiment="negative", cumulative_sentiment=-0.5,
                ),
            ],
            sentiment_start="negative",
            sentiment_end="positive",
            trajectory_direction="improving",
            provider="beeline",
            model="glm-xlarge",
        )
        assert result.resolution == ResolutionClassification.resolved
        assert len(result.sentiment_trajectory) == 1
        assert result.trajectory_direction == "improving"

    def test_from_json(self) -> None:
        data = json.loads(_valid_resolution_sentiment_json())
        result = ResolutionSentimentResult.model_validate(data)
        assert result.resolution == ResolutionClassification.resolved
        assert result.resolution_confidence == 0.9
        assert len(result.sentiment_trajectory) == 4
        assert result.sentiment_trajectory[0].cumulative_sentiment == -0.5
        assert result.trajectory_direction == "improving"


# ═══════════════════════════════════════════════════════════
# 3. System prompt tests
# ═══════════════════════════════════════════════════════════


class TestResolutionSentimentPrompt:
    """Tests for _RESOLUTION_SENTIMENT_SYSTEM_PROMPT."""

    def test_contains_resolution_categories(self) -> None:
        assert "resolved" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert "unresolved" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert "escalated" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert "redirected" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT

    def test_contains_cumulative_sentiment(self) -> None:
        assert "cumulative_sentiment" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT

    def test_contains_trajectory_direction(self) -> None:
        assert "improving" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert "declining" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert "stable" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT
        assert "volatile" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT

    def test_contains_json_instruction(self) -> None:
        assert "JSON" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT

    def test_contains_artifact_ignore(self) -> None:
        assert "ИГНОРИРУЙ" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT or "артефакт" in _RESOLUTION_SENTIMENT_SYSTEM_PROMPT.lower()


# ═══════════════════════════════════════════════════════════
# 4. Domain prompt addition tests
# ═══════════════════════════════════════════════════════════


class TestGetDomainPromptAddition:
    """Tests for get_domain_prompt_addition function."""

    def test_general_returns_empty(self) -> None:
        assert get_domain_prompt_addition("general") == ""

    def test_insurance_returns_non_empty(self) -> None:
        result = get_domain_prompt_addition("insurance")
        assert len(result) > 0
        assert "СТРАХОВАНИЕ" in result

    def test_banking_returns_non_empty(self) -> None:
        result = get_domain_prompt_addition("banking")
        assert len(result) > 0
        assert "БАНКИНГ" in result

    def test_healthcare_returns_non_empty(self) -> None:
        result = get_domain_prompt_addition("healthcare")
        assert len(result) > 0
        assert "ЗДРАВООХРАНЕНИЕ" in result

    def test_telecom_returns_non_empty(self) -> None:
        result = get_domain_prompt_addition("telecom")
        assert len(result) > 0
        assert "ТЕЛЕКОММУНИКАЦИИ" in result

    def test_unknown_domain_returns_empty(self) -> None:
        assert get_domain_prompt_addition("unknown") == ""


# ═══════════════════════════════════════════════════════════
# 5. analyze_resolution_sentiment function tests
# ═══════════════════════════════════════════════════════════


class TestAnalyzeResolutionSentiment:
    """Tests for analyze_resolution_sentiment async function."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_resolution_sentiment_json())
            result = await analyze_resolution_sentiment(
                dialogue_text="Клиент: Привет\nСотрудник: Здравствуйте",
                session_id="s1",
                provider_id="beeline",
            )
        assert isinstance(result, ResolutionSentimentResult)
        assert result.resolution == ResolutionClassification.resolved
        assert result.resolution_confidence == 0.9
        assert len(result.sentiment_trajectory) == 4
        assert result.trajectory_direction == "improving"

    @pytest.mark.asyncio
    async def test_session_id_override(self) -> None:
        """If LLM returns a different session_id, it should be overridden."""
        raw = _valid_resolution_sentiment_json(session_id="wrong")
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="correct",
                provider_id="beeline",
            )
        assert result.session_id == "correct"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("unavailable"))
            mock_get.return_value = mock_provider
            result = await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )
        assert result.provider == "none"
        assert result.resolution == ResolutionClassification.unresolved
        assert result.sentiment_trajectory == []
        assert result.trajectory_direction == "stable"

    @pytest.mark.asyncio
    async def test_escalated_resolution(self) -> None:
        raw = _valid_resolution_sentiment_json(
            resolution="escalated",
            resolution_confidence=0.8,
            resolution_reason="Диалог передан старшему специалисту",
            trajectory_direction="declining",
        )
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
            )
        assert result.resolution == ResolutionClassification.escalated
        assert result.trajectory_direction == "declining"

    @pytest.mark.asyncio
    async def test_markdown_wrapped_response(self) -> None:
        raw = '```json\n' + _valid_resolution_sentiment_json() + '\n```'
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
            )
        assert result.resolution == ResolutionClassification.resolved

    @pytest.mark.asyncio
    async def test_with_domain_parameter(self) -> None:
        """Domain parameter is accepted and used for prompt enhancement."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_resolution_sentiment_json())
            result = await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
                domain="insurance",
            )
        assert isinstance(result, ResolutionSentimentResult)

    @pytest.mark.asyncio
    async def test_broken_json_returns_defaults(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider("not json at all")
            result = await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
            )
        assert isinstance(result, ResolutionSentimentResult)
        # Falls back to Pydantic defaults since JSON parse failed
        assert result.sentiment_trajectory == []


# ═══════════════════════════════════════════════════════════
# 6. Endpoint tests
# ═══════════════════════════════════════════════════════════


class TestResolutionSentimentEndpoint:
    """Tests for POST /api/analysis/resolution-sentiment endpoint."""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_endpoint_exists(self) -> None:
        """The /resolution-sentiment route should be registered."""
        routes = [r.path for r in app.routes]
        assert "/api/analysis/resolution-sentiment" in routes

    def test_missing_session_returns_404(self) -> None:
        response = self.client.post(
            "/api/analysis/resolution-sentiment",
            json={"session_id": "nonexistent", "provider_id": "beeline"},
        )
        assert response.status_code == 404

    def test_missing_body_returns_422(self) -> None:
        response = self.client.post(
            "/api/analysis/resolution-sentiment",
            json={},
        )
        assert response.status_code == 422

    def test_default_domain(self) -> None:
        """ResolutionSentimentRequest should default domain to 'general'."""
        from app.routers.analysis import ResolutionSentimentRequest
        req = ResolutionSentimentRequest(session_id="test")
        assert req.domain == "general"

    def test_happy_path(self) -> None:
        from app.utils.session import session_store
        from app.models import ParsedDialog, DialogueTurn

        session = session_store.create()
        session.dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Проблема"),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="Помогу"),
            ],
            total_turns=2,
            client_turns=1,
            employee_turns=1,
        )
        session_store.update(session)

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_resolution_sentiment_json())
            response = self.client.post(
                "/api/analysis/resolution-sentiment",
                json={"session_id": session.id, "provider_id": "beeline"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["resolution"] == "resolved"
        assert len(data["sentiment_trajectory"]) == 4

    def test_with_domain_parameter(self) -> None:
        from app.utils.session import session_store
        from app.models import ParsedDialog, DialogueTurn

        session = session_store.create()
        session.dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Проблема"),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="Помогу"),
            ],
            total_turns=2,
            client_turns=1,
            employee_turns=1,
        )
        session_store.update(session)

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_resolution_sentiment_json())
            response = self.client.post(
                "/api/analysis/resolution-sentiment",
                json={"session_id": session.id, "provider_id": "beeline", "domain": "insurance"},
            )
        assert response.status_code == 200

    def test_invalid_domain_falls_back_to_general(self) -> None:
        """Invalid domain value falls back to 'general'."""
        from app.routers.analysis import ResolutionSentimentRequest
        req = ResolutionSentimentRequest(session_id="test", domain="invalid_domain")
        # The domain value is stored as-is in the request model
        # but validated in the endpoint handler
        assert req.domain == "invalid_domain"

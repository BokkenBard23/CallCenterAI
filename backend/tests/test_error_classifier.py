"""Comprehensive tests for error classifier (IP-5.2).

Covers:
  - ErrorCategory enum (7 values)
  - ClassifiedError model
  - ErrorClassificationResult model
  - System prompt content
  - analyze_errors function (mock LLM → valid JSON → correct result)
  - Fallback on LLM failure
  - Domain-specific prompt addition (IP-6.1)
  - POST /api/analysis/errors endpoint
  - Invalid/missing session handling
  - Markdown-wrapped LLM response
  - Session_id override
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    ClassifiedError,
    DomainType,
    ErrorCategory,
    ErrorClassificationResult,
)
from app.services.llm import (
    _ERROR_CLASSIFIER_SYSTEM_PROMPT,
    analyze_errors,
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


def _valid_error_json(**overrides: Any) -> str:
    """Build a valid error classification JSON response."""
    data = {
        "session_id": "",
        "has_errors": True,
        "errors": [
            {
                "turn_index": 2,
                "speaker": "Сотрудник",
                "category": "communication_error",
                "severity": "medium",
                "description": "Сотрудник перебил клиента",
                "suggested_fix": "Дать клиенту закончить мысль",
            },
            {
                "turn_index": 5,
                "speaker": "Сотрудник",
                "category": "information_error",
                "severity": "high",
                "description": "Сотрудник назвал неверный тариф",
                "suggested_fix": "Проверять актуальность информации перед ответом",
            },
        ],
        "total_errors": 2,
        "errors_by_category": {
            "communication_error": 1,
            "information_error": 1,
        },
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 1. Enum tests
# ═══════════════════════════════════════════════════════════


class TestErrorCategory:
    """Tests for ErrorCategory enum."""

    def test_has_seven_values(self) -> None:
        assert len(ErrorCategory) == 7

    def test_values_are_lowercase_english(self) -> None:
        for member in ErrorCategory:
            assert member.value == member.value.lower()
            assert " " not in member.value

    def test_specific_values(self) -> None:
        assert ErrorCategory.communication_error.value == "communication_error"
        assert ErrorCategory.procedural_error.value == "procedural_error"
        assert ErrorCategory.information_error.value == "information_error"
        assert ErrorCategory.service_error.value == "service_error"
        assert ErrorCategory.compliance_violation.value == "compliance_violation"
        assert ErrorCategory.empathy_failure.value == "empathy_failure"
        assert ErrorCategory.response_delay.value == "response_delay"

    def test_from_value(self) -> None:
        assert ErrorCategory("communication_error") is ErrorCategory.communication_error
        assert ErrorCategory("compliance_violation") is ErrorCategory.compliance_violation

    def test_stable_identifiers(self) -> None:
        """Enum values are stable — UI depends on them."""
        expected = {
            "communication_error",
            "procedural_error",
            "information_error",
            "service_error",
            "compliance_violation",
            "empathy_failure",
            "response_delay",
        }
        actual = {m.value for m in ErrorCategory}
        assert actual == expected


# ═══════════════════════════════════════════════════════════
# 2. Model tests
# ═══════════════════════════════════════════════════════════


class TestClassifiedError:
    """Tests for ClassifiedError model."""

    def test_valid_error(self) -> None:
        err = ClassifiedError(
            turn_index=2,
            speaker="Сотрудник",
            category=ErrorCategory.communication_error,
            severity="medium",
            description="Перебил клиента",
            suggested_fix="Дать закончить мысль",
        )
        assert err.category == ErrorCategory.communication_error
        assert err.severity == "medium"

    def test_defaults(self) -> None:
        err = ClassifiedError(
            turn_index=0,
            speaker="Клиент",
            category=ErrorCategory.service_error,
            description="Ошибка",
        )
        assert err.severity == "low"
        assert err.suggested_fix == ""


class TestErrorClassificationResult:
    """Tests for ErrorClassificationResult model."""

    def test_default_values(self) -> None:
        result = ErrorClassificationResult()
        assert result.session_id == ""
        assert result.has_errors is False
        assert result.errors == []
        assert result.total_errors == 0
        assert result.errors_by_category == {}
        assert result.provider == "none"

    def test_with_errors(self) -> None:
        result = ErrorClassificationResult(
            session_id="s1",
            has_errors=True,
            errors=[
                ClassifiedError(
                    turn_index=2,
                    speaker="Сотрудник",
                    category=ErrorCategory.compliance_violation,
                    severity="high",
                    description="Разглашение персональных данных",
                ),
            ],
            total_errors=1,
            errors_by_category={"compliance_violation": 1},
            provider="beeline",
            model="glm-xlarge",
        )
        assert result.has_errors is True
        assert result.total_errors == 1
        assert result.errors[0].category == ErrorCategory.compliance_violation

    def test_from_json(self) -> None:
        data = json.loads(_valid_error_json())
        result = ErrorClassificationResult.model_validate(data)
        assert result.has_errors is True
        assert result.total_errors == 2
        assert len(result.errors) == 2
        assert result.errors[0].category == ErrorCategory.communication_error
        assert result.errors[1].severity == "high"
        assert result.errors_by_category == {
            "communication_error": 1,
            "information_error": 1,
        }

    def test_no_errors_json(self) -> None:
        raw = _valid_error_json(
            has_errors=False, errors=[], total_errors=0, errors_by_category={},
        )
        data = json.loads(raw)
        result = ErrorClassificationResult.model_validate(data)
        assert result.has_errors is False
        assert result.total_errors == 0


# ═══════════════════════════════════════════════════════════
# 3. System prompt tests
# ═══════════════════════════════════════════════════════════


class TestErrorClassifierPrompt:
    """Tests for _ERROR_CLASSIFIER_SYSTEM_PROMPT."""

    def test_contains_all_categories(self) -> None:
        for cat in ErrorCategory:
            assert cat.value in _ERROR_CLASSIFIER_SYSTEM_PROMPT

    def test_contains_severity_levels(self) -> None:
        assert "low" in _ERROR_CLASSIFIER_SYSTEM_PROMPT
        assert "medium" in _ERROR_CLASSIFIER_SYSTEM_PROMPT
        assert "high" in _ERROR_CLASSIFIER_SYSTEM_PROMPT

    def test_contains_suggested_fix(self) -> None:
        assert "suggested_fix" in _ERROR_CLASSIFIER_SYSTEM_PROMPT

    def test_contains_json_instruction(self) -> None:
        assert "JSON" in _ERROR_CLASSIFIER_SYSTEM_PROMPT

    def test_contains_artifact_ignore(self) -> None:
        assert "ИГНОРИРУЙ" in _ERROR_CLASSIFIER_SYSTEM_PROMPT or "артефакт" in _ERROR_CLASSIFIER_SYSTEM_PROMPT.lower()

    def test_contains_errors_by_category(self) -> None:
        assert "errors_by_category" in _ERROR_CLASSIFIER_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# 4. analyze_errors function tests
# ═══════════════════════════════════════════════════════════


class TestAnalyzeErrors:
    """Tests for analyze_errors async function."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_error_json())
            result = await analyze_errors(
                dialogue_text="Клиент: Привет\nСотрудник: Здравствуйте",
                session_id="s1",
                provider_id="beeline",
            )
        assert isinstance(result, ErrorClassificationResult)
        assert result.has_errors is True
        assert result.total_errors == 2
        assert len(result.errors) == 2
        assert result.errors[0].category == ErrorCategory.communication_error
        assert result.errors_by_category == {
            "communication_error": 1,
            "information_error": 1,
        }

    @pytest.mark.asyncio
    async def test_session_id_override(self) -> None:
        raw = _valid_error_json(session_id="wrong")
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_errors(
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
            result = await analyze_errors(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )
        assert result.provider == "none"
        assert result.has_errors is False
        assert result.errors == []
        assert result.total_errors == 0

    @pytest.mark.asyncio
    async def test_no_errors_dialogue(self) -> None:
        raw = _valid_error_json(
            has_errors=False, errors=[], total_errors=0, errors_by_category={},
        )
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_errors(
                dialogue_text="test",
                session_id="s1",
            )
        assert result.has_errors is False
        assert result.total_errors == 0

    @pytest.mark.asyncio
    async def test_with_domain_parameter(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(_valid_error_json())
            result = await analyze_errors(
                dialogue_text="test",
                session_id="s1",
                domain="banking",
            )
        assert isinstance(result, ErrorClassificationResult)

    @pytest.mark.asyncio
    async def test_markdown_wrapped_response(self) -> None:
        raw = '```json\n' + _valid_error_json() + '\n```'
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)
            result = await analyze_errors(
                dialogue_text="test",
                session_id="s1",
            )
        assert result.has_errors is True
        assert result.total_errors == 2

    @pytest.mark.asyncio
    async def test_broken_json_returns_defaults(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider("not json at all")
            result = await analyze_errors(
                dialogue_text="test",
                session_id="s1",
            )
        assert isinstance(result, ErrorClassificationResult)
        assert result.has_errors is False
        assert result.errors == []


# ═══════════════════════════════════════════════════════════
# 5. Endpoint tests
# ═══════════════════════════════════════════════════════════


class TestErrorEndpoint:
    """Tests for POST /api/analysis/errors endpoint."""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_endpoint_exists(self) -> None:
        """The /errors route should be registered."""
        routes = [r.path for r in app.routes]
        assert "/api/analysis/errors" in routes

    def test_missing_session_returns_404(self) -> None:
        response = self.client.post(
            "/api/analysis/errors",
            json={"session_id": "nonexistent", "provider_id": "beeline"},
        )
        assert response.status_code == 404

    def test_missing_body_returns_422(self) -> None:
        response = self.client.post(
            "/api/analysis/errors",
            json={},
        )
        assert response.status_code == 422

    def test_default_domain(self) -> None:
        """ErrorClassificationRequest should default domain to 'general'."""
        from app.routers.analysis import ErrorClassificationRequest
        req = ErrorClassificationRequest(session_id="test")
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
            mock_get.return_value = _mock_provider(_valid_error_json())
            response = self.client.post(
                "/api/analysis/errors",
                json={"session_id": session.id, "provider_id": "beeline"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["has_errors"] is True
        assert data["total_errors"] == 2

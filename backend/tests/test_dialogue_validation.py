"""Tests for dialogue validation endpoint (ID-12).

Tests cover:
  - DialogueValidationResult model validation
  - analyze_dialogue_validation function with circuit breaker + fallback
  - POST /api/analysis/validate endpoint
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models import DialogueValidationResult
from app.services.llm import (
    _VALIDATION_SYSTEM_PROMPT,
    analyze_dialogue_validation,
    _run_llm_analysis,
    _get_circuit_breaker,
)


# ═══════════════════════════════════════════════════════════
# Model tests
# ═══════════════════════════════════════════════════════════


class TestDialogueValidationResultModel:
    """Tests for DialogueValidationResult Pydantic model."""

    def test_default_values(self):
        """Verify default values are correct."""
        result = DialogueValidationResult()
        assert result.is_valid_dialogue is False
        assert result.confidence == 0.0
        assert result.reason == ""
        assert result.language_detected == "ru"
        assert result.provider == "none"
        assert result.model == ""

    def test_valid_dialogue_result(self):
        """Verify construction with valid dialogue result."""
        result = DialogueValidationResult(
            is_valid_dialogue=True,
            confidence=0.95,
            reason="Диалог содержит осмысленные реплики клиента и сотрудника",
            language_detected="ru",
            provider="beeline",
            model="glm-xlarge",
        )
        assert result.is_valid_dialogue is True
        assert result.confidence == 0.95
        assert "осмысленные" in result.reason
        assert result.language_detected == "ru"
        assert result.provider == "beeline"

    def test_invalid_dialogue_result(self):
        """Verify construction with invalid dialogue result."""
        result = DialogueValidationResult(
            is_valid_dialogue=False,
            confidence=0.8,
            reason="Текст не содержит диалоговой структуры",
            language_detected="en",
            provider="ollama",
        )
        assert result.is_valid_dialogue is False
        assert result.confidence == 0.8
        assert result.language_detected == "en"

    def test_confidence_bounds(self):
        """Verify confidence is bounded [0.0, 1.0]."""
        # Valid boundaries
        DialogueValidationResult(confidence=0.0)
        DialogueValidationResult(confidence=1.0)
        DialogueValidationResult(confidence=0.5)

        # Invalid — below 0
        with pytest.raises(Exception):
            DialogueValidationResult(confidence=-0.1)

        # Invalid — above 1
        with pytest.raises(Exception):
            DialogueValidationResult(confidence=1.1)

    def test_serialization_roundtrip(self):
        """Verify JSON serialization/deserialization roundtrip."""
        original = DialogueValidationResult(
            is_valid_dialogue=True,
            confidence=0.88,
            reason="Валидный диалог с 5 репликами",
            language_detected="ru",
            provider="beeline",
            model="glm-xlarge",
        )
        json_str = original.model_dump_json()
        restored = DialogueValidationResult.model_validate_json(json_str)
        assert restored.is_valid_dialogue == original.is_valid_dialogue
        assert restored.confidence == original.confidence
        assert restored.reason == original.reason
        assert restored.language_detected == original.language_detected
        assert restored.provider == original.provider
        assert restored.model == original.model


# ═══════════════════════════════════════════════════════════
# System prompt tests
# ═══════════════════════════════════════════════════════════


class TestValidationSystemPrompt:
    """Tests for the dialogue validation system prompt."""

    def test_prompt_exists(self):
        """Verify the system prompt is defined."""
        assert _VALIDATION_SYSTEM_PROMPT is not None
        assert len(_VALIDATION_SYSTEM_PROMPT) > 100

    def test_prompt_contains_json_instruction(self):
        """Verify the prompt requests JSON output."""
        assert "JSON" in _VALIDATION_SYSTEM_PROMPT

    def test_prompt_contains_validation_fields(self):
        """Verify the prompt mentions all required fields."""
        assert "is_valid_dialogue" in _VALIDATION_SYSTEM_PROMPT
        assert "confidence" in _VALIDATION_SYSTEM_PROMPT
        assert "reason" in _VALIDATION_SYSTEM_PROMPT
        assert "language_detected" in _VALIDATION_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# Analysis function tests
# ═══════════════════════════════════════════════════════════


class TestAnalyzeDialogueValidation:
    """Tests for analyze_dialogue_validation function."""

    @pytest.mark.asyncio
    async def test_happy_path_valid_dialogue(self):
        """Verify valid dialogue is correctly detected."""
        llm_response = json.dumps({
            "is_valid_dialogue": True,
            "confidence": 0.92,
            "reason": "Диалог содержит осмысленные реплики",
            "language_detected": "ru",
        })

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=llm_response)
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.get_name.return_value = "test"

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            with patch("app.services.llm._get_circuit_breaker") as mock_cb:
                cb = MagicMock()
                cb.can_execute.return_value = True
                cb.state = "closed"
                mock_cb.return_value = cb

                result = await analyze_dialogue_validation(
                    dialogue_text="Клиент: Здравствуйте\nСотрудник: Добрый день",
                    provider_id="test",
                )

        assert isinstance(result, DialogueValidationResult)
        assert result.is_valid_dialogue is True
        assert result.confidence == 0.92
        assert "осмысленные" in result.reason
        assert result.language_detected == "ru"

    @pytest.mark.asyncio
    async def test_happy_path_invalid_dialogue(self):
        """Verify non-dialogue text is correctly rejected."""
        llm_response = json.dumps({
            "is_valid_dialogue": False,
            "confidence": 0.85,
            "reason": "Текст не содержит диалоговой структуры",
            "language_detected": "ru",
        })

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=llm_response)
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.get_name.return_value = "test"

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            with patch("app.services.llm._get_circuit_breaker") as mock_cb:
                cb = MagicMock()
                cb.can_execute.return_value = True
                cb.state = "closed"
                mock_cb.return_value = cb

                result = await analyze_dialogue_validation(
                    dialogue_text="Случайный текст без структуры",
                    provider_id="test",
                )

        assert result.is_valid_dialogue is False
        assert result.confidence == 0.85
        assert "не содержит" in result.reason

    @pytest.mark.asyncio
    async def test_llm_failure_returns_default(self):
        """Verify graceful degradation when all LLM providers fail."""
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=ConnectionError("unavailable"))
        mock_provider.get_name.return_value = "test"

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            with patch("app.services.llm._get_circuit_breaker") as mock_cb:
                cb = MagicMock()
                cb.can_execute.return_value = True
                cb.state = "closed"
                mock_cb.return_value = cb

                result = await analyze_dialogue_validation(
                    dialogue_text="some text",
                    provider_id="test",
                )

        assert result.is_valid_dialogue is False
        assert result.confidence == 0.0
        assert "LLM unavailable" in result.reason
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_malformed_json_returns_default(self):
        """Verify graceful handling of malformed LLM JSON."""
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value="not valid json at all")
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.get_name.return_value = "test"

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            with patch("app.services.llm._get_circuit_breaker") as mock_cb:
                cb = MagicMock()
                cb.can_execute.return_value = True
                cb.state = "closed"
                mock_cb.return_value = cb

                result = await analyze_dialogue_validation(
                    dialogue_text="some text",
                    provider_id="test",
                )

        # Should return default instance (model defaults)
        assert isinstance(result, DialogueValidationResult)
        # Provider should still be recorded from the successful generation
        # (even though parsing failed, the provider did respond)

    @pytest.mark.asyncio
    async def test_markdown_wrapped_json(self):
        """Verify handling of markdown-wrapped JSON response."""
        llm_response = "```json\n" + json.dumps({
            "is_valid_dialogue": True,
            "confidence": 0.9,
            "reason": "Валидный диалог",
            "language_detected": "ru",
        }) + "\n```"

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=llm_response)
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.get_name.return_value = "test"

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            with patch("app.services.llm._get_circuit_breaker") as mock_cb:
                cb = MagicMock()
                cb.can_execute.return_value = True
                cb.state = "closed"
                mock_cb.return_value = cb

                result = await analyze_dialogue_validation(
                    dialogue_text="Клиент: Здравствуйте",
                    provider_id="test",
                )

        assert result.is_valid_dialogue is True
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_skips_provider(self):
        """Verify that open circuit breaker skips the provider."""
        with patch("app.services.llm._get_circuit_breaker") as mock_cb:
            cb = MagicMock()
            cb.can_execute.return_value = False
            cb.state = "open"
            mock_cb.return_value = cb

            with patch("app.services.llm.get_provider", return_value=None):
                result = await analyze_dialogue_validation(
                    dialogue_text="some text",
                    provider_id="test",
                )

        assert result.is_valid_dialogue is False
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_partial_json_fields(self):
        """Verify handling of JSON with missing optional fields."""
        llm_response = json.dumps({
            "is_valid_dialogue": True,
            "confidence": 0.7,
            "reason": "OK",
            # language_detected missing — should use default "ru"
        })

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=llm_response)
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.get_name.return_value = "test"

        with patch("app.services.llm.get_provider", return_value=mock_provider):
            with patch("app.services.llm._get_circuit_breaker") as mock_cb:
                cb = MagicMock()
                cb.can_execute.return_value = True
                cb.state = "closed"
                mock_cb.return_value = cb

                result = await analyze_dialogue_validation(
                    dialogue_text="some text",
                    provider_id="test",
                )

        assert result.is_valid_dialogue is True
        # language_detected defaults to "ru" when missing from LLM response
        assert result.language_detected == "ru"


# ═══════════════════════════════════════════════════════════
# Endpoint tests
# ═══════════════════════════════════════════════════════════


class TestDialogueValidationEndpoint:
    """Tests for POST /api/analysis/validate endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        from app.main import app
        return TestClient(app)

    @pytest.fixture
    def session_with_dialogue(self, client):
        """Create a session with an uploaded dialogue."""
        from app.utils.session import session_store
        from app.models import DialogueTurn, ParsedDialog

        session_id = "test-validation-session"
        session = session_store.create(session_id)
        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте, я хочу отключить услугу"),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день! Какую именно услугу вы хотите отключить?"),
                DialogueTurn(turn_index=2, speaker="Клиент", text="Платную подписку на музыку"),
            ],
            total_turns=3,
            client_turns=2,
            employee_turns=1,
        )
        session.dialog = dialog
        session_store.update(session)
        return session.id

    def test_validate_endpoint_404_missing_session(self, client):
        """Verify 404 when session not found."""
        response = client.post(
            "/api/analysis/validate",
            json={"session_id": "nonexistent", "provider_id": "beeline"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_validate_endpoint_400_no_dialogue(self, client):
        """Verify 400 when session has no dialogue."""
        from app.utils.session import session_store
        session_id = "test-no-dialogue"
        session_store.create(session_id)

        try:
            response = client.post(
                "/api/analysis/validate",
                json={"session_id": session_id, "provider_id": "beeline"},
            )
            assert response.status_code == 400
            assert "no dialogue" in response.json()["detail"].lower()
        finally:
            # Cleanup
            session_store.delete(session_id)

    def test_validate_endpoint_returns_validation_result(self, client, session_with_dialogue):
        """Verify endpoint returns DialogueValidationResult structure."""
        with patch("app.routers.analysis.analyze_dialogue_validation") as mock_analyze:
            mock_analyze.return_value = DialogueValidationResult(
                is_valid_dialogue=True,
                confidence=0.95,
                reason="Диалог содержит осмысленные реплики",
                language_detected="ru",
                provider="test",
                model="test-model",
            )

            response = client.post(
                "/api/analysis/validate",
                json={
                    "session_id": session_with_dialogue,
                    "provider_id": "beeline",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid_dialogue"] is True
        assert data["confidence"] == 0.95
        assert data["reason"] != ""
        assert data["language_detected"] == "ru"
        assert "provider" in data
        assert "model" in data

    def test_validate_endpoint_default_provider(self, client, session_with_dialogue):
        """Verify default provider_id is 'beeline'."""
        with patch("app.routers.analysis.analyze_dialogue_validation") as mock_analyze:
            mock_analyze.return_value = DialogueValidationResult(
                is_valid_dialogue=False,
                confidence=0.0,
                reason="LLM unavailable",
                provider="none",
            )

            response = client.post(
                "/api/analysis/validate",
                json={"session_id": session_with_dialogue},
            )

        assert response.status_code == 200
        # Check that analyze_dialogue_validation was called with default provider
        mock_analyze.assert_called_once()
        call_kwargs = mock_analyze.call_args.kwargs
        assert call_kwargs.get("provider_id") == "beeline"

    def test_validate_endpoint_invalid_body(self, client):
        """Verify 422 when request body is invalid."""
        response = client.post(
            "/api/analysis/validate",
            json={},  # Missing session_id
        )
        assert response.status_code == 422

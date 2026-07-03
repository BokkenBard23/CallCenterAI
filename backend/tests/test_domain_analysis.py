"""Comprehensive tests for domain-specific analysis (IP-6.1).

Covers:
  - DomainType enum (5 values)
  - _DOMAIN_PROMPT_ADDITIONS content for each domain
  - get_domain_prompt_addition function
  - LLMOrchestrator with domain parameter
  - POST /api/analysis/full with domain parameter
  - Domain prompt prepended to analysis prompts
  - AnalysisAnnotation.domain field
  - Config: analysis_default_domain
  - Integration: domain affects resolution-sentiment and error classifier
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    AnalysisAnnotation,
    DomainType,
    ProgressInfo,
    ResolutionSentimentResult,
)
from app.services.llm import (
    _DOMAIN_PROMPT_ADDITIONS,
    _RESOLUTION_SENTIMENT_SYSTEM_PROMPT,
    LLMOrchestrator,
    analyze_errors,
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


# ═══════════════════════════════════════════════════════════
# 1. DomainType enum tests
# ═══════════════════════════════════════════════════════════


class TestDomainType:
    """Tests for DomainType enum."""

    def test_has_five_values(self) -> None:
        assert len(DomainType) == 5

    def test_values_are_lowercase_english(self) -> None:
        for member in DomainType:
            assert member.value == member.value.lower()

    def test_specific_values(self) -> None:
        assert DomainType.general.value == "general"
        assert DomainType.insurance.value == "insurance"
        assert DomainType.banking.value == "banking"
        assert DomainType.healthcare.value == "healthcare"
        assert DomainType.telecom.value == "telecom"

    def test_from_value(self) -> None:
        assert DomainType("general") is DomainType.general
        assert DomainType("telecom") is DomainType.telecom

    def test_stable_identifiers(self) -> None:
        """Enum values are stable — UI domain selector depends on them."""
        expected = {"general", "insurance", "banking", "healthcare", "telecom"}
        actual = {m.value for m in DomainType}
        assert actual == expected


# ═══════════════════════════════════════════════════════════
# 2. Domain prompt content tests
# ═══════════════════════════════════════════════════════════


class TestDomainPromptAdditions:
    """Tests for _DOMAIN_PROMPT_ADDITIONS content."""

    def test_four_domains_have_additions(self) -> None:
        """Insurance, banking, healthcare, telecom have prompt additions."""
        assert DomainType.insurance.value in _DOMAIN_PROMPT_ADDITIONS
        assert DomainType.banking.value in _DOMAIN_PROMPT_ADDITIONS
        assert DomainType.healthcare.value in _DOMAIN_PROMPT_ADDITIONS
        assert DomainType.telecom.value in _DOMAIN_PROMPT_ADDITIONS

    def test_general_not_in_additions(self) -> None:
        """'general' domain has no additions."""
        assert DomainType.general.value not in _DOMAIN_PROMPT_ADDITIONS

    def test_insurance_content(self) -> None:
        content = _DOMAIN_PROMPT_ADDITIONS[DomainType.insurance.value]
        assert "СТРАХОВАНИЕ" in content
        assert "страховых случаев" in content.lower() or "полис" in content.lower()

    def test_banking_content(self) -> None:
        content = _DOMAIN_PROMPT_ADDITIONS[DomainType.banking.value]
        assert "БАНКИНГ" in content
        assert "мошенничеств" in content.lower() or "безопасност" in content.lower()

    def test_healthcare_content(self) -> None:
        content = _DOMAIN_PROMPT_ADDITIONS[DomainType.healthcare.value]
        assert "ЗДРАВООХРАНЕНИЕ" in content
        assert "конфиденциаль" in content.lower() or "пациент" in content.lower()

    def test_telecom_content(self) -> None:
        content = _DOMAIN_PROMPT_ADDITIONS[DomainType.telecom.value]
        assert "ТЕЛЕКОММУНИКАЦИИ" in content
        assert "биллинг" in content.lower() or "тариф" in content.lower()


# ═══════════════════════════════════════════════════════════
# 3. get_domain_prompt_addition function tests
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
        assert get_domain_prompt_addition("unknown_domain") == ""

    def test_empty_string_returns_empty(self) -> None:
        assert get_domain_prompt_addition("") == ""


# ═══════════════════════════════════════════════════════════
# 4. AnalysisAnnotation domain field
# ═══════════════════════════════════════════════════════════


class TestAnalysisAnnotationDomainField:
    """Tests for AnalysisAnnotation.domain field."""

    def test_default_domain_is_general(self) -> None:
        annotation = AnalysisAnnotation(
            session_id="s1",
            progress=ProgressInfo(),
        )
        assert annotation.domain == "general"

    def test_domain_can_be_set(self) -> None:
        annotation = AnalysisAnnotation(
            session_id="s1",
            progress=ProgressInfo(),
            domain="insurance",
        )
        assert annotation.domain == "insurance"


# ═══════════════════════════════════════════════════════════
# 5. LLMOrchestrator with domain parameter
# ═══════════════════════════════════════════════════════════


class TestOrchestratorDomainParameter:
    """Tests for LLMOrchestrator.run_all_analyses with domain parameter."""

    @pytest.mark.asyncio
    async def test_default_domain_is_general(self) -> None:
        """Orchestrator defaults to domain='general'."""
        orchestrator = LLMOrchestrator(steps=[])  # no steps for speed
        result = await orchestrator.run_all_analyses(
            dialogue_text="test",
            session_id="s1",
            provider_id="beeline",
        )
        assert result.domain == "general"

    @pytest.mark.asyncio
    async def test_domain_propagated_to_result(self) -> None:
        """Domain parameter is stored in the AnalysisAnnotation result."""
        orchestrator = LLMOrchestrator(steps=[])  # no steps for speed
        result = await orchestrator.run_all_analyses(
            dialogue_text="test",
            session_id="s1",
            provider_id="beeline",
            domain="banking",
        )
        assert result.domain == "banking"

    @pytest.mark.asyncio
    async def test_domain_with_steps(self) -> None:
        """Domain works with actual analysis steps."""
        from app.models import SentimentAnalysisResult

        mock_sentiment = SentimentAnalysisResult(
            utterances=[],
            overall_sentiment="neutral",
            sentiment_trajectory="stable",
            provider="test",
            model="test-model",
        )

        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "utterances": [],
                    "overall_sentiment": "neutral",
                    "sentiment_trajectory": "stable",
                })
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            orchestrator = LLMOrchestrator(steps=["sentiment"])
            result = await orchestrator.run_all_analyses(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
                domain="healthcare",
            )

        assert result.domain == "healthcare"


# ═══════════════════════════════════════════════════════════
# 6. Domain in resolution-sentiment analysis
# ═══════════════════════════════════════════════════════════


class TestDomainInResolutionSentiment:
    """Domain parameter affects analyze_resolution_sentiment prompt."""

    @pytest.mark.asyncio
    async def test_domain_prepended_to_prompt(self) -> None:
        """When domain != general, domain addition is prepended to system prompt."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "resolution": "resolved",
                    "resolution_confidence": 0.9,
                    "resolution_reason": "Test",
                    "sentiment_trajectory": [],
                    "sentiment_start": "neutral",
                    "sentiment_end": "neutral",
                    "trajectory_direction": "stable",
                })
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
                domain="insurance",
            )

            # Verify that the system_prompt passed to generate includes domain context
            call_kwargs = mock_provider.generate.call_args.kwargs
            assert "system_prompt" in call_kwargs
            assert "СТРАХОВАНИЕ" in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_general_domain_no_addition(self) -> None:
        """When domain=general, no addition is prepended."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "resolution": "unresolved",
                    "resolution_confidence": 0.5,
                    "resolution_reason": "Test",
                    "sentiment_trajectory": [],
                    "sentiment_start": "neutral",
                    "sentiment_end": "neutral",
                    "trajectory_direction": "stable",
                })
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_resolution_sentiment(
                dialogue_text="test",
                session_id="s1",
                domain="general",
            )

            call_kwargs = mock_provider.generate.call_args.kwargs
            assert "system_prompt" in call_kwargs
            # The prompt should be the base prompt without domain addition
            assert "СТРАХОВАНИЕ" not in call_kwargs["system_prompt"]
            assert "БАНКИНГ" not in call_kwargs["system_prompt"]


# ═══════════════════════════════════════════════════════════
# 7. Domain in error classifier
# ═══════════════════════════════════════════════════════════


class TestDomainInErrorClassifier:
    """Domain parameter affects analyze_errors prompt."""

    @pytest.mark.asyncio
    async def test_banking_domain_prepended(self) -> None:
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "has_errors": False,
                    "errors": [],
                    "total_errors": 0,
                    "errors_by_category": {},
                })
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            await analyze_errors(
                dialogue_text="test",
                session_id="s1",
                domain="banking",
            )

            call_kwargs = mock_provider.generate.call_args.kwargs
            assert "БАНКИНГ" in call_kwargs["system_prompt"]


# ═══════════════════════════════════════════════════════════
# 8. POST /api/analysis/full with domain
# ═══════════════════════════════════════════════════════════


class TestFullAnalysisDomainEndpoint:
    """Tests for POST /api/analysis/full with domain parameter."""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_full_analysis_default_domain(self) -> None:
        from app.routers.analysis import FullAnalysisRequest
        req = FullAnalysisRequest(session_id="test")
        assert req.domain == "general"

    def test_full_analysis_with_domain(self) -> None:
        from app.routers.analysis import FullAnalysisRequest
        req = FullAnalysisRequest(session_id="test", domain="telecom")
        assert req.domain == "telecom"

    def test_full_analysis_endpoint_with_domain(self) -> None:
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

        # Mock all LLM providers to return valid results
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "utterances": [],
                    "overall_sentiment": "neutral",
                    "sentiment_trajectory": "stable",
                })
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            response = self.client.post(
                "/api/analysis/full",
                json={
                    "session_id": session.id,
                    "provider_id": "beeline",
                    "include_summary": False,
                    "domain": "insurance",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["domain"] == "insurance"

    def test_full_analysis_invalid_domain_falls_back(self) -> None:
        """Invalid domain value falls back to 'general'."""
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
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=json.dumps({
                    "utterances": [],
                    "overall_sentiment": "neutral",
                    "sentiment_trajectory": "stable",
                })
            )
            mock_provider.get_default_model = lambda: "test-model"
            mock_get.return_value = mock_provider

            response = self.client.post(
                "/api/analysis/full",
                json={
                    "session_id": session.id,
                    "provider_id": "beeline",
                    "include_summary": False,
                    "domain": "invalid_domain",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["domain"] == "general"


# ═══════════════════════════════════════════════════════════
# 9. Config: analysis_default_domain
# ═══════════════════════════════════════════════════════════


class TestAnalysisDefaultDomainConfig:
    """Tests for analysis_default_domain config setting."""

    def test_default_value(self) -> None:
        from app.config import settings
        assert settings.analysis_default_domain == "general"

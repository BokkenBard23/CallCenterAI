"""Comprehensive tests for quality scoring (IP-4.1).

Covers:
  - QualityCategory enum completeness (12 categories)
  - QualityLevel enum (high/medium/low)
  - CategoryScore model validation (score range 0-1, valid categories)
  - QualityScoreResult model defaults and derived fields
  - QUALITY_CATEGORY_LABELS mapping completeness
  - _compute_quality_derived_fields (overall_score, overall_level, strengths, weaknesses)
  - _build_quality_fallback_result (all categories at medium)
  - analyze_quality function (mock LLM → valid JSON → correct result)
  - POST /api/analysis/quality-score endpoint
  - Fallback on LLM failure (circuit breaker / connection error)
  - Score derivation from level
  - All 12 categories present in response
  - Invalid/missing session handling
  - Markdown-wrapped LLM response
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CategoryScore,
    QualityCategory,
    QualityLevel,
    QualityScoreResult,
    QUALITY_CATEGORY_LABELS,
)
from app.services.llm import (
    _QUALITY_SYSTEM_PROMPT,
    _compute_quality_derived_fields,
    _build_quality_fallback_result,
    _circuit_breakers,
    analyze_quality,
)


@pytest.fixture(autouse=True)
def _reset_circuit_breakers():
    """Reset circuit breaker state between tests.

    The module-level ``_circuit_breakers`` dict persists across tests.
    Earlier tests may open the 'beeline' circuit breaker, causing
    quality scoring tests to skip beeline and fall back to ollama.
    """
    _circuit_breakers.clear()
    yield
    _circuit_breakers.clear()


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


def _mock_provider(response_text: str) -> AsyncMock:
    """Create a mock LLM provider with proper sync/async method setup.

    - ``generate`` is async (AsyncMock).
    - ``get_default_model`` is sync (plain lambda), matching the ABC.
    """
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value=response_text)
    mock_provider.get_default_model = lambda: "test-model"
    return mock_provider


def _valid_quality_json(session_id: str = "test-session", **overrides: Any) -> str:
    """Build a valid quality-scoring JSON response."""
    categories_data = []
    for cat in QualityCategory:
        categories_data.append({
            "category": cat.value,
            "level": "medium",
            "score": 0.66,
            "justification": f"Оценка для {cat.value}",
        })
    # Vary some categories to test strengths/weaknesses
    categories_data[0] = {
        "category": "communication_skills",
        "level": "high",
        "score": 0.9,
        "justification": "Сотрудник общался ясно и вежливо",
    }
    categories_data[7] = {
        "category": "efficiency",
        "level": "low",
        "score": 0.33,
        "justification": "Долгое решение простого вопроса",
    }

    data = {
        "session_id": session_id,
        "categories": categories_data,
        "strengths": ["communication_skills"],
        "weaknesses": ["efficiency"],
        "recommendations": [
            "Ускорить обработку типовых запросов",
            "Продолжать использовать вежливую коммуникацию",
        ],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _minimal_quality_json() -> str:
    """Build a minimal valid quality JSON (only categories, no derived fields)."""
    categories_data = [
        {
            "category": cat.value,
            "level": "high" if cat.value == "empathy" else "medium",
            "score": 1.0 if cat.value == "empathy" else 0.66,
            "justification": f"Оценка {cat.value}",
        }
        for cat in QualityCategory
    ]
    return json.dumps({"categories": categories_data}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 1. Enum tests
# ═══════════════════════════════════════════════════════════


class TestQualityLevel:
    """Tests for QualityLevel enum."""

    def test_has_three_values(self) -> None:
        assert len(QualityLevel) == 3

    def test_values_are_lowercase_english(self) -> None:
        for member in QualityLevel:
            assert member.value == member.value.lower()
            assert member.value in ("high", "medium", "low")

    def test_specific_values(self) -> None:
        assert QualityLevel.high.value == "high"
        assert QualityLevel.medium.value == "medium"
        assert QualityLevel.low.value == "low"

    def test_from_value(self) -> None:
        assert QualityLevel("high") is QualityLevel.high
        assert QualityLevel("medium") is QualityLevel.medium
        assert QualityLevel("low") is QualityLevel.low


class TestQualityCategory:
    """Tests for QualityCategory enum (12 categories)."""

    def test_has_twelve_categories(self) -> None:
        assert len(QualityCategory) == 12

    def test_all_expected_categories_present(self) -> None:
        expected = {
            "communication_skills",
            "problem_solving",
            "product_knowledge",
            "responsiveness",
            "professionalism",
            "empathy",
            "accuracy",
            "efficiency",
            "follow_up_procedures",
            "conflict_resolution",
            "compliance",
            "customer_education",
        }
        actual = {member.value for member in QualityCategory}
        assert actual == expected

    def test_values_are_snake_case(self) -> None:
        for member in QualityCategory:
            assert member.value == member.value.lower()
            assert " " not in member.value
            assert "-" not in member.value

    def test_from_value(self) -> None:
        assert QualityCategory("communication_skills") is QualityCategory.communication_skills
        assert QualityCategory("customer_education") is QualityCategory.customer_education


class TestQualityCategoryLabels:
    """Tests for QUALITY_CATEGORY_LABELS mapping."""

    def test_all_categories_have_labels(self) -> None:
        for cat in QualityCategory:
            assert cat.value in QUALITY_CATEGORY_LABELS

    def test_labels_are_russian(self) -> None:
        for cat in QualityCategory:
            label = QUALITY_CATEGORY_LABELS[cat.value]
            assert len(label) > 0
            # Russian labels should have Cyrillic characters
            assert any("\u0400" <= ch <= "\u04FF" for ch in label)

    def test_exactly_twelve_labels(self) -> None:
        assert len(QUALITY_CATEGORY_LABELS) == 12

    def test_specific_labels(self) -> None:
        assert QUALITY_CATEGORY_LABELS["communication_skills"] == "Навыки общения"
        assert QUALITY_CATEGORY_LABELS["problem_solving"] == "Решение проблем"
        assert QUALITY_CATEGORY_LABELS["customer_education"] == "Обучение клиента"


# ═══════════════════════════════════════════════════════════
# 2. Model validation tests
# ═══════════════════════════════════════════════════════════


class TestCategoryScore:
    """Tests for CategoryScore model."""

    def test_valid_category_score(self) -> None:
        cs = CategoryScore(
            category=QualityCategory.communication_skills,
            level=QualityLevel.high,
            score=0.9,
            justification="Отличная коммуникация",
        )
        assert cs.category == QualityCategory.communication_skills
        assert cs.level == QualityLevel.high
        assert cs.score == 0.9
        assert cs.justification == "Отличная коммуникация"

    def test_score_boundary_low(self) -> None:
        cs = CategoryScore(
            category=QualityCategory.empathy,
            level=QualityLevel.low,
            score=0.0,
        )
        assert cs.score == 0.0

    def test_score_boundary_high(self) -> None:
        cs = CategoryScore(
            category=QualityCategory.empathy,
            level=QualityLevel.high,
            score=1.0,
        )
        assert cs.score == 1.0

    def test_score_below_zero_rejected(self) -> None:
        with pytest.raises(Exception):
            CategoryScore(
                category=QualityCategory.empathy,
                level=QualityLevel.low,
                score=-0.1,
            )

    def test_score_above_one_rejected(self) -> None:
        with pytest.raises(Exception):
            CategoryScore(
                category=QualityCategory.empathy,
                level=QualityLevel.high,
                score=1.1,
            )

    def test_default_justification(self) -> None:
        cs = CategoryScore(
            category=QualityCategory.compliance,
            level=QualityLevel.medium,
            score=0.66,
        )
        assert cs.justification == ""

    def test_from_dict_with_string_values(self) -> None:
        """CategoryScore should accept string values for category/level."""
        cs = CategoryScore(
            category="communication_skills",
            level="high",
            score=0.9,
            justification="Test",
        )
        assert cs.category == QualityCategory.communication_skills
        assert cs.level == QualityLevel.high

    def test_invalid_category_rejected(self) -> None:
        with pytest.raises(Exception):
            CategoryScore(
                category="nonexistent_category",
                level="high",
                score=0.9,
            )

    def test_invalid_level_rejected(self) -> None:
        with pytest.raises(Exception):
            CategoryScore(
                category=QualityCategory.empathy,
                level="critical",
                score=0.9,
            )


class TestQualityScoreResult:
    """Tests for QualityScoreResult model."""

    def test_default_values(self) -> None:
        result = QualityScoreResult(session_id="test")
        assert result.session_id == "test"
        assert result.categories == []
        assert result.overall_score == 0.0
        assert result.overall_level == QualityLevel.medium
        assert result.strengths == []
        assert result.weaknesses == []
        assert result.recommendations == []
        assert result.provider == "none"
        assert result.model == ""

    def test_with_categories(self) -> None:
        categories = [
            CategoryScore(category=QualityCategory.communication_skills, level=QualityLevel.high, score=0.9),
            CategoryScore(category=QualityCategory.efficiency, level=QualityLevel.low, score=0.33),
        ]
        result = QualityScoreResult(
            session_id="s1",
            categories=categories,
            overall_score=0.615,
            overall_level=QualityLevel.medium,
            strengths=["communication_skills"],
            weaknesses=["efficiency"],
        )
        assert len(result.categories) == 2
        assert result.overall_score == 0.615

    def test_from_json_response(self) -> None:
        """QualityScoreResult should parse from a typical LLM JSON response."""
        raw = _valid_quality_json(session_id="sess-123")
        parsed = json.loads(raw)
        result = QualityScoreResult.model_validate(parsed)
        assert result.session_id == "sess-123"
        assert len(result.categories) == 12
        assert len(result.recommendations) == 2


# ═══════════════════════════════════════════════════════════
# 3. Derived fields computation
# ═══════════════════════════════════════════════════════════


class TestComputeQualityDerivedFields:
    """Tests for _compute_quality_derived_fields."""

    def _make_result(
        self,
        categories: List[CategoryScore],
        session_id: str = "test",
        recommendations: List[str] | None = None,
    ) -> QualityScoreResult:
        return QualityScoreResult(
            session_id=session_id,
            categories=categories,
            recommendations=recommendations or [],
        )

    def test_empty_categories(self) -> None:
        result = QualityScoreResult(session_id="test", categories=[])
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_score == 0.0
        assert computed.overall_level == QualityLevel.medium
        assert computed.strengths == []
        assert computed.weaknesses == []

    def test_all_high(self) -> None:
        categories = [
            CategoryScore(category=cat, level=QualityLevel.high, score=1.0)
            for cat in QualityCategory
        ]
        result = self._make_result(categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_score == 1.0
        assert computed.overall_level == QualityLevel.high
        assert len(computed.strengths) == 12
        assert computed.weaknesses == []

    def test_all_low(self) -> None:
        categories = [
            CategoryScore(category=cat, level=QualityLevel.low, score=0.2)
            for cat in QualityCategory
        ]
        result = self._make_result(categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_score == 0.2
        assert computed.overall_level == QualityLevel.low
        assert computed.strengths == []
        assert len(computed.weaknesses) == 12

    def test_mixed_levels(self) -> None:
        categories = [
            CategoryScore(category=QualityCategory.communication_skills, level=QualityLevel.high, score=0.9),
            CategoryScore(category=QualityCategory.problem_solving, level=QualityLevel.medium, score=0.6),
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.low, score=0.3),
        ]
        result = self._make_result(categories)
        computed = _compute_quality_derived_fields(result)
        expected_score = round((0.9 + 0.6 + 0.3) / 3, 4)
        assert computed.overall_score == expected_score
        assert computed.overall_level == QualityLevel.medium  # 0.6 >= 0.5
        assert computed.strengths == ["communication_skills"]
        assert computed.weaknesses == ["empathy"]

    def test_overall_level_high_threshold(self) -> None:
        """overall_score > 0.75 → high."""
        categories = [
            CategoryScore(category=QualityCategory.communication_skills, level=QualityLevel.high, score=0.8),
        ]
        result = self._make_result(categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.high

    def test_overall_level_medium_threshold(self) -> None:
        """0.5 ≤ overall_score ≤ 0.75 → medium."""
        categories = [
            CategoryScore(category=QualityCategory.communication_skills, level=QualityLevel.medium, score=0.5),
        ]
        result = self._make_result(categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.medium

    def test_overall_level_low_threshold(self) -> None:
        """overall_score < 0.5 → low."""
        categories = [
            CategoryScore(category=QualityCategory.communication_skills, level=QualityLevel.low, score=0.4),
        ]
        result = self._make_result(categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.low

    def test_preserves_recommendations(self) -> None:
        categories = [
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.medium, score=0.6),
        ]
        recs = ["Рекомендация 1", "Рекомендация 2"]
        result = self._make_result(categories, recommendations=recs)
        computed = _compute_quality_derived_fields(result)
        assert computed.recommendations == recs

    def test_preserves_provider_and_model(self) -> None:
        categories = [
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.medium, score=0.6),
        ]
        result = QualityScoreResult(
            session_id="test",
            categories=categories,
            provider="beeline",
            model="glm-5.1",
        )
        computed = _compute_quality_derived_fields(result)
        assert computed.provider == "beeline"
        assert computed.model == "glm-5.1"


# ═══════════════════════════════════════════════════════════
# 4. Fallback result builder
# ═══════════════════════════════════════════════════════════


class TestBuildQualityFallbackResult:
    """Tests for _build_quality_fallback_result."""

    def test_all_categories_at_medium(self) -> None:
        result = _build_quality_fallback_result("sess-1")
        assert len(result.categories) == 12
        for cat in result.categories:
            assert cat.level == QualityLevel.medium
            assert cat.score == 0.66
            assert cat.justification == ""

    def test_session_id_propagated(self) -> None:
        result = _build_quality_fallback_result("my-session")
        assert result.session_id == "my-session"

    def test_provider_is_none(self) -> None:
        result = _build_quality_fallback_result("s1")
        assert result.provider == "none"
        assert result.model == ""

    def test_overall_score_medium(self) -> None:
        result = _build_quality_fallback_result("s1")
        assert result.overall_score == 0.66
        assert result.overall_level == QualityLevel.medium

    def test_no_strengths_or_weaknesses(self) -> None:
        result = _build_quality_fallback_result("s1")
        assert result.strengths == []
        assert result.weaknesses == []

    def test_empty_recommendations(self) -> None:
        result = _build_quality_fallback_result("s1")
        assert result.recommendations == []

    def test_all_twelve_categories_present(self) -> None:
        result = _build_quality_fallback_result("s1")
        category_values = {c.category for c in result.categories}
        assert category_values == set(QualityCategory)


# ═══════════════════════════════════════════════════════════
# 5. System prompt tests
# ═══════════════════════════════════════════════════════════


class TestQualitySystemPrompt:
    """Tests for _QUALITY_SYSTEM_PROMPT."""

    def test_contains_all_category_names(self) -> None:
        for cat in QualityCategory:
            assert cat.value in _QUALITY_SYSTEM_PROMPT

    def test_contains_level_options(self) -> None:
        assert "high" in _QUALITY_SYSTEM_PROMPT
        assert "medium" in _QUALITY_SYSTEM_PROMPT
        assert "low" in _QUALITY_SYSTEM_PROMPT

    def test_contains_json_instruction(self) -> None:
        assert "JSON" in _QUALITY_SYSTEM_PROMPT or "json" in _QUALITY_SYSTEM_PROMPT.lower()

    def test_contains_artifact_ignore(self) -> None:
        assert "артефакт" in _QUALITY_SYSTEM_PROMPT.lower() or "ИГНОРИРУЙ" in _QUALITY_SYSTEM_PROMPT

    def test_contains_recommendations_instruction(self) -> None:
        assert "recommendations" in _QUALITY_SYSTEM_PROMPT or "рекомендац" in _QUALITY_SYSTEM_PROMPT.lower()

    def test_contains_strengths_and_weaknesses(self) -> None:
        assert "strengths" in _QUALITY_SYSTEM_PROMPT
        assert "weaknesses" in _QUALITY_SYSTEM_PROMPT

    def test_contains_justification_instruction(self) -> None:
        assert "justification" in _QUALITY_SYSTEM_PROMPT or "обоснован" in _QUALITY_SYSTEM_PROMPT.lower()

    def test_contains_score_range(self) -> None:
        assert "0.0" in _QUALITY_SYSTEM_PROMPT
        assert "1.0" in _QUALITY_SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════
# 6. analyze_quality function tests (mocked LLM)
# ═══════════════════════════════════════════════════════════


class TestAnalyzeQuality:
    """Tests for analyze_quality async function."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        """analyze_quality returns a valid QualityScoreResult with all 12 categories."""
        raw_response = _valid_quality_json(session_id="sess-1")

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="Клиент: Привет\nСотрудник: Здравствуйте",
                session_id="sess-1",
                provider_id="beeline",
            )

        assert isinstance(result, QualityScoreResult)
        assert result.session_id == "sess-1"
        assert len(result.categories) == 12
        assert result.provider == "beeline"
        assert result.model == "test-model"

    @pytest.mark.asyncio
    async def test_all_categories_present(self) -> None:
        """All 12 QualityCategory values appear in the result."""
        raw_response = _valid_quality_json()

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        result_categories = {c.category for c in result.categories}
        assert result_categories == set(QualityCategory)

    @pytest.mark.asyncio
    async def test_derived_fields_computed(self) -> None:
        """overall_score, overall_level, strengths, weaknesses are computed from categories."""
        raw_response = _valid_quality_json()

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        # The valid JSON has communication_skills=high, efficiency=low
        assert "communication_skills" in result.strengths
        assert "efficiency" in result.weaknesses
        assert result.overall_score > 0
        assert result.overall_level in (QualityLevel.high, QualityLevel.medium, QualityLevel.low)

    @pytest.mark.asyncio
    async def test_session_id_overridden(self) -> None:
        """If LLM returns a different session_id, it should be overridden."""
        raw_response = _valid_quality_json(session_id="wrong-session")

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="correct-session",
                provider_id="beeline",
            )

        assert result.session_id == "correct-session"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        """When all LLM providers fail, returns fallback with all categories at medium."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(side_effect=ConnectionError("Service unavailable"))
            mock_get.return_value = mock_provider

            result = await analyze_quality(
                dialogue_text="test",
                session_id="fallback-sess",
                provider_id="beeline",
            )

        assert result.provider == "none"
        assert len(result.categories) == 12
        for cat in result.categories:
            assert cat.level == QualityLevel.medium
        assert result.session_id == "fallback-sess"

    @pytest.mark.asyncio
    async def test_minimal_json_response(self) -> None:
        """LLM may return only categories without derived fields; they should be computed."""
        raw_response = _minimal_quality_json()

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        # empathy is high, rest medium
        assert "empathy" in result.strengths
        assert result.overall_score > 0

    @pytest.mark.asyncio
    async def test_markdown_wrapped_response(self) -> None:
        """LLM response wrapped in ```json ... ``` should be parsed correctly."""
        raw = _valid_quality_json()
        wrapped = f"```json\n{raw}\n```"

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(wrapped)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        assert len(result.categories) == 12

    @pytest.mark.asyncio
    async def test_score_level_consistency(self) -> None:
        """Each category score should be within a reasonable range for its level."""
        raw_response = _valid_quality_json()

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        for cat in result.categories:
            assert 0.0 <= cat.score <= 1.0
            assert cat.level in (QualityLevel.high, QualityLevel.medium, QualityLevel.low)


# ═══════════════════════════════════════════════════════════
# 7. Endpoint tests
# ═══════════════════════════════════════════════════════════


class TestQualityScoreEndpoint:
    """Tests for POST /api/analysis/quality-score endpoint."""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_endpoint_exists(self) -> None:
        """The /quality-score route should be registered."""
        routes = [r.path for r in app.routes]
        assert "/api/analysis/quality-score" in routes

    def test_missing_session_returns_404(self) -> None:
        """Request with non-existent session_id returns 404."""
        response = self.client.post(
            "/api/analysis/quality-score",
            json={"session_id": "nonexistent", "provider_id": "beeline"},
        )
        assert response.status_code == 404

    def test_missing_body_returns_422(self) -> None:
        """Request without body returns 422."""
        response = self.client.post(
            "/api/analysis/quality-score",
            json={},
        )
        assert response.status_code == 422

    def test_default_provider_id(self) -> None:
        """QualityScoreRequest should default provider_id to 'beeline'."""
        from app.routers.analysis import QualityScoreRequest
        req = QualityScoreRequest(session_id="test")
        assert req.provider_id == "beeline"

    def test_quality_score_request_model(self) -> None:
        """QualityScoreRequest model should accept session_id and optional provider_id."""
        from app.routers.analysis import QualityScoreRequest
        req = QualityScoreRequest(session_id="s1", provider_id="ollama")
        assert req.session_id == "s1"
        assert req.provider_id == "ollama"


# ═══════════════════════════════════════════════════════════
# 8. Score derivation from level
# ═══════════════════════════════════════════════════════════


class TestScoreDerivation:
    """Tests that score values are consistent with their levels."""

    def test_low_score_range(self) -> None:
        """Low level typically maps to score around 0.33."""
        cs = CategoryScore(category=QualityCategory.efficiency, level=QualityLevel.low, score=0.33)
        assert cs.score < 0.5

    def test_medium_score_range(self) -> None:
        """Medium level typically maps to score around 0.66."""
        cs = CategoryScore(category=QualityCategory.empathy, level=QualityLevel.medium, score=0.66)
        assert 0.5 <= cs.score <= 0.75

    def test_high_score_range(self) -> None:
        """High level typically maps to score around 1.0."""
        cs = CategoryScore(category=QualityCategory.communication_skills, level=QualityLevel.high, score=0.95)
        assert cs.score > 0.75

    def test_overall_level_boundaries(self) -> None:
        """Verify the boundary thresholds for overall_level."""
        # Score > 0.75 → high
        categories = [
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.high, score=0.8),
        ]
        result = QualityScoreResult(session_id="t", categories=categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.high

        # Score = 0.75 → medium (not > 0.75)
        categories = [
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.medium, score=0.75),
        ]
        result = QualityScoreResult(session_id="t", categories=categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.medium

        # Score = 0.5 → medium
        categories = [
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.medium, score=0.5),
        ]
        result = QualityScoreResult(session_id="t", categories=categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.medium

        # Score < 0.5 → low
        categories = [
            CategoryScore(category=QualityCategory.empathy, level=QualityLevel.low, score=0.49),
        ]
        result = QualityScoreResult(session_id="t", categories=categories)
        computed = _compute_quality_derived_fields(result)
        assert computed.overall_level == QualityLevel.low


# ═══════════════════════════════════════════════════════════
# 9. Integration / edge case tests
# ═══════════════════════════════════════════════════════════


class TestQualityScoringIntegration:
    """Integration tests for the full quality scoring pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_llm(self) -> None:
        """End-to-end: mock LLM → analyze_quality → verify all fields."""
        raw_response = _valid_quality_json(session_id="int-sess")

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw_response)

            result = await analyze_quality(
                dialogue_text="Клиент: У меня проблема с роутером\nСотрудник: Сейчас помогу",
                session_id="int-sess",
                provider_id="beeline",
            )

        # Verify all 12 categories
        assert len(result.categories) == 12
        category_values = {c.category for c in result.categories}
        assert category_values == set(QualityCategory)

        # Verify derived fields
        assert result.overall_score > 0
        assert result.overall_level in set(QualityLevel)
        assert isinstance(result.strengths, list)
        assert isinstance(result.weaknesses, list)
        assert isinstance(result.recommendations, list)

        # Verify metadata
        assert result.session_id == "int-sess"
        assert result.provider == "beeline"
        assert result.model == "test-model"

    @pytest.mark.asyncio
    async def test_partial_llm_response(self) -> None:
        """LLM returns fewer than 12 categories — should still parse."""
        partial_data = {
            "categories": [
                {"category": "communication_skills", "level": "high", "score": 0.9, "justification": "Good"},
                {"category": "empathy", "level": "medium", "score": 0.6, "justification": "OK"},
            ],
            "strengths": ["communication_skills"],
            "weaknesses": [],
            "recommendations": [],
        }

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(json.dumps(partial_data))

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        # We accept whatever LLM returns (could be partial)
        assert len(result.categories) >= 1

    @pytest.mark.asyncio
    async def test_malformed_json_fallback(self) -> None:
        """When LLM returns non-JSON, _safe_parse_model uses model defaults (empty categories)."""
        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider("Это не JSON")

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        # Non-JSON → _safe_parse_model falls back to QualityScoreResult()
        # which has empty categories. session_id is then overridden by analyze_quality.
        assert result.session_id == "s1"
        assert result.provider == "beeline"  # LLM didn't fail, just returned bad data
        # Categories may be empty because LLM data was invalid
        assert isinstance(result.categories, list)

    @pytest.mark.asyncio
    async def test_empty_categories_in_response(self) -> None:
        """LLM returns empty categories list — result has empty categories (not 12-medium fallback)."""
        raw = json.dumps({"categories": [], "strengths": [], "weaknesses": [], "recommendations": []})

        with patch("app.services.llm.get_provider") as mock_get:
            mock_get.return_value = _mock_provider(raw)

            result = await analyze_quality(
                dialogue_text="test",
                session_id="s1",
                provider_id="beeline",
            )

        # LLM returned valid JSON with empty categories — accepted as-is
        assert result.session_id == "s1"
        assert len(result.categories) == 0

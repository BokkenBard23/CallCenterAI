"""Tests for PII Masking API router — endpoint-level tests with mocked PIIMaskingService.

Covers:
  - POST /mask: PII detection, no-PII text, empty/too-long input, custom entity_types,
    custom min_score, service unavailable (503), service error (503)
  - GET /status: available, unavailable, no-service, stats populated
  - Schema validation: PIIMaskResponse, PIIStatusResponse
  - Router structure: correct routes defined

HARDENED: strict_no_shortcuts=true. All tests must pass.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.middleware.rate_limiter import limiter
from app.models import (
    PIIDetection,
    PIIDetectionPublic,
    PIIEntityType,
    PIIMaskRequest,
    PIIMaskResponse,
    PIIMaskingConfig,
    PIIMaskingResult,
    PIIStatusResponse,
)
from app.routers.pii import router as pii_router


# ═══════════════════════════════════════════════════════════
# Test app factory
# ═══════════════════════════════════════════════════════════


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with PII router for testing."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(pii_router, prefix="/api/pii", tags=["pii"])
    return app


# ═══════════════════════════════════════════════════════════
# Mock helpers
# ═══════════════════════════════════════════════════════════


def _make_masking_result(
    masked_text: str = "Hello <PERSON>",
    detections: list[PIIDetection] | None = None,
    entity_counts: dict[str, int] | None = None,
    processing_time_ms: float = 12.5,
    masked: bool = False,
    error: str | None = None,
) -> PIIMaskingResult:
    """Create a PIIMaskingResult for mocking."""
    if detections is None:
        detections = []
    if entity_counts is None:
        entity_counts = {}
    return PIIMaskingResult(
        masked_text=masked_text,
        detections=detections,
        entity_counts=entity_counts,
        processing_time_ms=processing_time_ms,
        masked=masked,
        error=error,
    )


def _make_detection(
    entity_type: PIIEntityType = PIIEntityType.phone_number,
    start: int = 0,
    end: int = 12,
    text: str = "+79001234567",
    score: float = 0.85,
    recognizer: str = "RussianPhoneRecognizer",
) -> PIIDetection:
    """Create a PIIDetection for mocking."""
    return PIIDetection(
        entity_type=entity_type,
        start=start,
        end=end,
        text=text,
        score=score,
        recognizer=recognizer,
    )


def _make_available_service() -> MagicMock:
    """Create a mock PIIMaskingService that reports as available."""
    mock = MagicMock()
    mock.is_available.return_value = True
    mock.get_stats.return_value = {
        "total_masked": 42,
        "entity_counts": {"phone_number": 20, "person": 15, "email_address": 7},
        "avg_latency_ms": 15.3,
        "circuit_breaker_state": "closed",
        "available": True,
        "failure_count": 0,
        "masking_count": 42,
    }
    return mock


def _make_unavailable_service() -> MagicMock:
    """Create a mock PIIMaskingService that reports as unavailable."""
    mock = MagicMock()
    mock.is_available.return_value = False
    mock.get_stats.return_value = {
        "total_masked": 0,
        "entity_counts": {},
        "avg_latency_ms": 0.0,
        "circuit_breaker_state": "open",
        "available": False,
        "failure_count": 3,
        "masking_count": 0,
    }
    return mock


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture()
def client():
    """Create a TestClient with available PII masking service."""
    limiter.reset()
    app = _create_test_app()

    mock_service = _make_available_service()
    # Default: mask_text returns a clean result (no PII detected)
    mock_service.mask_text.return_value = _make_masking_result(
        masked_text="Текст без PII",
    )

    with TestClient(app) as test_client:
        app.state.pii_masking_service = mock_service
        yield test_client


@pytest.fixture()
def client_unavailable():
    """Create a TestClient with unavailable PII masking service."""
    limiter.reset()
    app = _create_test_app()

    mock_service = _make_unavailable_service()

    with TestClient(app) as test_client:
        app.state.pii_masking_service = mock_service
        yield test_client


@pytest.fixture()
def client_no_service():
    """Create a TestClient without PII masking service on app.state."""
    limiter.reset()
    app = _create_test_app()

    with TestClient(app) as test_client:
        # Explicitly ensure no pii_masking_service on app.state
        if hasattr(app.state, "pii_masking_service"):
            delattr(app.state, "pii_masking_service")
        yield test_client


# ═══════════════════════════════════════════════════════════
# Router structure tests
# ═══════════════════════════════════════════════════════════


class TestRouterStructure:
    """Tests for router definition and route paths."""

    def test_router_exists(self) -> None:
        """PII router must be defined."""
        from app.routers.pii import router
        assert router is not None

    def test_router_has_two_routes(self) -> None:
        """PII router must have /mask and /status routes."""
        from app.routers.pii import router
        paths = [r.path for r in router.routes]
        assert "/mask" in paths, f"Expected /mask in routes, got: {paths}"
        assert "/status" in paths, f"Expected /status in routes, got: {paths}"

    def test_router_mask_is_post(self) -> None:
        """Mask endpoint must use POST method."""
        from app.routers.pii import router
        for route in router.routes:
            if route.path == "/mask":
                assert "POST" in route.methods, f"Expected POST for /mask, got: {route.methods}"
                break
        else:
            pytest.fail("/mask route not found in router")

    def test_router_status_is_get(self) -> None:
        """Status endpoint must use GET method."""
        from app.routers.pii import router
        for route in router.routes:
            if route.path == "/status":
                assert "GET" in route.methods, f"Expected GET for /status, got: {route.methods}"
                break
        else:
            pytest.fail("/status route not found in router")


# ═══════════════════════════════════════════════════════════
# POST /mask tests
# ═══════════════════════════════════════════════════════════


class TestMaskEndpoint:
    """Tests for POST /api/pii/mask endpoint."""

    def test_post_pii_mask_with_pii(self, client: TestClient) -> None:
        """Text with PII → masked_text + detections."""
        detection = _make_detection(
            entity_type=PIIEntityType.phone_number,
            start=7,
            end=20,
            text="+79001234567",
            score=0.85,
        )
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Звоните <PHONE> сегодня",
            detections=[detection],
            entity_counts={"phone_number": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Звоните +79001234567 сегодня"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["masked_text"] == "Звоните <PHONE> сегодня"
        assert len(data["detections"]) == 1
        assert data["detections"][0]["entity_type"] == "phone_number"
        assert data["entity_counts"]["phone_number"] == 1

    def test_post_pii_mask_no_pii(self, client: TestClient) -> None:
        """Text without PII → same text returned, empty detections."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Обычный текст без PII",
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Обычный текст без PII"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["masked_text"] == "Обычный текст без PII"
        assert data["detections"] == []
        assert data["entity_counts"] == {}

    def test_post_pii_mask_empty_text(self, client: TestClient) -> None:
        """Empty text → 422 (min_length=1)."""
        response = client.post(
            "/api/pii/mask",
            json={"text": ""},
        )
        assert response.status_code == 422

    def test_post_pii_mask_too_long_text(self, client: TestClient) -> None:
        """Text exceeding max_length → 422 (max_length=50000)."""
        response = client.post(
            "/api/pii/mask",
            json={"text": "x" * 50001},
        )
        assert response.status_code == 422

    def test_post_pii_mask_specific_entity_types(self, client: TestClient) -> None:
        """Specific entity_types=[phone_number] → only phone masked."""
        detection = _make_detection(
            entity_type=PIIEntityType.phone_number,
            start=7,
            end=20,
            text="+79001234567",
        )
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Иван <PHONE>",
            detections=[detection],
            entity_counts={"phone_number": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={
                "text": "Иван +79001234567",
                "entity_types": ["phone_number"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["masked_text"] == "Иван <PHONE>"

        # Verify config was passed to mask_text with specific entity types
        call_args = mock_service.mask_text.call_args
        config = call_args[1].get("config") if "config" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else None
        assert config is not None
        assert any(et == PIIEntityType.phone_number for et in config.entity_types)

    def test_post_pii_mask_custom_min_score(self, client: TestClient) -> None:
        """min_score=0.8 → only high-confidence detections."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Мой телефон <PHONE>",
            detections=[_make_detection(score=0.9)],
            entity_counts={"phone_number": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Мой телефон +79001234567", "min_score": 0.8},
        )
        assert response.status_code == 200

        # Verify config was passed with min_score=0.8
        call_args = mock_service.mask_text.call_args
        config = call_args[1].get("config") if "config" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else None
        assert config is not None
        assert config.min_score == 0.8

    def test_post_pii_mask_default_entity_types(self, client: TestClient) -> None:
        """No entity_types specified → no PIIMaskingConfig passed (service uses defaults)."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Текст",
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст"},
        )
        assert response.status_code == 200

        # Verify mask_text was called without config (None)
        call_args = mock_service.mask_text.call_args
        config = call_args[1].get("config") if "config" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else None
        assert config is None, "Expected no config when using defaults"

    def test_post_pii_mask_default_min_score(self, client: TestClient) -> None:
        """Default min_score=0.5 → no PIIMaskingConfig passed (service uses defaults)."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Текст",
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст", "min_score": 0.5},
        )
        assert response.status_code == 200

        # min_score 0.5 is the default → no config
        call_args = mock_service.mask_text.call_args
        config = call_args[1].get("config") if "config" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else None
        assert config is None, "Expected no config when min_score is default 0.5"

    def test_post_pii_mask_multiple_detections(self, client: TestClient) -> None:
        """Multiple PII entities detected → all returned."""
        detections = [
            _make_detection(
                entity_type=PIIEntityType.person,
                start=0,
                end=4,
                text="Иван",
                score=0.9,
                recognizer="SpacyRecognizer",
            ),
            _make_detection(
                entity_type=PIIEntityType.phone_number,
                start=5,
                end=18,
                text="+79001234567",
                score=0.85,
                recognizer="RussianPhoneRecognizer",
            ),
            _make_detection(
                entity_type=PIIEntityType.email_address,
                start=22,
                end=36,
                text="ivan@mail.ru",
                score=0.95,
                recognizer="EmailRecognizer",
            ),
        ]
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="<PERSON> <PHONE> <EMAIL>",
            detections=detections,
            entity_counts={"person": 1, "phone_number": 1, "email_address": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Иван +79001234567 ivan@mail.ru"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["detections"]) == 3
        assert data["entity_counts"]["person"] == 1
        assert data["entity_counts"]["phone_number"] == 1
        assert data["entity_counts"]["email_address"] == 1

    def test_post_pii_mask_service_unavailable(self, client_unavailable: TestClient) -> None:
        """Service unavailable → 503."""
        response = client_unavailable.post(
            "/api/pii/mask",
            json={"text": "Текст"},
        )
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower() or "compliance" in response.json()["detail"].lower()

    def test_post_pii_mask_service_error(self, client: TestClient) -> None:
        """mask_text returns error → 503."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="",
            error="PII masking unavailable, processing blocked for compliance (152-FZ)",
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст"},
        )
        assert response.status_code == 503
        # M-1: Error response must NOT contain PII context — only generic compliance message
        assert "compliance" in response.json()["detail"].lower()

    def test_post_pii_mask_returns_processing_time(self, client: TestClient) -> None:
        """Response must include processing_time_ms."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Текст",
            processing_time_ms=23.7,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "processing_time_ms" in data
        assert data["processing_time_ms"] == 23.7

    def test_post_pii_mask_invalid_min_score(self, client: TestClient) -> None:
        """min_score outside [0.0, 1.0] → 422."""
        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст", "min_score": 1.5},
        )
        assert response.status_code == 422

    def test_post_pii_mask_invalid_entity_type(self, client: TestClient) -> None:
        """Invalid entity_type string → 422."""
        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст", "entity_types": ["nonexistent_type"]},
        )
        assert response.status_code == 422

    def test_post_pii_mask_entity_types_creates_config(self, client: TestClient) -> None:
        """When entity_types is provided, PIIMaskingConfig must be created with all types."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Текст",
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Текст", "entity_types": ["person", "phone_number"]},
        )
        assert response.status_code == 200

        call_args = mock_service.mask_text.call_args
        config = call_args[1].get("config") if "config" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else None
        assert config is not None
        entity_type_values = [et.value for et in config.entity_types]
        assert "person" in entity_type_values
        assert "phone_number" in entity_type_values


# ═══════════════════════════════════════════════════════════
# GET /status tests
# ═══════════════════════════════════════════════════════════


class TestStatusEndpoint:
    """Tests for GET /api/pii/status endpoint."""

    def test_get_pii_status_available(self, client: TestClient) -> None:
        """Available service → returns available=True + stats."""
        response = client.get("/api/pii/status")
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["circuit_breaker_state"] == "closed"
        assert data["total_masked"] == 42
        assert "phone_number" in data["entity_counts"]
        assert data["avg_latency_ms"] == 15.3

    def test_get_pii_status_unavailable(self, client_unavailable: TestClient) -> None:
        """Unavailable service → available=False, circuit breaker open."""
        response = client_unavailable.get("/api/pii/status")
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is False
        assert data["circuit_breaker_state"] == "open"

    def test_get_pii_status_no_service(self, client_no_service: TestClient) -> None:
        """No pii_masking_service on app.state → available=False with defaults."""
        response = client_no_service.get("/api/pii/status")
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is False
        assert data["circuit_breaker_state"] == "unknown"
        assert data["total_masked"] == 0
        assert data["entity_counts"] == {}
        assert data["avg_latency_ms"] == 0.0
        assert data["language"] == "ru"
        assert data["recognizers"] == []

    def test_get_pii_status_with_stats(self, client: TestClient) -> None:
        """Stats from service are reflected in response."""
        mock_service = client.app.state.pii_masking_service
        mock_service.get_stats.return_value = {
            "total_masked": 100,
            "entity_counts": {"person": 50, "email_address": 30, "phone_number": 20},
            "avg_latency_ms": 25.5,
            "circuit_breaker_state": "closed",
            "available": True,
            "failure_count": 0,
            "masking_count": 100,
        }

        response = client.get("/api/pii/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_masked"] == 100
        assert data["entity_counts"]["person"] == 50
        assert data["avg_latency_ms"] == 25.5

    def test_get_pii_status_circuit_breaker_half_open(self, client: TestClient) -> None:
        """Circuit breaker in half_open state is reported correctly."""
        mock_service = client.app.state.pii_masking_service
        mock_service.is_available.return_value = True
        mock_service.get_stats.return_value = {
            "total_masked": 5,
            "entity_counts": {},
            "avg_latency_ms": 10.0,
            "circuit_breaker_state": "half_open",
            "available": True,
            "failure_count": 1,
            "masking_count": 5,
        }

        response = client.get("/api/pii/status")
        assert response.status_code == 200
        data = response.json()
        assert data["circuit_breaker_state"] == "half_open"


# ═══════════════════════════════════════════════════════════
# Schema validation tests
# ═══════════════════════════════════════════════════════════


class TestSchemaValidation:
    """Tests for response schema correctness."""

    def test_mask_response_schema(self, client: TestClient) -> None:
        """PIIMaskResponse must have all required fields."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Тест",
            detections=[],
            entity_counts={},
            processing_time_ms=5.0,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Тест"},
        )
        assert response.status_code == 200
        data = response.json()

        # Verify all PIIMaskResponse fields present
        required_fields = {"masked_text", "detections", "entity_counts", "processing_time_ms"}
        assert required_fields.issubset(set(data.keys())), (
            f"Missing fields: {required_fields - set(data.keys())}"
        )
        # Verify types
        assert isinstance(data["masked_text"], str)
        assert isinstance(data["detections"], list)
        assert isinstance(data["entity_counts"], dict)
        assert isinstance(data["processing_time_ms"], (int, float))

    def test_status_response_schema(self, client: TestClient) -> None:
        """PIIStatusResponse must have all required fields."""
        response = client.get("/api/pii/status")
        assert response.status_code == 200
        data = response.json()

        # Verify all PIIStatusResponse fields present
        required_fields = {
            "available", "circuit_breaker_state", "total_masked",
            "entity_counts", "avg_latency_ms", "language", "recognizers",
        }
        assert required_fields.issubset(set(data.keys())), (
            f"Missing fields: {required_fields - set(data.keys())}"
        )
        # Verify types
        assert isinstance(data["available"], bool)
        assert isinstance(data["circuit_breaker_state"], str)
        assert isinstance(data["total_masked"], int)
        assert isinstance(data["entity_counts"], dict)
        assert isinstance(data["avg_latency_ms"], (int, float))
        assert isinstance(data["language"], str)
        assert isinstance(data["recognizers"], list)

    def test_detection_schema_in_mask_response(self, client: TestClient) -> None:
        """Each detection in PIIMaskResponse must have correct fields (no raw PII)."""
        detection = _make_detection(
            entity_type=PIIEntityType.phone_number,
            start=0,
            end=12,
            text="+79001234567",
            score=0.85,
            recognizer="RussianPhoneRecognizer",
        )
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="<PHONE>",
            detections=[detection],
            entity_counts={"phone_number": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "+79001234567"},
        )
        assert response.status_code == 200
        det = response.json()["detections"][0]

        # PIIDetectionPublic fields (no "text" field — 152-FZ compliance)
        required_fields = {"entity_type", "start", "end", "score", "recognizer"}
        assert required_fields.issubset(set(det.keys())), (
            f"Missing detection fields: {required_fields - set(det.keys())}"
        )
        assert isinstance(det["start"], int)
        assert isinstance(det["end"], int)
        assert isinstance(det["score"], (int, float))

        # CRITICAL: "text" field must NOT be present in API response
        assert "text" not in det, (
            "PIIDetectionPublic must NOT contain 'text' field — "
            "raw PII must not be leaked via API (152-FZ compliance)"
        )


# ═══════════════════════════════════════════════════════════
# PII Leak Prevention Tests (152-FZ Compliance)
# ═══════════════════════════════════════════════════════════


class TestPIILeakPrevention:
    """Tests verifying that raw PII is never leaked via API responses.

    These tests enforce 152-FZ compliance:
    - C-1: PIIDetectionPublic must not contain raw PII text
    - C-2: PIIMaskResponse must not contain original_text
    - M-1: Error responses must use generic messages (no PII context)
    """

    def test_pii_mask_response_no_raw_pii_in_detections(self, client: TestClient) -> None:
        """POST /mask response detections must NOT contain raw PII text (C-1)."""
        detection = _make_detection(
            entity_type=PIIEntityType.phone_number,
            start=7,
            end=20,
            text="+79001234567",
            score=0.85,
        )
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="Звоните <PHONE> сегодня",
            detections=[detection],
            entity_counts={"phone_number": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Звоните +79001234567 сегодня"},
        )
        assert response.status_code == 200
        data = response.json()

        # Verify detections exist
        assert len(data["detections"]) == 1
        det = data["detections"][0]

        # CRITICAL: "text" field must NOT be present — raw PII must not leak
        assert "text" not in det, (
            f"API response detection contains 'text' field with raw PII! "
            f"Detection keys: {list(det.keys())}. This violates 152-FZ."
        )

        # Verify expected fields are present
        assert "entity_type" in det
        assert "start" in det
        assert "end" in det
        assert "score" in det
        assert "recognizer" in det

    def test_pii_mask_response_no_original_text(self, client: TestClient) -> None:
        """POST /mask response must NOT contain original_text field (C-2)."""
        mock_service = client.app.state.pii_masking_service
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="<PERSON> позвонил",
            detections=[_make_detection(entity_type=PIIEntityType.person)],
            entity_counts={"person": 1},
            masked=True,
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Иван позвонил"},
        )
        assert response.status_code == 200
        data = response.json()

        # CRITICAL: "original_text" must NOT be in response
        assert "original_text" not in data, (
            f"API response contains 'original_text' field! "
            f"Keys: {list(data.keys())}. This violates 152-FZ."
        )

    def test_pii_mask_error_no_pii_context(self, client: TestClient) -> None:
        """POST /mask error response must use generic message — no PII context (M-1)."""
        mock_service = client.app.state.pii_masking_service
        # Simulate an error that might contain PII context
        mock_service.mask_text.return_value = _make_masking_result(
            masked_text="",
            error="PII masking failed: RuntimeError('Error processing Иван Иванов on turn 0')",
        )

        response = client.post(
            "/api/pii/mask",
            json={"text": "Иван Иванов позвонил"},
        )
        assert response.status_code == 503
        detail = response.json()["detail"]

        # Error detail must NOT contain any PII context
        assert "Иван" not in detail, (
            f"Error detail contains PII name! Detail: {detail}"
        )
        assert "turn" not in detail.lower(), (
            f"Error detail contains processing context! Detail: {detail}"
        )
        # Must use generic compliance message
        assert "compliance" in detail.lower() or "unavailable" in detail.lower()

    def test_pii_detection_public_model_no_text_field(self) -> None:
        """PIIDetectionPublic model must NOT have a 'text' field."""
        public_det = PIIDetectionPublic(
            entity_type=PIIEntityType.phone_number,
            start=0,
            end=12,
            score=0.85,
            recognizer="RussianPhoneRecognizer",
        )
        # Model should not have 'text' attribute
        assert not hasattr(public_det, "text"), (
            "PIIDetectionPublic must not have 'text' field — "
            "it would contain raw PII and violate 152-FZ"
        )

    def test_pii_masking_result_no_original_text(self) -> None:
        """PIIMaskingResult must NOT have original_text field (C-2)."""
        result = PIIMaskingResult(
            masked_text="<PERSON> test",
            masked=True,
        )
        assert not hasattr(result, "original_text"), (
            "PIIMaskingResult must not have 'original_text' field — "
            "it would store raw PII in memory and risk leaking via debug/serialization"
        )

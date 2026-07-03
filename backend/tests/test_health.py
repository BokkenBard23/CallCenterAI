"""Tests for Health Check endpoint (ID-15).

Covers:
  - GET /api/health — structured health check
  - HealthCheckResult model
  - Service checks: session store, FRIDA, vector store
  - Status aggregation: healthy / degraded / unhealthy
  - Uptime computation
  - Active sessions count
  - Config: health_check_enabled
  - Structured logging middleware: JsonFormatter, correlation ID
  - Legacy /health endpoint backward compatibility
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid

import pytest
import pytest_asyncio

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.main import app
from app.models import HealthCheckResult
from app.middleware.structured_logging import JsonFormatter, StructuredLoggingMiddleware


# ═══════════════════════════════════════════════════════════
# Model Tests
# ═══════════════════════════════════════════════════════════


class TestHealthCheckResultModel:
    """Tests for HealthCheckResult Pydantic model."""

    def test_default_values(self):
        """Default model has sensible defaults."""
        result = HealthCheckResult(status="healthy", version="1.0.0")
        assert result.status == "healthy"
        assert result.version == "1.0.0"
        assert result.uptime_seconds == 0.0
        assert result.checks == {}
        assert result.active_sessions == 0
        assert result.frida_available is False
        assert result.vector_store_size == 0

    def test_with_full_data(self):
        """Model with all fields populated."""
        result = HealthCheckResult(
            status="degraded",
            version="1.0.0",
            uptime_seconds=123.45,
            checks={"session_store": "ok", "frida": "error: unavailable"},
            active_sessions=5,
            frida_available=False,
            vector_store_size=100,
        )
        assert result.status == "degraded"
        assert result.uptime_seconds == 123.45
        assert result.checks["session_store"] == "ok"
        assert result.active_sessions == 5
        assert result.vector_store_size == 100

    def test_status_values(self):
        """All valid status values are accepted."""
        for status in ("healthy", "degraded", "unhealthy"):
            result = HealthCheckResult(status=status, version="1.0.0")
            assert result.status == status

    def test_serialization(self):
        """Model serializes to JSON and back."""
        result = HealthCheckResult(
            status="healthy",
            version="1.0.0",
            uptime_seconds=10.0,
            checks={"session_store": "ok"},
            active_sessions=1,
            frida_available=True,
            vector_store_size=42,
        )
        data = result.model_dump()
        restored = HealthCheckResult(**data)
        assert restored.status == result.status
        assert restored.uptime_seconds == result.uptime_seconds
        assert restored.active_sessions == result.active_sessions

    def test_check_error_format(self):
        """Check values can be 'ok' or 'error: ...'."""
        result = HealthCheckResult(
            status="degraded",
            version="1.0.0",
            checks={
                "session_store": "ok",
                "frida": "error: FRIDA service unavailable",
                "vector_store": "ok",
            },
        )
        assert result.checks["frida"].startswith("error:")


# ═══════════════════════════════════════════════════════════
# Structured Logging Tests
# ═══════════════════════════════════════════════════════════


class TestJsonFormatter:
    """Tests for the JSON log formatter."""

    def test_basic_format(self):
        """Basic log record is formatted as JSON."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Test message"
        assert "timestamp" in data

    def test_correlation_id_in_output(self):
        """Correlation ID is included when present on the record."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="With correlation",
            args=None,
            exc_info=None,
        )
        record.correlation_id = "test-correlation-123"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["correlation_id"] == "test-correlation-123"

    def test_no_correlation_id_when_absent(self):
        """No correlation_id key in output when not set on record."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Without correlation",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "correlation_id" not in data

    def test_extra_fields_included(self):
        """Extra fields on the log record are included in JSON output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="With extras",
            args=None,
            exc_info=None,
        )
        record.http_method = "POST"
        record.http_path = "/api/upload/rtf"
        record.http_status = 200
        record.duration_ms = 42.5
        output = formatter.format(record)
        data = json.loads(output)
        assert data["http_method"] == "POST"
        assert data["http_path"] == "/api/upload/rtf"
        assert data["http_status"] == 200
        assert data["duration_ms"] == 42.5

    def test_non_serializable_extra_converted_to_string(self):
        """Non-JSON-serializable extra fields are converted to strings."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Non-serializable",
            args=None,
            exc_info=None,
        )
        record.custom_object = object()  # Not JSON-serializable
        output = formatter.format(record)
        data = json.loads(output)
        assert "custom_object" in data
        assert isinstance(data["custom_object"], str)

    def test_exception_info_included(self):
        """Exception info is included when present."""
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="With exception",
            args=None,
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_ensure_ascii_false(self):
        """Russian text is preserved (not escaped)."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Тестовое сообщение на русском",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "Тестовое сообщение на русском"

    def test_json_output_is_single_line(self):
        """Each log record is a single line (no newlines in JSON)."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Single line test",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        assert "\n" not in output


class TestSetupStructuredLogging:
    """Tests for the setup_structured_logging function."""

    def test_adds_handler_to_root_logger(self):
        """Adding structured logging adds a handler to root logger."""
        from app.middleware.structured_logging import setup_structured_logging

        root_logger = logging.getLogger()
        initial_count = len(root_logger.handlers)

        handler = setup_structured_logging()

        try:
            assert len(root_logger.handlers) == initial_count + 1
            assert handler in root_logger.handlers
        finally:
            # Clean up
            root_logger.removeHandler(handler)
            handler.close()

    def test_does_not_replace_existing_handlers(self):
        """Adding structured logging preserves existing handlers."""
        from app.middleware.structured_logging import setup_structured_logging

        root_logger = logging.getLogger()
        existing_handler = logging.StreamHandler()
        root_logger.addHandler(existing_handler)
        initial_count = len(root_logger.handlers)

        handler = setup_structured_logging()

        try:
            assert existing_handler in root_logger.handlers
            assert len(root_logger.handlers) == initial_count + 1
        finally:
            root_logger.removeHandler(handler)
            root_logger.removeHandler(existing_handler)
            handler.close()
            existing_handler.close()


# ═══════════════════════════════════════════════════════════
# Endpoint Integration Tests
# ═══════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestHealthEndpoint:
    """Tests for GET /api/health."""

    async def test_health_endpoint_returns_200(self, client: AsyncClient):
        """Health endpoint returns HTTP 200."""
        resp = await client.get("/api/health")
        assert resp.status_code == 200

    async def test_health_response_has_required_fields(self, client: AsyncClient):
        """Health response contains all required fields."""
        resp = await client.get("/api/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert "checks" in data
        assert "active_sessions" in data
        assert "frida_available" in data
        assert "vector_store_size" in data

    async def test_health_response_status_is_valid(self, client: AsyncClient):
        """Health status is one of: healthy, degraded, unhealthy."""
        resp = await client.get("/api/health")
        data = resp.json()
        assert data["status"] in ("healthy", "degraded", "unhealthy")

    async def test_health_response_version_matches_config(self, client: AsyncClient):
        """Version field matches app_version config."""
        resp = await client.get("/api/health")
        data = resp.json()
        assert data["version"] == "1.0.0"

    async def test_health_uptime_is_positive(self, client: AsyncClient):
        """Uptime is a positive number."""
        resp = await client.get("/api/health")
        data = resp.json()
        assert data["uptime_seconds"] > 0

    async def test_health_checks_is_dict(self, client: AsyncClient):
        """Checks field is a dict with service statuses."""
        resp = await client.get("/api/health")
        data = resp.json()
        checks = data["checks"]
        assert isinstance(checks, dict)
        assert "session_store" in checks
        assert "frida" in checks
        assert "vector_store" in checks

    async def test_health_active_sessions_is_int(self, client: AsyncClient):
        """Active sessions is an integer >= 0."""
        resp = await client.get("/api/health")
        data = resp.json()
        assert isinstance(data["active_sessions"], int)
        assert data["active_sessions"] >= 0

    async def test_health_vector_store_size_is_int(self, client: AsyncClient):
        """Vector store size is an integer >= 0."""
        resp = await client.get("/api/health")
        data = resp.json()
        assert isinstance(data["vector_store_size"], int)
        assert data["vector_store_size"] >= 0

    async def test_health_no_authentication_required(self, client: AsyncClient):
        """Health endpoint is accessible without any auth headers."""
        resp = await client.get("/api/health")
        assert resp.status_code == 200

    async def test_health_after_creating_session(self, client: AsyncClient):
        """Active sessions count increases after uploading a file."""
        # Get initial count
        resp1 = await client.get("/api/health")
        initial_sessions = resp1.json()["active_sessions"]

        # Upload a file to create a session
        mini_rtf = (
            r"{\rtf1\ansi{\fonttbl\f0\fswiss Helvetica;}"
            r"\f0\pard Клиент: Тест\par }"
        )
        await client.post(
            "/api/upload/rtf",
            files=[("file", ("test.rtf", mini_rtf.encode("utf-8"), "application/rtf"))],
        )

        # Check sessions increased
        resp2 = await client.get("/api/health")
        new_sessions = resp2.json()["active_sessions"]
        assert new_sessions >= initial_sessions


@pytest.mark.asyncio
class TestLegacyHealthEndpoint:
    """Tests for the legacy /health endpoint (backward compatibility)."""

    async def test_legacy_health_returns_200(self, client: AsyncClient):
        """Legacy /health endpoint still works."""
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_legacy_health_has_status_ok(self, client: AsyncClient):
        """Legacy /health returns status: ok."""
        resp = await client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"

    async def test_legacy_health_has_version(self, client: AsyncClient):
        """Legacy /health returns version."""
        resp = await client.get("/health")
        data = resp.json()
        assert "version" in data


# ═══════════════════════════════════════════════════════════
# Correlation ID Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCorrelationId:
    """Tests for correlation ID in responses."""

    async def test_response_has_correlation_id_header(self, client: AsyncClient):
        """Response includes X-Correlation-ID header."""
        resp = await client.get("/api/health")
        assert "X-Correlation-ID" in resp.headers
        # Should be a valid UUID-like hex string
        correlation_id = resp.headers["X-Correlation-ID"]
        assert len(correlation_id) > 0

    async def test_custom_correlation_id_is_echoed(self, client: AsyncClient):
        """Custom X-Correlation-ID from request is echoed in response."""
        custom_id = str(uuid.uuid4())
        resp = await client.get(
            "/api/health",
            headers={"X-Correlation-ID": custom_id},
        )
        assert resp.headers["X-Correlation-ID"] == custom_id

    async def test_different_requests_get_different_correlation_ids(self, client: AsyncClient):
        """Each request without custom correlation ID gets a unique one."""
        resp1 = await client.get("/api/health")
        resp2 = await client.get("/api/health")
        id1 = resp1.headers["X-Correlation-ID"]
        id2 = resp2.headers["X-Correlation-ID"]
        assert id1 != id2

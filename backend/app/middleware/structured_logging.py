"""Structured logging middleware — JSON-formatted request logging with correlation IDs.

Provides:
  - StructuredLoggingMiddleware: logs every request with method, path, status, duration
  - JSON formatter for Python logging
  - Correlation ID injection into each request

This middleware is opt-in: adding the handler does NOT replace existing
logging configuration. It adds a new handler that outputs JSON-formatted
log records alongside any existing handlers.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


# ═══════════════════════════════════════════════════════════
# JSON Log Formatter
# ═══════════════════════════════════════════════════════════


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Each record is emitted as a JSON object with standard fields:
      - timestamp: ISO 8601 formatted time
      - level: log level name
      - logger: logger name
      - message: formatted message
      - correlation_id: request correlation ID (if available)

    Extra fields on the log record are merged into the JSON object.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation ID if present
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            log_entry["correlation_id"] = correlation_id

        # Add any extra fields from the log record
        standard_attrs = {
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "pathname", "filename", "module", "thread", "threadName",
            "process", "processName", "levelname", "levelno", "message",
            "msecs", "taskName", "correlation_id",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                try:
                    json.dumps(value)  # Test JSON-serializability
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_structured_logging(level: int = logging.INFO) -> logging.StreamHandler:
    """Add a JSON-formatted logging handler to the root logger.

    This is opt-in: it adds a new handler without replacing existing ones.
    Returns the handler so callers can remove it later if needed.

    Args:
        level: Logging level for the new handler (default: INFO).

    Returns:
        The StreamHandler that was added to the root logger.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    return handler


# ═══════════════════════════════════════════════════════════
# Structured Logging Middleware
# ═══════════════════════════════════════════════════════════


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every HTTP request with structured data.

    For each request, logs:
      - HTTP method and path
      - Response status code
      - Request duration in milliseconds
      - Correlation ID (generated per request)

    Uses Python's standard logging with extra fields for JSON formatting.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process request, log structured data, and return response."""
        # Generate correlation ID
        correlation_id = request.headers.get(
            "X-Correlation-ID",
            uuid.uuid4().hex,
        )

        # Store correlation ID on request state for downstream use
        request.state.correlation_id = correlation_id

        # Record start time
        start_time = time.monotonic()

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Log structured request data
        logger = logging.getLogger("app.middleware.structured_logging")
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "correlation_id": correlation_id,
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else None,
            },
        )

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id

        return response

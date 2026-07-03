"""Tests for Batch RTF Upload endpoint (IP-2.1).

Covers:
  - POST /api/upload/rtf/batch — validation and processing
  - BatchUploadRtfResponse model
  - File count limits (1-10)
  - Per-file processing (independent failures)
  - Partial success (some files succeed, some fail)
  - Session creation and linking
  - Error aggregation
  - Edge cases: empty file list, oversized files, wrong extensions
"""

from __future__ import annotations

import io
import os
import sys

import pytest
import pytest_asyncio

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.main import app
from app.models import BatchUploadRtfResponse, UploadRtfResponse


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

MINI_RTF = (
    r"{\rtf1\ansi{\fonttbl\f0\fswiss Helvetica;}"
    r"\f0\pard Клиент: Здравствуйте\par "
    r"Сотрудник: Добрый день\par }"
)


def _rtf_file(filename: str = "test.rtf", content: bytes | None = None) -> tuple:
    """Create a file tuple for multipart upload."""
    if content is None:
        content = MINI_RTF.encode("utf-8")
    return ("files", (filename, content, "application/rtf"))


# ═══════════════════════════════════════════════════════════
# Model Tests
# ═══════════════════════════════════════════════════════════


class TestBatchUploadRtfResponseModel:
    """Tests for BatchUploadRtfResponse Pydantic model."""

    def test_default_values(self):
        """Default response has empty results, zero counts."""
        resp = BatchUploadRtfResponse()
        assert resp.results == []
        assert resp.total == 0
        assert resp.successful == 0
        assert resp.failed == 0
        assert resp.errors == []

    def test_with_results(self):
        """Response with results and counts."""
        r1 = UploadRtfResponse(session_id="abc", turn_count=2, raw_text_length=50)
        r2 = UploadRtfResponse(session_id="", error="Bad file")
        resp = BatchUploadRtfResponse(
            results=[r1, r2],
            total=2,
            successful=1,
            failed=1,
            errors=[{"filename": "bad.rtf", "error": "Bad file"}],
        )
        assert resp.total == 2
        assert resp.successful == 1
        assert resp.failed == 1
        assert len(resp.results) == 2
        assert resp.results[0].session_id == "abc"
        assert resp.results[1].error == "Bad file"

    def test_serialization(self):
        """Model serializes to JSON and back."""
        r1 = UploadRtfResponse(session_id="s1", turn_count=3, raw_text_length=100)
        resp = BatchUploadRtfResponse(
            results=[r1],
            total=1,
            successful=1,
            failed=0,
            errors=[],
        )
        data = resp.model_dump()
        restored = BatchUploadRtfResponse(**data)
        assert restored.total == 1
        assert restored.successful == 1
        assert restored.results[0].session_id == "s1"


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
class TestBatchUploadEndpoint:
    """Tests for POST /api/upload/rtf/batch."""

    async def test_batch_upload_single_file(self, client: AsyncClient):
        """Batch with 1 file succeeds."""
        files = [_rtf_file("single.rtf")]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["successful"] == 1
        assert data["failed"] == 0
        assert data["errors"] == []
        assert len(data["results"]) == 1
        assert data["results"][0]["session_id"] != ""

    async def test_batch_upload_multiple_files(self, client: AsyncClient):
        """Batch with 3 valid files all succeed."""
        files = [
            _rtf_file("file1.rtf"),
            _rtf_file("file2.rtf"),
            _rtf_file("file3.rtf"),
        ]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0
        # Each file gets its own session
        session_ids = [r["session_id"] for r in data["results"]]
        assert len(set(session_ids)) == 3  # All unique

    async def test_batch_upload_exceeds_limit(self, client: AsyncClient):
        """Batch with >10 files returns 400."""
        files = [_rtf_file(f"file{i}.rtf") for i in range(11)]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 400
        assert "10" in resp.json()["detail"]

    async def test_batch_upload_partial_success(self, client: AsyncClient):
        """Batch with 1 valid + 1 invalid extension → partial success."""
        files = [
            _rtf_file("good.rtf"),
            ("files", ("bad.txt", b"not rtf content", "text/plain")),
        ]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["successful"] == 1
        assert data["failed"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["filename"] == "bad.txt"

    async def test_batch_upload_all_invalid(self, client: AsyncClient):
        """Batch with all invalid files returns 200 with all failed."""
        files = [
            ("files", ("bad1.txt", b"not rtf", "text/plain")),
            ("files", ("bad2.pdf", b"not rtf", "application/pdf")),
        ]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["successful"] == 0
        assert data["failed"] == 2
        assert len(data["errors"]) == 2

    async def test_batch_upload_empty_file(self, client: AsyncClient):
        """Empty file in batch is recorded as error."""
        files = [
            _rtf_file("valid.rtf"),
            ("files", ("empty.rtf", b"", "application/rtf")),
        ]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["successful"] == 1
        assert data["failed"] == 1
        empty_error = [e for e in data["errors"] if e["filename"] == "empty.rtf"]
        assert len(empty_error) == 1
        assert "Empty file" in empty_error[0]["error"]

    async def test_batch_upload_invalid_session(self, client: AsyncClient):
        """Batch with non-existent session_id returns 404."""
        files = [_rtf_file("test.rtf")]
        resp = await client.post(
            "/api/upload/rtf/batch",
            files=files,
            data={"session_id": "nonexistent"},
        )
        assert resp.status_code == 404

    async def test_batch_upload_with_valid_session(self, client: AsyncClient):
        """Batch with valid session_id creates sessions linked to it."""
        # First, upload a file to create a session
        single_resp = await client.post(
            "/api/upload/rtf",
            files=[("file", ("init.rtf", MINI_RTF.encode("utf-8"), "application/rtf"))],
        )
        assert single_resp.status_code == 200
        session_id = single_resp.json()["session_id"]

        # Now batch upload with that session_id
        files = [_rtf_file("batch1.rtf")]
        resp = await client.post(
            "/api/upload/rtf/batch",
            files=files,
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["successful"] == 1
        assert data["results"][0]["session_id"] != ""

    async def test_batch_upload_results_order_matches_input(self, client: AsyncClient):
        """Results array order matches input file order."""
        files = [
            _rtf_file("alpha.rtf"),
            ("files", ("bad.txt", b"not rtf", "text/plain")),
            _rtf_file("gamma.rtf"),
        ]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["session_id"] != ""  # alpha succeeded
        assert data["results"][1]["error"] != ""  # bad.txt failed
        assert data["results"][2]["session_id"] != ""  # gamma succeeded

    async def test_batch_upload_error_contains_filename(self, client: AsyncClient):
        """Error entries contain the original filename."""
        files = [("files", ("specific_name.txt", b"bad", "text/plain"))]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["errors"][0]["filename"] == "specific_name.txt"

    async def test_batch_upload_max_files_boundary(self, client: AsyncClient):
        """Batch with exactly 10 files should succeed."""
        files = [_rtf_file(f"file{i}.rtf") for i in range(10)]
        resp = await client.post("/api/upload/rtf/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10

    async def test_single_upload_still_works(self, client: AsyncClient):
        """Existing POST /api/upload/rtf endpoint is not affected."""
        files = [("file", ("test.rtf", MINI_RTF.encode("utf-8"), "application/rtf"))]
        resp = await client.post("/api/upload/rtf", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] != ""
        assert data["turn_count"] > 0

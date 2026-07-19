"""Tests for P4 Level 3.8 — idempotent dictionary upload.

Verifies that:
  1. Uploading the same XML twice to the same session returns the existing
     dictionary instead of creating a duplicate.
  2. Uploading a different XML creates a new dictionary.
  3. Uploading the same XML to a different session creates a new dictionary
     (idempotency is per-session, not global).
  4. The response is identical between the first and idempotent uploads
     (same dictionary name, same conditions).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.session_store_memory import MemorySessionStore


# ── Test fixtures ───────────────────────────────────────────

SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<SpeechLabRequest>
  <Id>test-dict-001</Id>
  <Name>Test Dictionary</Name>
  <Tokens>
    <Token>
      <Type>WORD</Type>
      <Text>hello</Text>
    </Token>
    <Token>
      <Type>WORD</Type>
      <Text>world</Text>
    </Token>
  </Tokens>
</SpeechLabRequest>
"""

DIFFERENT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<SpeechLabRequest>
  <Id>test-dict-002</Id>
  <Name>Another Dictionary</Name>
  <Tokens>
    <Token>
      <Type>WORD</Type>
      <Text>goodbye</Text>
    </Token>
  </Tokens>
</SpeechLabRequest>
"""


@pytest.fixture
def app_with_memory_store():
    """Build a FastAPI app with a fresh in-memory session store."""
    from fastapi import FastAPI
    from app.routers import upload
    from app.services.session_store_memory import MemorySessionStore

    fresh_store = MemorySessionStore()
    app = FastAPI()
    app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
    app.include_router(upload.sessions_router, prefix="/api/sessions", tags=["sessions"])

    # Monkey-patch the global session_store used by the upload router
    original_store = upload.session_store
    upload.session_store = fresh_store

    yield app, fresh_store

    # Restore
    upload.session_store = original_store


@pytest.fixture
def client(app_with_memory_store):
    app, _store = app_with_memory_store
    return TestClient(app)


# ── Tests ───────────────────────────────────────────────────


class TestIdempotentDictionaryUpload:
    """P4 Level 3.8: uploading the same XML twice returns the existing dict."""

    def test_same_xml_twice_returns_existing(self, client):
        """Uploading the same XML twice returns the same dictionary (no duplicate)."""
        # First upload
        resp1 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
        )
        assert resp1.status_code == 200, resp1.text
        data1 = resp1.json()
        session_id = data1["session_id"]
        dict_name_1 = data1["dictionary"]["name"]

        # Second upload — same XML, same session
        resp2 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
            data={"session_id": session_id},
        )
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()

        # Same session, same dictionary name
        assert data2["session_id"] == session_id
        assert data2["dictionary"]["name"] == dict_name_1

    def test_different_xml_creates_new_dictionary(self, client):
        """Uploading a different XML creates a new dictionary in the session."""
        # First upload
        resp1 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
        )
        session_id = resp1.json()["session_id"]
        name1 = resp1.json()["dictionary"]["name"]

        # Second upload — different XML, same session
        resp2 = client.post(
            "/api/upload/dictionary",
            files={"file": ("other.xml", DIFFERENT_XML, "application/xml")},
            data={"session_id": session_id},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        name2 = data2["dictionary"]["name"]

        # Different dictionaries
        assert name1 != name2

    def test_same_xml_different_session_creates_new(self, client, app_with_memory_store):
        """Uploading the same XML to a different session creates a new dictionary.

        Idempotency is per-session, not global.
        """
        _app, store = app_with_memory_store

        # First upload — session A
        resp1 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
        )
        session_a = resp1.json()["session_id"]

        # Create session B explicitly
        store.create("session-b")
        # Second upload — same XML, different session
        resp2 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
            data={"session_id": "session-b"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == "session-b"
        # The dictionary should be present in session B
        session_b = store.get("session-b")
        assert session_b is not None
        assert len(session_b.dictionaries) >= 1

    def test_idempotent_upload_preserves_dictionary_id(self, client):
        """The dictionary id is preserved between the first and idempotent upload."""
        resp1 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
        )
        session_id = resp1.json()["session_id"]
        dict_id_1 = resp1.json()["dictionary"]["id"]

        resp2 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
            data={"session_id": session_id},
        )
        dict_id_2 = resp2.json()["dictionary"]["id"]

        assert dict_id_1 == dict_id_2

    def test_no_duplicate_in_session_dictionaries(self, client, app_with_memory_store):
        """After idempotent upload, the session has only one dictionary with that name."""
        _app, store = app_with_memory_store

        resp1 = client.post(
            "/api/upload/dictionary",
            files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
        )
        session_id = resp1.json()["session_id"]

        # Upload the same XML 3 more times
        for _ in range(3):
            client.post(
                "/api/upload/dictionary",
                files={"file": ("test.xml", SAMPLE_XML, "application/xml")},
                data={"session_id": session_id},
            )

        # The session should still have exactly 1 dictionary
        session = store.get(session_id)
        assert session is not None
        assert len(session.dictionaries) == 1

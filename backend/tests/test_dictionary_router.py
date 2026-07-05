"""Tests for app.routers.dictionary — editing, AI, validation, duplicates,
statistics, XML export endpoints, plus a regression test for GET /tokens.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    PhraseGroupVisual,
)
from app.services.dictionary_ai import (
    DictionaryAnalysisResult,
    DictionarySuggestion,
)
from app.services.xml_parser import parse_xml_bytes


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


_SIMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<SpeechLabRequest type="SpeechLabRequest">
  <Id>root-1</Id>
  <Name>RootDict</Name>
  <State>SAVED</State>
  <SavedState>
    <TotalFound>0</TotalFound>
    <LastUpdateTime>2024-01-01T00:00:00.0000000</LastUpdateTime>
    <ExecutionTime>00:00:00</ExecutionTime>
    <IsActual>false</IsActual>
    <IsCancelled>false</IsCancelled>
  </SavedState>
  <Temporary>False</Temporary>
  <OrderIndex>0</OrderIndex>
  <IsThemed>False</IsThemed>
  <Attributes><AttributeTokens/></Attributes>
  <Tokens>
    <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2"/></Token>
    <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2"/></Token>
    <Token><Text>world</Text><Type>WORD</Type><IsError>false</IsError><Properties Channel="ANY" WordDistance="2"/></Token>
  </Tokens>
  <ExtraLimitations/>
  <ComplexCompleted>False</ComplexCompleted>
  <Requests>
    <SpeechLabRequest type="SpeechLabRequest">
      <Id>child-1</Id>
      <Name>ChildDict</Name>
      <State>SAVED</State>
      <SavedState>
        <TotalFound>0</TotalFound>
        <LastUpdateTime>2024-01-01T00:00:00.0000000</LastUpdateTime>
        <ExecutionTime>00:00:00</ExecutionTime>
        <IsActual>false</IsActual>
        <IsCancelled>false</IsCancelled>
      </SavedState>
      <Temporary>False</Temporary>
      <OrderIndex>0</OrderIndex>
      <IsThemed>False</IsThemed>
      <Attributes><AttributeTokens/></Attributes>
      <Tokens>
        <Token><Text>cancel</Text><Type>WORD</Type><IsError>false</IsError><Properties Channel="CLIENT" WordDistance="2"/></Token>
      </Tokens>
      <ExtraLimitations/>
      <ComplexCompleted>False</ComplexCompleted>
      <Requests/>
    </SpeechLabRequest>
  </Requests>
</SpeechLabRequest>
"""


async def _seed_session(client: AsyncClient, xml: bytes = _SIMPLE_XML) -> str:
    """Upload a dictionary and return the session_id."""
    resp = await client.post(
        "/api/upload/dictionary",
        files={"file": ("test.xml", xml, "application/xml")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


class _FakeProvider:
    """Fake LLM provider for tests."""

    def __init__(self, response: str = "") -> None:
        self._response = response

    async def generate(self, prompt: str, model: Optional[str] = None,
                       system_prompt: Optional[str] = None) -> str:
        return self._response

    async def is_available(self) -> bool:
        return True

    def get_name(self) -> str:
        return "fake"

    def get_default_model(self) -> str:
        return "fake-model"

    def get_models(self) -> List[str]:
        return ["fake-model"]


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def client():
    """Async HTTP test client for the FastAPI app."""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ═══════════════════════════════════════════════════════════
# GET /tokens (regression)
# ═══════════════════════════════════════════════════════════


class TestGetTokens:
    @pytest.mark.asyncio
    async def test_tokens_happy_path(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.get(f"/api/dictionary/{session_id}/tokens")
        assert resp.status_code == 200
        tokens = resp.json()
        assert isinstance(tokens, list)
        assert len(tokens) > 0
        assert tokens[0]["text"] in ("hello", "world", "hello world")

    @pytest.mark.asyncio
    async def test_tokens_missing_session_404(self, client: AsyncClient):
        resp = await client.get("/api/dictionary/nonexistent/tokens")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tokens_missing_dict_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.get(
            f"/api/dictionary/{session_id}/tokens",
            params={"dict_name": "Nope"},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# Editing — Nodes
# ═══════════════════════════════════════════════════════════


class TestNodeEndpoints:
    @pytest.mark.asyncio
    async def test_add_root_node(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes",
            json={"name": "NewRoot"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "NewRoot"
        assert body["parent_name"] is None

    @pytest.mark.asyncio
    async def test_add_child_node(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes",
            json={"name": "SubNode", "parent_name": "RootDict"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "SubNode"

    @pytest.mark.asyncio
    async def test_add_child_node_parent_not_found_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes",
            json={"name": "Sub", "parent_name": "Ghost"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_root_node_duplicate_422(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes",
            json={"name": "RootDict"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_add_node_empty_name_422(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes",
            json={"name": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_node_name(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.patch(
            f"/api/dictionary/{session_id}/nodes/RootDict",
            json={"name": "RenamedRoot"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "RenamedRoot"
        # Verify the session.dictionaries key changed too
        resp_tokens = await client.get(
            f"/api/dictionary/{session_id}/tokens",
            params={"dict_name": "RenamedRoot"},
        )
        assert resp_tokens.status_code == 200

    @pytest.mark.asyncio
    async def test_update_node_missing_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.patch(
            f"/api/dictionary/{session_id}/nodes/Ghost",
            json={"name": "X"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_root_node(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.delete(f"/api/dictionary/{session_id}/nodes/RootDict")
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] is True
        # Subsequent GET /tokens → 404 (no dictionaries)
        resp2 = await client.get(f"/api/dictionary/{session_id}/tokens")
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_child_node(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.delete(f"/api/dictionary/{session_id}/nodes/ChildDict")
        assert resp.status_code == 200
        assert resp.json()["node_name"] == "ChildDict"

    @pytest.mark.asyncio
    async def test_delete_node_missing_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.delete(f"/api/dictionary/{session_id}/nodes/Ghost")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# Editing — Conditions
# ═══════════════════════════════════════════════════════════


class TestConditionEndpoints:
    @pytest.mark.asyncio
    async def test_add_condition(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "new phrase", "word_distance": 2},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["condition"]["text"] == "new phrase"
        assert body["condition"]["word_count"] == 2
        assert body["index"] >= 0

    @pytest.mark.asyncio
    async def test_add_condition_invalid_channel_422(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "x", "channel_constraint": "WRONG"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_add_condition_node_not_found_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/Ghost/conditions",
            json={"text": "x"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_condition(self, client: AsyncClient):
        session_id = await _seed_session(client)
        # Add one condition first
        add = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "old text", "word_distance": 2},
        )
        idx = add.json()["index"]
        resp = await client.patch(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/{idx}",
            json={"text": "new text", "channel_constraint": "CLIENT"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["text"] == "new text"
        assert body["channel_constraint"] == "CLIENT"
        assert body["word_count"] == 2

    @pytest.mark.asyncio
    async def test_update_condition_out_of_range_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.patch(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/999",
            json={"text": "x"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_condition_invalid_logic_operator_422(self, client: AsyncClient):
        session_id = await _seed_session(client)
        add = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "x"},
        )
        idx = add.json()["index"]
        resp = await client.patch(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/{idx}",
            json={"logic_operator": "Bogus"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_condition(self, client: AsyncClient):
        session_id = await _seed_session(client)
        add = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "to remove"},
        )
        idx = add.json()["index"]
        resp = await client.delete(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/{idx}",
        )
        assert resp.status_code == 200
        assert resp.json()["condition_idx"] == idx

    @pytest.mark.asyncio
    async def test_delete_condition_out_of_range_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.delete(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/999",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reorder_conditions(self, client: AsyncClient):
        session_id = await _seed_session(client)
        # The root already has 1 condition from the seed XML ("hello world").
        # Add 2 more so we have 3 total.
        added_indices = []
        for txt in ("aaa", "bbb"):
            r = await client.post(
                f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
                json={"text": txt},
            )
            added_indices.append(r.json()["index"])
        # Build a new order = reverse of all current indices
        n = 1 + len(added_indices)
        new_order = list(reversed(range(n)))
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/reorder",
            json={"new_order": new_order},
        )
        assert resp.status_code == 200, resp.text
        texts = [c["text"] for c in resp.json()["conditions"]]
        # Original order: ["hello world", "aaa", "bbb"] → reversed
        assert texts == ["bbb", "aaa", "hello world"]

    @pytest.mark.asyncio
    async def test_reorder_invalid_permutation_422(self, client: AsyncClient):
        session_id = await _seed_session(client)
        for txt in ("aaa", "bbb"):
            await client.post(
                f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
                json={"text": txt},
            )
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/reorder",
            json={"new_order": [0, 0]},  # duplicate
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_reorder_wrong_length_422(self, client: AsyncClient):
        session_id = await _seed_session(client)
        # Root already has 1 condition; add 1 more → 2 total.
        await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "only one"},
        )
        # Now 2 conditions exist; sending 3 indices must be 422.
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions/reorder",
            json={"new_order": [0, 1, 2]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_edit_then_get_tokens_persisted(self, client: AsyncClient):
        """Edit → re-GET tokens → verify change persisted."""
        session_id = await _seed_session(client)
        # Add a condition to the ChildDict node
        resp = await client.post(
            f"/api/dictionary/{session_id}/nodes/ChildDict/conditions",
            json={"text": "persisted phrase"},
        )
        assert resp.status_code == 200
        # Re-fetch via a NEW session_store.get (verifies persistence)
        from app.utils.session import session_store
        session = session_store.get(session_id)
        assert session is not None
        # Locate the ChildDict
        from app.routers.dictionary import _find_node_recursive
        root = session.dictionaries["RootDict"]
        child = _find_node_recursive(root, "ChildDict")
        assert child is not None
        texts = [c.text for c in child.conditions]
        assert "persisted phrase" in texts


# ═══════════════════════════════════════════════════════════
# Analysis endpoints
# ═══════════════════════════════════════════════════════════


class TestAnalysisEndpoints:
    @pytest.mark.asyncio
    async def test_analyze_ai_with_mocked_llm(self, client: AsyncClient):
        fake_response = (
            '{"summary": "Test summary.", '
            '"examples": ["hello world"], '
            '"recommendations": ["add more"]}'
        )
        fake = _FakeProvider(fake_response)
        with patch("app.services.dictionary_ai.get_provider", return_value=fake):
            session_id = await _seed_session(client)
            resp = await client.post(
                f"/api/dictionary/{session_id}/analyze-ai",
                json={"provider_id": "fake"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["summary"] == "Test summary."
        assert body["examples"] == ["hello world"]

    @pytest.mark.asyncio
    async def test_analyze_ai_missing_session_404(self, client: AsyncClient):
        resp = await client.post(
            "/api/dictionary/ghost/analyze-ai",
            json={},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_suggest_phrases_with_mocked_llm(self, client: AsyncClient):
        fake_response = (
            '[{"phrase": "alpha", "channel": "CLIENT", "distance": 2},'
            ' {"phrase": "beta", "channel": "ANY", "distance": 0}]'
        )
        fake = _FakeProvider(fake_response)
        with patch("app.services.dictionary_ai.get_provider", return_value=fake):
            session_id = await _seed_session(client)
            resp = await client.post(
                f"/api/dictionary/{session_id}/suggest-phrases",
                json={"count": 2},
            )
        assert resp.status_code == 200, resp.text
        suggestions = resp.json()["suggestions"]
        assert len(suggestions) == 2
        assert suggestions[0]["phrase"] == "alpha"

    @pytest.mark.asyncio
    async def test_suggest_phrases_missing_dict_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/suggest-phrases",
            json={"dict_name": "Ghost"},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# Duplicates / Statistics / Validate
# ═══════════════════════════════════════════════════════════


class TestReportEndpoints:
    @pytest.mark.asyncio
    async def test_duplicates(self, client: AsyncClient):
        session_id = await _seed_session(client)
        # Add a duplicate of an existing phrase via the API
        await client.post(
            f"/api/dictionary/{session_id}/nodes/RootDict/conditions",
            json={"text": "hello world"},
        )
        resp = await client.post(
            f"/api/dictionary/{session_id}/duplicates",
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "full" in body
        assert "soft" in body
        # At least one duplicate pair should exist now
        total = len(body["full"]) + len(body["soft"])
        assert total >= 1

    @pytest.mark.asyncio
    async def test_duplicates_missing_session_404(self, client: AsyncClient):
        resp = await client.post("/api/dictionary/ghost/duplicates", json={})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_statistics(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/statistics",
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_conditions"] >= 1
        assert "channels_distribution" in body

    @pytest.mark.asyncio
    async def test_validate(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/validate",
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "errors" in body
        assert "warnings" in body

    @pytest.mark.asyncio
    async def test_validate_missing_dict_404(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/validate",
            json={"dict_name": "Ghost"},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# XML export + round-trip
# ═══════════════════════════════════════════════════════════


class TestExportXml:
    @pytest.mark.asyncio
    async def test_export_xml(self, client: AsyncClient):
        session_id = await _seed_session(client)
        resp = await client.post(
            f"/api/dictionary/{session_id}/export-xml",
            json={"pretty": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/xml"
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".xml" in cd
        # Must be valid XML
        xml_bytes = resp.content
        assert xml_bytes.startswith(b"<?xml")

    @pytest.mark.asyncio
    async def test_export_xml_missing_session_404(self, client: AsyncClient):
        resp = await client.post("/api/dictionary/ghost/export-xml", json={})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_export_xml_round_trip(self, client: AsyncClient):
        """Export → re-parse → verify the tree survives the round trip."""
        session_id = await _seed_session(client)
        export = await client.post(
            f"/api/dictionary/{session_id}/export-xml",
            json={"pretty": True},
        )
        assert export.status_code == 200
        xml_bytes = export.content

        # Re-parse the exported XML
        node, validation = await parse_xml_bytes(xml_bytes, "round_trip.xml")
        assert node.name == "RootDict"
        assert len(node.children) == 1
        assert node.children[0].name == "ChildDict"
        # Both nodes should have at least one condition
        assert len(node.conditions) >= 1
        assert len(node.children[0].conditions) >= 1

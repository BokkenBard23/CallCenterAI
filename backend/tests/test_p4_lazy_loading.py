"""Tests for P4 Level 2.5 — lazy loading tree endpoints.

Verifies that:
  1. GET /api/dictionary/{session_id}/roots returns root metadata only
     (no conditions, no children).
  2. GET /api/dictionary/{session_id}?node_id=<name> returns the full
     subtree for the named node.
  3. GET /api/dictionary/{session_id}?depth=N prunes the tree to N levels.
  4. The /roots response is significantly smaller than the full tree.
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    DictionaryCondition,
    DictionaryNode,
)
from app.services.session_store_memory import MemorySessionStore


# ── Fixtures ─────────────────────────────────────────────────


def _make_nested_dictionary() -> DictionaryNode:
    """Build a nested dictionary with root → child → grandchild structure."""
    grandchild = DictionaryNode(
        id="gc-1",
        name="Внучок",
        conditions=[
            DictionaryCondition(text="phrase 1"),
            DictionaryCondition(text="phrase 2"),
        ],
        condition_count=2,
    )
    child = DictionaryNode(
        id="ch-1",
        name="Ребёнок",
        conditions=[
            DictionaryCondition(text="child phrase"),
        ],
        condition_count=1,
        children=[grandchild],
        has_children=True,
        children_count=1,
    )
    root = DictionaryNode(
        id="root-1",
        name="Корень",
        conditions=[
            DictionaryCondition(text="root phrase 1"),
            DictionaryCondition(text="root phrase 2"),
            DictionaryCondition(text="root phrase 3"),
        ],
        condition_count=3,
        children=[child],
        has_children=True,
        children_count=1,
    )
    return root


@pytest.fixture
def app_with_store():
    from fastapi import FastAPI
    from app.routers import dictionary as dict_router
    from app.services.session_store_memory import MemorySessionStore

    fresh_store = MemorySessionStore()
    app = FastAPI()
    app.include_router(dict_router.router, prefix="/api/dictionary", tags=["dictionary"])

    # Monkey-patch the global session_store used by the dictionary router
    original_store = dict_router.session_store
    dict_router.session_store = fresh_store

    # Register a session with a nested dictionary
    fresh_store.create("sess-1")
    session = fresh_store.get("sess-1")
    session.dictionaries["Корень"] = _make_nested_dictionary()
    fresh_store.update(session)

    yield app, fresh_store

    dict_router.session_store = original_store


@pytest.fixture
def client(app_with_store):
    app, _store = app_with_store
    return TestClient(app)


# ── Tests: /roots endpoint ─────────────────────────────────


class TestRootsEndpoint:
    def test_roots_returns_root_metadata_only(self, client):
        """GET /roots returns the root node with empty conditions and children."""
        resp = client.get("/api/dictionary/sess-1/roots")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        root = data[0]
        assert root["name"] == "Корень"
        # Metadata preserved
        assert root["condition_count"] == 3
        assert root["has_children"] is True
        assert root["children_count"] == 1
        # But conditions and children are EMPTY
        assert root["conditions"] == []
        assert root["children"] == []

    def test_roots_response_smaller_than_full_tree(self, client):
        """The /roots response is significantly smaller than GET /{session_id}."""
        roots_resp = client.get("/api/dictionary/sess-1/roots")
        full_resp = client.get("/api/dictionary/sess-1")

        assert len(roots_resp.content) < len(full_resp.content)

    def test_roots_404_on_missing_session(self, client):
        resp = client.get("/api/dictionary/nonexistent/roots")
        assert resp.status_code == 404

    def test_roots_empty_for_session_without_dicts(self, client, app_with_store):
        _app, store = app_with_store
        store.create("empty-sess")
        resp = client.get("/api/dictionary/empty-sess/roots")
        assert resp.status_code == 200
        assert resp.json() == []


# ── Tests: ?node_id=<name> subtree loading ──────────────────


class TestSubtreeLoading:
    def test_node_id_returns_subtree(self, client):
        """GET /{session_id}?node_id=Ребёнок returns the child subtree."""
        resp = client.get("/api/dictionary/sess-1", params={"node_id": "Ребёнок"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        subtree = data[0]
        assert subtree["name"] == "Ребёнок"
        assert len(subtree["conditions"]) == 1
        # Grandchild should be present in the subtree
        assert len(subtree["children"]) == 1
        assert subtree["children"][0]["name"] == "Внучок"

    def test_node_id_404_on_missing_node(self, client):
        resp = client.get("/api/dictionary/sess-1", params={"node_id": "Несуществующий"})
        assert resp.status_code == 404

    def test_node_id_with_depth_prunes_subtree(self, client):
        """?node_id=Корень&depth=1 returns the root with no children."""
        resp = client.get(
            "/api/dictionary/sess-1",
            params={"node_id": "Корень", "depth": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        root = data[0]
        assert root["name"] == "Корень"
        assert root["children"] == []
        assert root["has_children"] is False

    def test_depth_2_keeps_one_level_of_children(self, client):
        """?depth=2 returns root + first level of children (grandchildren stripped)."""
        resp = client.get("/api/dictionary/sess-1", params={"depth": 2})
        assert resp.status_code == 200
        data = resp.json()
        root = data[0]
        assert root["name"] == "Корень"
        assert len(root["children"]) == 1
        child = root["children"][0]
        assert child["name"] == "Ребёнок"
        # Grandchild should be stripped (depth=2 = root + 1 level)
        assert child["children"] == []
        assert child["has_children"] is False


# ── Tests: combined lazy loading flow ──────────────────────


class TestLazyLoadingFlow:
    def test_full_lazy_loading_flow(self, client):
        """Simulates the FE lazy loading flow:
        1. GET /roots → root metadata only
        2. GET /?node_id=Корень → full root subtree
        3. GET /?node_id=Ребёнок → child subtree
        """
        # Step 1: Load roots
        roots_resp = client.get("/api/dictionary/sess-1/roots")
        assert roots_resp.status_code == 200
        roots = roots_resp.json()
        assert len(roots) == 1
        assert roots[0]["conditions"] == []
        assert roots[0]["children"] == []

        # Step 2: Load root subtree on expand
        subtree_resp = client.get(
            "/api/dictionary/sess-1", params={"node_id": "Корень"}
        )
        assert subtree_resp.status_code == 200
        subtree = subtree_resp.json()[0]
        assert len(subtree["conditions"]) == 3
        assert len(subtree["children"]) == 1

        # Step 3: Load child subtree on expand
        child_resp = client.get(
            "/api/dictionary/sess-1", params={"node_id": "Ребёнок"}
        )
        assert child_resp.status_code == 200
        child = child_resp.json()[0]
        assert len(child["conditions"]) == 1
        assert len(child["children"]) == 1
        assert child["children"][0]["name"] == "Внучок"

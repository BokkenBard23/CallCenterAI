"""Tests for INV-6 container nodes (empty conditions, children-only) edge-case.

UI-2.6 BE timestamps iteration (Task 3). Real SmartLogger dictionaries have
not been observed with pure container nodes (see docs/specs/smartlogger-xml-
verification.md V7: all 31 SpeechLabRequest nodes carry non-empty <Tokens>),
but the code path must remain correct for synthetic test fixtures and
forward compatibility.

A container node (``node.conditions == []``) is one whose only purpose is
to group children. ``_search_recursive`` MUST:

  1. NOT increment `level` — children stay at the parent's level.
  2. Produce NO matches of its own (no conditions to evaluate).
  3. Inherit `allowed_turn_indices` verbatim from the caller (open / closed
     / None). This means the GATE is preserved across container boundaries.
  4. Treat `node_matched` as implicitly True (gate stays open) —
     ``evaluate_phrase_logic_tree([], set()) == True`` (empty AND = vacuous
     truth).
  5. Pass `parent_match_times` through unchanged — container is invisible
     to EventType=Parent time-gap filtering.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "Transcrib")
)

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DialogueTurn,
    ParsedDialog,
)
from app.services.search import (
    _search_recursive,
    evaluate_phrase_logic_tree,
    run_hierarchical_search,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _condition(text: str, channel: str = "ANY") -> DictionaryCondition:
    return DictionaryCondition(
        text=text,
        word_distance=2,
        word_count=len(text.split()),
        channel_constraint=channel,
    )


def _make_dialog(turns: list[tuple[str, str]]) -> ParsedDialog:
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=i, speaker=s, text=t)
            for i, (s, t) in enumerate(turns)
        ],
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. Container node with children — level + GATE inheritance
# ═══════════════════════════════════════════════════════════════════════


class TestContainerNodeInheritance:
    """Children of a container node inherit level + allowed_turn_indices."""

    @pytest.mark.asyncio
    async def test_container_node_children_at_same_level_as_root(self) -> None:
        """Container at root (level=1) → children searched at level=1 (NOT 2).

        Without INV-6 the level would be incremented on every recursive call,
        producing a spurious +1 shift for the first real condition node.
        """
        dialog = _make_dialog([("Клиент", "я хочу расторгнуть договор")])

        q1 = DictionaryNode(
            id="q1",
            name="Q1",
            conditions=[_condition("расторгнуть", channel="CLIENT")],
            children=[],
        )
        container = DictionaryNode(
            id="container",
            name="Container",
            conditions=[],  # empty → container
            children=[q1],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[container], cascade=False
        )

        assert result.total_matches == 1
        # Container does not consume level → Q1 is level=1.
        assert result.matches[0].word_distance_used == 1
        assert result.matches[0].quarter == "Q1"

    @pytest.mark.asyncio
    async def test_double_nested_container_children_at_same_level(self) -> None:
        """Two stacked containers → child still at level=1."""
        dialog = _make_dialog([("Клиент", "расторгнуть")])

        q1 = DictionaryNode(
            id="q1",
            name="Q1",
            conditions=[_condition("расторгнуть", channel="CLIENT")],
            children=[],
        )
        inner = DictionaryNode(
            id="inner",
            name="Inner Container",
            conditions=[],
            children=[q1],
        )
        outer = DictionaryNode(
            id="outer",
            name="Outer Container",
            conditions=[],
            children=[inner],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[outer], cascade=False
        )

        assert result.matches[0].word_distance_used == 1

    @pytest.mark.asyncio
    async def test_container_produces_no_matches_of_its_own(self) -> None:
        """A container node has no conditions → it cannot match anything.

        Even if the dialogue text would match a phrase, the container's
        own ``level_counts`` entry must be absent (or zero) — there is no
        DictMatch with ``quarter == container.name``.
        """
        dialog = _make_dialog([("Клиент", "расторгнуть")])

        container = DictionaryNode(
            id="container",
            name="Container",
            conditions=[],
            children=[
                DictionaryNode(
                    id="q1",
                    name="Q1",
                    conditions=[_condition("расторгнуть", channel="CLIENT")],
                    children=[],
                )
            ],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[container], cascade=False
        )

        container_matches = [m for m in result.matches if m.quarter == "Container"]
        assert container_matches == []

    @pytest.mark.asyncio
    async def test_container_inherits_open_gate(self) -> None:
        """If the parent of a container opened the gate (allowed=None),
        the container's children must also see an open gate."""
        dialog = _make_dialog([
            ("Клиент", "расторгнуть"),       # turn 0
            ("Клиент", "отказываюсь"),       # turn 1 (different phrase)
        ])

        q2 = DictionaryNode(
            id="q2",
            name="Q2",
            conditions=[_condition("отказываюсь", channel="CLIENT")],
            children=[],
        )
        container = DictionaryNode(
            id="container",
            name="Container",
            conditions=[],
            children=[q2],
        )
        q1 = DictionaryNode(
            id="q1",
            name="Q1",
            conditions=[_condition("расторгнуть", channel="CLIENT")],
            children=[container],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[q1], cascade=False
        )

        # Q1 matched at turn 0 → gate opens → container (no conditions)
        # inherits the open gate → Q2 should match turn 1.
        q2_turns = {m.turn_index for m in result.matches if m.quarter == "Q2"}
        assert 1 in q2_turns
        # Q2 level should be 2 (Q1 was level 1, container does not consume).
        q2_match = next(m for m in result.matches if m.quarter == "Q2")
        assert q2_match.word_distance_used == 2

    @pytest.mark.asyncio
    async def test_container_inherits_closed_gate(self) -> None:
        """If the parent of a container closed the gate (allowed=set()),
        the container's children must also see a closed gate."""
        dialog = _make_dialog([
            ("Клиент", "отказываюсь"),  # Q2 phrase only, no Q1 → gate closed
        ])

        q2 = DictionaryNode(
            id="q2",
            name="Q2",
            conditions=[_condition("отказываюсь", channel="CLIENT")],
            children=[],
        )
        container = DictionaryNode(
            id="container",
            name="Container",
            conditions=[],
            children=[q2],
        )
        q1 = DictionaryNode(
            id="q1",
            name="Q1",
            conditions=[_condition("расторгнуть", channel="CLIENT")],
            children=[container],
        )

        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[q1], cascade=False
        )

        # Q1 did not match → gate closed → container inherits closed gate
        # → Q2 should NOT match even though turn text matches Q2 phrase.
        q2_matches = [m for m in result.matches if m.quarter == "Q2"]
        assert q2_matches == []


# ═══════════════════════════════════════════════════════════════════════
# 2. evaluate_phrase_logic_tree: empty phrase_groups → True
# ═══════════════════════════════════════════════════════════════════════


class TestEmptyPhraseGroupsGate:
    """``evaluate_phrase_logic_tree([], set())`` must return True — this is
    what makes a container node's gate implicitly open."""

    def test_empty_phrase_groups_returns_true(self) -> None:
        assert evaluate_phrase_logic_tree([], set()) is True

    def test_empty_phrase_groups_true_regardless_of_matches(self) -> None:
        """Even if some phrases matched (impossible for a real container,
        but defensive), the empty-tree evaluation is True."""
        assert evaluate_phrase_logic_tree([], {"anything"}) is True


# ═══════════════════════════════════════════════════════════════════════
# 3. Container node: parent_match_times passthrough
# ═══════════════════════════════════════════════════════════════════════


class TestContainerParentMatchTimesPassthrough:
    """A container node must pass ``parent_match_times`` through unchanged
    so children's EventType=Parent limits evaluate relative to the nearest
    ancestor that actually produced matches (NOT the container)."""

    def test_container_passes_parent_match_times_through(self) -> None:
        """Direct call to _search_recursive with a container node and a
        non-None parent_match_times → children receive the SAME list."""
        # We can't easily intercept the recursive call from the public API
        # without heavy monkeypatching, so we exercise the contract via a
        # fixture that has a Parent-type limit on the child and verify it
        # resolves against the GRANDPARENT's match time.
        from app.models import ExtraLimitation, ExtraLimitationLimit

        # Build a 3-turn timed dialogue.
        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(
                    turn_index=0,
                    speaker="Клиент",
                    text="расторгнуть",
                    start_offset=10.0,
                    end_offset=15.0,
                ),
                DialogueTurn(
                    turn_index=1,
                    speaker="Сотрудник",
                    text="ignore",
                    start_offset=20.0,
                    end_offset=25.0,
                ),
                DialogueTurn(
                    turn_index=2,
                    speaker="Клиент",
                    text="отказываюсь",
                    start_offset=30.0,
                    end_offset=35.0,
                ),
            ],
        )

        # Q2 has a Parent-type After=10s INCLUDE limit (OnlyInGaps). Parent
        # (Q1) matched at t=10. Window = [10, 20].
        # turn 2 (start=30) is NOT in window → filtered out (kept out by
        # OnlyInGaps since match must be inside window to survive).
        # If the container dropped parent_match_times, Q2's filter would be
        # a no-op and Q2 would match turn 2 — that's the regression we guard
        # against.
        q2 = DictionaryNode(
            id="q2",
            name="Q2",
            conditions=[
                DictionaryCondition(
                    text="отказываюсь",
                    word_distance=2,
                    word_count=1,
                    channel_constraint="CLIENT",
                    extra_limitations=[
                        ExtraLimitation(
                            event_type="Parent",
                            search_specifier="OnlyInGaps",
                            limits=[
                                ExtraLimitationLimit(
                                    value=10,
                                    value_type="Seconds",
                                    channel="ANY",
                                    enabled=True,
                                    search_direction="After",
                                )
                            ],
                        )
                    ],
                )
            ],
            children=[],
        )
        container = DictionaryNode(
            id="container",
            name="Container",
            conditions=[],
            children=[q2],
        )
        q1 = DictionaryNode(
            id="q1",
            name="Q1",
            conditions=[_condition("расторгнуть", channel="CLIENT")],
            children=[container],
        )

        import asyncio as _aio

        async def _run():
            return await run_hierarchical_search(
                dialog=dialog, dictionaries=[q1], cascade=False
            )

        out = _aio.run(_run())

        q2_matches = [m for m in out.matches if m.quarter == "Q2"]
        # Parent matched at t=10; After=10 → keep matches with start in [10,20].
        # turn 2 start=30 → NOT within 10s after → filtered out.
        assert q2_matches == [], (
            "Container must pass parent_match_times through so the Parent "
            "filter on Q2 actually applies. Got Q2 matches: "
            f"{[m.turn_index for m in q2_matches]}"
        )

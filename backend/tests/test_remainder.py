"""Tests for Remainder catch-all fallback (UI-2.6).

`<SpeechLabRemainderRequest>` nodes are catch-all fallback siblings of
ordinary `<SpeechLabRequest>` nodes. Real production dictionaries contain
2 such nodes ("Предложен сразу монтажник без альтернативы",
"Стоимость не озвучена") — see docs/specs/smartlogger-xml-verification.md.

UI-2.6 semantics implemented in search.py:
  - Remainder nodes are searched like ordinary nodes (no special catch-all
    suppression of siblings — that legacy "non-matched parent" semantic
    is TODO at the cascade level, not the node level).
  - Matches from remainder nodes are marked `DictMatch.is_remainder=True`
    so the FE can render them distinctly.
  - `is_remainder` does NOT change GATE behaviour for siblings or children.

Invariant preserved: `DictMatch` FRONTEND CONTRACT — only a new optional
field `is_remainder: bool = False` was added (default keeps existing
clients working). Existing fields are untouched.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Ensure smartlogger is importable (matches test_search_hierarchy.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Transcrib"))

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DictMatch,
    DialogueTurn,
    ParsedDialog,
)
from app.services.search import _search_recursive, run_hierarchical_search


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_condition(text: str, word_distance: int = 2, channel: str = "ANY") -> DictionaryCondition:
    return DictionaryCondition(
        text=text,
        word_distance=word_distance,
        word_count=len(text.split()),
        channel_constraint=channel,
    )


def _make_dialog(turns: list[tuple[str, str]]) -> ParsedDialog:
    return ParsedDialog(
        filename="test_dialog.rtf",
        turns=[
            DialogueTurn(turn_index=i, text=text, speaker=speaker)
            for i, (speaker, text) in enumerate(turns)
        ],
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. Remainder node matches are marked is_remainder=True
# ═══════════════════════════════════════════════════════════════════════


class TestRemainderMarked:
    @pytest.mark.asyncio
    async def test_remainder_node_matches_flagged(self) -> None:
        """A match from a <SpeechLabRemainderRequest> node carries is_remainder=True."""
        dialog = _make_dialog([
            ("Клиент", "стоимость не озвучена повторю"),
        ])
        remainder = DictionaryNode(
            id="r1",
            name="Стоимость не озвучена",
            parent_name="root",
            conditions=[_make_condition("стоимость не озвучена", channel="CLIENT")],
            children=[],
            is_remainder=True,
        )
        root = DictionaryNode(
            id="root",
            name="Root",
            conditions=[],
            children=[remainder],
        )
        result = await run_hierarchical_search(dialog=dialog, dictionaries=[root], cascade=False)
        assert result.total_matches == 1
        assert result.matches[0].is_remainder is True
        # Other fields are still populated normally.
        assert result.matches[0].phrase_text == "стоимость не озвучена"
        assert result.matches[0].quarter == "Стоимость не озвучена"

    @pytest.mark.asyncio
    async def test_non_remainder_node_matches_not_flagged(self) -> None:
        """A match from a normal <SpeechLabRequest> node has is_remainder=False."""
        dialog = _make_dialog([
            ("Клиент", "хочу расторгнуть договор"),
        ])
        node = DictionaryNode(
            id="q1",
            name="Риск расторжения",
            conditions=[_make_condition("расторгнуть договор", channel="CLIENT")],
            children=[],
            is_remainder=False,
        )
        result = await run_hierarchical_search(dialog=dialog, dictionaries=[node], cascade=False)
        assert result.total_matches == 1
        assert result.matches[0].is_remainder is False


# ═══════════════════════════════════════════════════════════════════════
# 2. Remainder matches included in results
# ═══════════════════════════════════════════════════════════════════════


class TestRemainderIncluded:
    @pytest.mark.asyncio
    async def test_remainder_match_in_results(self) -> None:
        """Remainder match is included in all_matches, not dropped."""
        dialog = _make_dialog([
            ("Клиент", "предложен сразу монтажник"),
        ])
        remainder = DictionaryNode(
            id="r1",
            name="Предложен сразу монтажник",
            conditions=[_make_condition("предложен сразу монтажник", channel="CLIENT")],
            children=[],
            is_remainder=True,
        )
        result = await run_hierarchical_search(dialog=dialog, dictionaries=[remainder], cascade=False)
        assert result.total_matches == 1
        assert len(result.matches) == 1
        assert result.matches[0].is_remainder is True

    @pytest.mark.asyncio
    async def test_remainder_and_normal_match_coexist(self) -> None:
        """When both a normal node and a remainder node match, both are returned."""
        dialog = _make_dialog([
            ("Клиент", "хочу расторгнуть договор и стоимость не озвучена"),
        ])
        normal = DictionaryNode(
            id="q1",
            name="Риск расторжения",
            conditions=[_make_condition("расторгнуть договор", channel="CLIENT")],
            children=[],
            is_remainder=False,
        )
        remainder = DictionaryNode(
            id="r1",
            name="Стоимость не озвучена",
            conditions=[_make_condition("стоимость не озвучена", channel="CLIENT")],
            children=[],
            is_remainder=True,
        )
        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[normal, remainder], cascade=False
        )
        assert result.total_matches == 2
        is_remainder_flags = {m.phrase_text: m.is_remainder for m in result.matches}
        assert is_remainder_flags["расторгнуть договор"] is False
        assert is_remainder_flags["стоимость не озвучена"] is True


# ═══════════════════════════════════════════════════════════════════════
# 3. Remainder doesn't affect GATE for siblings
# ═══════════════════════════════════════════════════════════════════════


class TestRemainderGate:
    def test_remainder_node_does_not_open_gate_for_siblings_directly(self) -> None:
        """Remainder matches don't affect sibling nodes (no cross-node GATE).

        Sibling search uses cascade (root-level dicts); a remainder dict that
        matches does NOT change whether the next dict is searched (cascade
        only cares whether *previous* dict matched — and matches count).
        Inside a single root, GATE is parent→child, not sibling→sibling.

        This test asserts the invariant: a remainder node's matches don't
        influence another sibling remainder's results. Both are searched
        independently.
        """
        turns = [
            {"speaker": "Клиент", "text": "стоимость не озвучена", "start_offset": None, "end_offset": None},
        ]
        channel_map = {0: "Клиент"}

        # Two siblings — both searched independently via _search_recursive.
        r1 = DictionaryNode(
            id="r1",
            name="Стоимость не озвучена",
            conditions=[_make_condition("стоимость", channel="CLIENT")],
            children=[],
            is_remainder=True,
        )
        r2 = DictionaryNode(
            id="r2",
            name="Не сматчился нигде",
            conditions=[_make_condition("не существующее слово", channel="CLIENT")],
            children=[],
            is_remainder=True,
        )
        # Call _search_recursive on r1 alone — should return 1 match flagged.
        matches_r1, _ = _search_recursive(
            node=r1,
            turns=turns,
            channel_map=channel_map,
            allowed_turn_indices=None,
            level=1,
            dict_name="r1",
        )
        assert len(matches_r1) == 1
        assert matches_r1[0].is_remainder is True

        # And r2 alone — should return 0 matches.
        matches_r2, _ = _search_recursive(
            node=r2,
            turns=turns,
            channel_map=channel_map,
            allowed_turn_indices=None,
            level=1,
            dict_name="r2",
        )
        assert matches_r2 == []

    @pytest.mark.asyncio
    async def test_remainder_node_children_follow_normal_gate(self) -> None:
        """Children of a remainder node follow normal GATE (open if parent matched).

        A remainder node with a child whose phrase appears in a *different*
        turn — the child searches ALL turns iff the parent remainder matched.
        """
        dialog = _make_dialog([
            ("Клиент", "стоимость"),                # turn 0 — remainder match
            ("Сотрудник", "уточнение деталей"),     # turn 1 — child match
        ])
        child = DictionaryNode(
            id="c1",
            name="Уточнение",
            conditions=[_make_condition("уточнение", channel="OPERATOR")],
            children=[],
        )
        remainder = DictionaryNode(
            id="r1",
            name="Стоимость не озвучена",
            conditions=[_make_condition("стоимость", channel="CLIENT")],
            children=[child],
            is_remainder=True,
        )
        result = await run_hierarchical_search(
            dialog=dialog, dictionaries=[remainder], cascade=False
        )
        # Both matches: parent remainder at level 1, child at level 2.
        assert result.total_matches == 2
        # The child match is NOT flagged is_remainder (only the remainder node's
        # own matches are flagged; child is a normal SpeechLabRequest).
        flags_by_phrase = {m.phrase_text: m.is_remainder for m in result.matches}
        assert flags_by_phrase["стоимость"] is True
        assert flags_by_phrase["уточнение"] is False


# ═══════════════════════════════════════════════════════════════════════
# 4. Default DictMatch.is_remainder is False (backward compat)
# ═══════════════════════════════════════════════════════════════════════


class TestDefaultField:
    def test_dict_match_default_is_remainder_false(self) -> None:
        """New DictMatch instances default to is_remainder=False."""
        m = DictMatch(
            phrase_text="x",
            quarter="q",
            turn_index=0,
            speaker="Клиент",
        )
        assert m.is_remainder is False

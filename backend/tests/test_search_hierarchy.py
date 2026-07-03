"""Tests for hierarchical search: level assignment (INV-6) and cascade semantics (INV-7).

Covers:
  - INV-6: Container nodes (no conditions) do NOT consume a level number.
    Root SpeechLabRequest with no conditions → children at level=1 (not 2).
    Q1 phrases = level 1, Q2 phrases = level 2, Q3 phrases = level 3.
  - INV-7 (GATE model): Cascade is a prerequisite GATE, not a turn-level filter.
    When cascade=True, each subsequent dictionary searches ALL turns,
    but ONLY IF the previous dictionary had at least one match anywhere.
    Rationale: Q2 phrases appear in DIFFERENT turns than Q1 phrases.
    The gate model captures: "Q2 is relevant only when Q1 matched somewhere."
  - Hierarchy: child dicts search ALL turns if parent matched, skipped if not.
"""
import sys
import os
import pytest

# Ensure smartlogger is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))
# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DictMatch,
    ParsedDialog,
    SearchResult,
    TextSegment,
    DialogueTurn,
)
from app.services.search import run_hierarchical_search, _search_recursive


# ═══════════════════════════════════════════════════════════════════════
# Test fixtures
# ═══════════════════════════════════════════════════════════════════════

def _make_condition(text: str, word_distance: int = 2, channel: str = "ANY",
                    is_exact: bool = False) -> DictionaryCondition:
    """Helper to create a DictionaryCondition."""
    return DictionaryCondition(
        text=text,
        word_distance=word_distance,
        word_count=len(text.split()),
        channel_constraint=channel,
        is_exact=is_exact,
    )


def _make_dialog(turns: list[tuple[str, str]]) -> ParsedDialog:
    """Helper to create a ParsedDialog from (speaker, text) pairs."""
    return ParsedDialog(
        filename="test_dialog.rtf",
        turns=[
            DialogueTurn(turn_index=i, text=text, speaker=speaker)
            for i, (speaker, text) in enumerate(turns)
        ],
    )


# ═══════════════════════════════════════════════════════════════════════
# INV-6: Level assignment — container nodes don't consume levels
# ═══════════════════════════════════════════════════════════════════════

class TestLevelAssignmentINV6:
    """Tests for INV-6: Container nodes (no conditions) skip level increment.

    In the combined XML like "sample_dictionary.xml":
      Root (no conditions, just attributes) → Q1 (conditions) → Q2 (conditions) → Q3 (conditions)

    Q1 should be level=1, Q2=level=2, Q3=level=3.
    NOT: Root=level1 (wasted), Q1=level2, Q2=level3, Q3=level4.
    """

    @pytest.mark.asyncio
    async def test_container_no_conditions_children_at_level1(self):
        """Root container with no conditions → children start at level=1."""
        dialog = _make_dialog([
            ("Клиент", "я хочу расторгнуть договор"),
            ("Сотрудник", "давайте обсудим"),
        ])

        q1 = DictionaryNode(
            id="q1", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть договор", word_distance=1, channel="CLIENT")],
            children=[],
        )
        root = DictionaryNode(
            id="root", name="Root Container",
            conditions=[],  # No conditions — container node
            children=[q1],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        # The match should be at level=1 (not level=2)
        assert result.total_matches >= 1, "Expected at least 1 match"
        for match in result.matches:
            assert match.word_distance_used == 1, (
                f"Expected level=1 for Q1 phrase, got level={match.word_distance_used}"
            )
        assert "1" in result.matches_by_level, "Expected level 1 in matches_by_level"

    @pytest.mark.asyncio
    async def test_three_level_hierarchy_with_container_root(self):
        """Root(container) → Q1(conditions) → Q2(conditions) → Q3(conditions).

        Q1=level1, Q2=level2, Q3=level3.

        GATE model: Q1 matched → Q2 searches ALL turns → Q2 matched → Q3 searches ALL turns.
        Use ANY channel so all conditions can match in any turn.
        """
        dialog = _make_dialog([
            ("Клиент", "я хочу расторгнуть договор"),  # turn 0: Q1 match
            ("Клиент", "отказываюсь от диагностики"),  # turn 1: Q2 match (different turn!)
            ("Клиент", "создам задание"),  # turn 2: Q3 match (different turn!)
        ])

        q3 = DictionaryNode(
            id="q3", name="Нет задания",
            conditions=[_make_condition("создам", word_distance=1, channel="ANY")],
            children=[],
        )
        q2 = DictionaryNode(
            id="q2", name="Отказ от диагностики",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="ANY")],
            children=[q3],
        )
        q1 = DictionaryNode(
            id="q1", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="ANY")],
            children=[q2],
        )
        root = DictionaryNode(
            id="root", name="Root Container",
            conditions=[],  # Container — no conditions
            children=[q1],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        # Collect levels from matches
        levels = {m.word_distance_used for m in result.matches}

        # Q1 should be level=1, not level=2
        assert 1 in levels, f"Expected level 1 for Q1, got levels: {levels}"
        # Q2 should be level=2 (child of Q1 which had matches → gate passed → searches ALL turns)
        assert 2 in levels, f"Expected level 2 for Q2, got levels: {levels}"
        # Q3 should be level=3 (child of Q2 which had matches → gate passed → searches ALL turns)
        assert 3 in levels, f"Expected level 3 for Q3, got levels: {levels}"
        # Level 4 should NOT exist (container root doesn't consume a level)
        assert 4 not in levels, f"Expected NO level 4, got levels: {levels}"

    @pytest.mark.asyncio
    async def test_no_container_root_has_conditions(self):
        """If root HAS conditions, it owns level=1 and children get level=2."""
        dialog = _make_dialog([
            ("Клиент", "я хочу расторгнуть договор"),
        ])

        child = DictionaryNode(
            id="child", name="Подробности",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[],
        )
        root = DictionaryNode(
            id="root", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[child],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        levels = {m.word_distance_used for m in result.matches}
        assert 1 in levels, f"Root with conditions should be level 1, got {levels}"
        assert 2 in levels, f"Child should be level 2, got {levels}"

    @pytest.mark.asyncio
    async def test_nested_containers_both_no_conditions(self):
        """Two nested containers (no conditions) — children still at level=1."""
        dialog = _make_dialog([
            ("Клиент", "я хочу расторгнуть договор"),
        ])

        q1 = DictionaryNode(
            id="q1", name="Q1 with conditions",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[],
        )
        inner_container = DictionaryNode(
            id="inner", name="Inner Container",
            conditions=[],  # Also no conditions
            children=[q1],
        )
        root = DictionaryNode(
            id="root", name="Root Container",
            conditions=[],  # No conditions
            children=[inner_container],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        # Even with TWO nested containers, Q1 should be level=1
        for match in result.matches:
            assert match.word_distance_used == 1, (
                f"Expected level=1 despite double container, got {match.word_distance_used}"
            )


# ═══════════════════════════════════════════════════════════════════════
# INV-7: Cascade GATE semantics (revised)
# ═══════════════════════════════════════════════════════════════════════

class TestCascadeGateINV7:
    """Tests for INV-7 revised: Cascade is a GATE, not a turn-level filter.

    SmartLogger behavior: Q2 searches ALL turns in the dialogue,
    but ONLY IF Q1 had at least one match anywhere in the dialogue.
    Q2 phrases (e.g. "клиент отказывается") appear in DIFFERENT turns
    than Q1 phrases (e.g. "риск расторжения"). The gate model
    correctly captures: "Q2 is relevant only when Q1 matched somewhere."
    """

    @pytest.mark.asyncio
    async def test_cascade_gate_second_dict_searches_all_turns(self):
        """cascade=True: if Q1 matched, Q2 searches ALL turns (gate passed).

        Dialog:
          Turn 0: "расторгнуть договор" — matches Q1 only
          Turn 1: "отказываюсь от диагностики" — matches Q2 only
          Turn 2: "расторгнуть отказываюсь" — matches both

        Gate cascade: Q1 matched somewhere → Q2 searches ALL turns.
        Q2 should find matches in BOTH turn 1 AND turn 2.
        """
        dialog = _make_dialog([
            ("Клиент", "я хочу расторгнуть договор"),  # turn 0: Q1 match
            ("Клиент", "я отказываюсь от диагностики"),  # turn 1: Q2 match only
            ("Клиент", "расторгнуть и отказываюсь"),  # turn 2: both Q1+Q2 match
        ])

        dict1 = DictionaryNode(
            id="d1", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[],
        )
        dict2 = DictionaryNode(
            id="d2", name="Отказ от диагностики",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="CLIENT")],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[dict1, dict2],
            cascade=True,
        )

        # Dict 1 matches: turn 0 and turn 2
        dict1_turns = {m.turn_index for m in result.matches if m.quarter == "Риск расторжения"}
        assert 0 in dict1_turns, "Dict 1 should match turn 0"
        assert 2 in dict1_turns, "Dict 1 should match turn 2"

        # Gate cascade: Q1 matched → Q2 searches ALL turns
        # Q2 should find matches in turn 1 AND turn 2
        dict2_turns = {m.turn_index for m in result.matches if m.quarter == "Отказ от диагностики"}
        assert 1 in dict2_turns, "Dict 2 (gate cascade) should match turn 1 (Q2 phrase there)"
        assert 2 in dict2_turns, "Dict 2 (gate cascade) should match turn 2 (Q2 phrase there)"

    @pytest.mark.asyncio
    async def test_cascade_false_searches_all_turns(self):
        """cascade=False: each dictionary searches ALL turns independently."""
        dialog = _make_dialog([
            ("Клиент", "я хочу расторгнуть договор"),  # turn 0: Q1 match
            ("Клиент", "я отказываюсь от диагностики"),  # turn 1: Q2 match only
        ])

        dict1 = DictionaryNode(
            id="d1", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[],
        )
        dict2 = DictionaryNode(
            id="d2", name="Отказ от диагностики",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="CLIENT")],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[dict1, dict2],
            cascade=False,
        )

        # Dict 2 should match turn 1 even though dict 1 didn't match it
        dict2_turns = {m.turn_index for m in result.matches if m.quarter == "Отказ от диагностики"}
        assert 1 in dict2_turns, "Dict 2 (no cascade) should match turn 1"

    @pytest.mark.asyncio
    async def test_cascade_three_dicts_all_search_all_turns(self):
        """cascade=True with 3 dicts: each searches ALL turns if previous gates passed."""
        dialog = _make_dialog([
            ("Клиент", "расторгнуть отказываюсь создам"),  # turn 0: all three match
            ("Клиент", "расторгнуть отказываюсь"),  # turn 1: Q1+Q2 match
            ("Клиент", "отказываюсь создам"),  # turn 2: Q2+Q3 match (no Q1)
            ("Клиент", "создам"),  # turn 3: Q3 only
        ])

        dict1 = DictionaryNode(
            id="d1", name="Q1",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[],
        )
        dict2 = DictionaryNode(
            id="d2", name="Q2",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="CLIENT")],
            children=[],
        )
        dict3 = DictionaryNode(
            id="d3", name="Q3",
            conditions=[_make_condition("создам", word_distance=1, channel="CLIENT")],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[dict1, dict2, dict3],
            cascade=True,
        )

        # Dict 1 matches: turns 0, 1
        d1_turns = {m.turn_index for m in result.matches if m.quarter == "Q1"}
        assert d1_turns == {0, 1}, f"Q1 should match turns 0,1; got {d1_turns}"

        # Gate cascade: Q1 matched → Q2 searches ALL turns → finds 0,1,2
        d2_turns = {m.turn_index for m in result.matches if m.quarter == "Q2"}
        assert d2_turns == {0, 1, 2}, f"Q2 (gate cascade) should match turns 0,1,2; got {d2_turns}"

        # Gate cascade: Q1+Q2 both matched → Q3 searches ALL turns → finds 0,2,3
        d3_turns = {m.turn_index for m in result.matches if m.quarter == "Q3"}
        assert d3_turns == {0, 2, 3}, f"Q3 (gate cascade) should match turns 0,2,3; got {d3_turns}"

    @pytest.mark.asyncio
    async def test_cascade_first_dict_no_match_skips_second(self):
        """cascade=True: if Dict 1 matches nothing, Dict 2 is skipped (gate failed)."""
        dialog = _make_dialog([
            ("Клиент", "привет как дела"),  # no match for any dict
        ])

        dict1 = DictionaryNode(
            id="d1", name="Q1",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[],
        )
        dict2 = DictionaryNode(
            id="d2", name="Q2",
            conditions=[_make_condition("привет", word_distance=1, channel="CLIENT")],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[dict1, dict2],
            cascade=True,
        )

        # Dict 1 matches nothing → gate failed → Dict 2 is skipped
        assert result.total_matches == 0, (
            "With gate cascade, if Q1 has no matches, Q2 should be skipped entirely"
        )


# ═══════════════════════════════════════════════════════════════════════
# Hierarchy: child dict searches ALL turns if parent matched (GATE model)
# ═══════════════════════════════════════════════════════════════════════

class TestHierarchyChildGate:
    """Tests for hierarchical search: child dicts search ALL turns if parent matched.

    GATE model: If Q1 matched somewhere in the dialogue → Q2 searches ALL turns.
    If Q1 matched nowhere → Q2 is skipped entirely.
    This matches SmartLogger behavior: Q2 phrases appear in different turns than Q1.
    """

    @pytest.mark.asyncio
    async def test_child_searches_all_turns_when_parent_matched(self):
        """Q2 (child of Q1) searches ALL turns when Q1 matched somewhere.

        Dialog:
          Turn 0: "расторгнуть договор" — Q1 match only
          Turn 1: "отказываюсь диагностики" — Q2 match only (different turn!)
          Turn 2: "расторгнуть отказываюсь" — both match

        Gate model: Q1 matched in turn 0 → Q2 searches ALL turns → finds turn 1 AND turn 2.
        """
        dialog = _make_dialog([
            ("Клиент", "расторгнуть договор"),  # turn 0: Q1 match
            ("Клиент", "отказываюсь диагностики"),  # turn 1: Q2 match only (different turn!)
            ("Клиент", "расторгнуть отказываюсь"),  # turn 2: both match
        ])

        q2 = DictionaryNode(
            id="q2", name="Отказ от диагностики",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="CLIENT")],
            children=[],
        )
        q1 = DictionaryNode(
            id="q1", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[q2],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[q1],
            cascade=False,
        )

        # Q1 matches: turns 0, 2
        q1_turns = {m.turn_index for m in result.matches if m.quarter == "Риск расторжения"}
        assert q1_turns == {0, 2}, f"Q1 should match turns 0,2; got {q1_turns}"

        # Q2 (child of Q1): Q1 matched → Q2 searches ALL turns
        # Should find matches in turn 1 AND turn 2
        q2_turns = {m.turn_index for m in result.matches if m.quarter == "Отказ от диагностики"}
        assert 1 in q2_turns, "Q2 (child) should match turn 1 (Q2 phrase there, Q1 matched somewhere)"
        assert 2 in q2_turns, "Q2 (child) should match turn 2 (both Q1 and Q2 phrases there)"

    @pytest.mark.asyncio
    async def test_child_skipped_when_parent_no_match(self):
        """Q2 is skipped entirely if Q1 had no matches (gate failed)."""
        dialog = _make_dialog([
            ("Клиент", "отказываюсь диагностики"),  # Q2 phrase only, no Q1
        ])

        q2 = DictionaryNode(
            id="q2", name="Отказ от диагностики",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="CLIENT")],
            children=[],
        )
        q1 = DictionaryNode(
            id="q1", name="Риск расторжения",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[q2],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[q1],
            cascade=False,
        )

        # Q1 matches nothing → Q2 is skipped (gate failed)
        q2_matches = [m for m in result.matches if m.quarter == "Отказ от диагностики"]
        assert len(q2_matches) == 0, (
            "Q2 should be skipped when Q1 has no matches (gate failed)"
        )

    @pytest.mark.asyncio
    async def test_child_level_with_container_root(self):
        """Container root → Q1 → Q2: levels should be 1 and 2.

        GATE model: Q1 matched → Q2 searches ALL turns.
        """
        dialog = _make_dialog([
            ("Клиент", "расторгнуть отказываюсь"),
        ])

        q2 = DictionaryNode(
            id="q2", name="Q2",
            conditions=[_make_condition("отказываюсь", word_distance=1, channel="CLIENT")],
            children=[],
        )
        q1 = DictionaryNode(
            id="q1", name="Q1",
            conditions=[_make_condition("расторгнуть", word_distance=1, channel="CLIENT")],
            children=[q2],
        )
        root = DictionaryNode(
            id="root", name="Root",
            conditions=[],  # Container
            children=[q1],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        # Q1 should be level=1, Q2 should be level=2
        q1_matches = [m for m in result.matches if m.quarter == "Q1"]
        q2_matches = [m for m in result.matches if m.quarter == "Q2"]

        for m in q1_matches:
            assert m.word_distance_used == 1, f"Q1 should be level 1, got {m.word_distance_used}"
        for m in q2_matches:
            assert m.word_distance_used == 2, f"Q2 should be level 2, got {m.word_distance_used}"

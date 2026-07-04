"""Tests for build_phrase_logic_tree and evaluate_phrase_logic_tree (UI-2.6 N1/N15).

Covers acceptance criteria for the phrase_logic_tree wave:
  - Simple: A → PHRASE(A), evaluates True iff A matched
  - И:   A И B  → AND[PHRASE(A), PHRASE(B)], True iff both match
  - ИЛИ: A ИЛИ B → OR[PHRASE(A), PHRASE(B)], True iff any matches
  - НЕ:  НЕ A  → NOT[PHRASE(A)], True iff A NOT matched
  - Combination (precedence И > ИЛИ):
      A ИЛИ B И C → OR[PHRASE(A), AND[PHRASE(B), PHRASE(C)]]
  - Edge: empty phrase_groups → True (no conditions / gate open)
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import PhraseGroup
from app.services.logic_builder import build_phrase_logic_tree
from app.services.search import evaluate_phrase_logic_tree


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _pg(words: list[str], operator: str = "", is_negated: bool = False) -> PhraseGroup:
    return PhraseGroup(
        words=words,
        operator=operator,
        is_negated=is_negated,
    )


def _node_types(node) -> list[str]:
    """Flatten the tree to a list of node_types for shape assertions."""
    types = [node.node_type]
    for c in node.children:
        types.extend(_node_types(c))
    return types


# ═══════════════════════════════════════════════════════════════════════
# 1. Simple phrase
# ═══════════════════════════════════════════════════════════════════════


class TestSimplePhrase:
    def test_single_phrase_shape(self) -> None:
        """Single PhraseGroup A → PHRASE(A)."""
        tree = build_phrase_logic_tree([_pg(["отказ"])])
        assert tree.node_type == "PHRASE"
        assert tree.payload["text"] == "отказ"

    def test_single_phrase_evaluates_true_if_matched(self) -> None:
        groups = [_pg(["отказ"])]
        assert evaluate_phrase_logic_tree(groups, {"отказ"}) is True

    def test_single_phrase_evaluates_false_if_not_matched(self) -> None:
        groups = [_pg(["отказ"])]
        assert evaluate_phrase_logic_tree(groups, set()) is False
        assert evaluate_phrase_logic_tree(groups, {"что-то другое"}) is False


# ═══════════════════════════════════════════════════════════════════════
# 2. AND (И)
# ═══════════════════════════════════════════════════════════════════════


class TestAndCombination:
    def test_and_shape(self) -> None:
        """A И B → AND[PHRASE(A), PHRASE(B)]."""
        groups = [_pg(["отказ"]), _pg(["расторгнуть"], operator="AND")]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "AND"
        assert len(tree.children) == 2
        assert tree.children[0].node_type == "PHRASE"
        assert tree.children[1].node_type == "PHRASE"

    def test_and_evaluates_true_only_if_both_match(self) -> None:
        groups = [_pg(["отказ"]), _pg(["расторгнуть"], operator="AND")]
        assert evaluate_phrase_logic_tree(groups, {"отказ", "расторгнуть"}) is True
        assert evaluate_phrase_logic_tree(groups, {"отказ"}) is False
        assert evaluate_phrase_logic_tree(groups, {"расторгнуть"}) is False
        assert evaluate_phrase_logic_tree(groups, set()) is False

    def test_three_phrase_and_chain(self) -> None:
        groups = [
            _pg(["a"]),
            _pg(["b"], operator="AND"),
            _pg(["c"], operator="AND"),
        ]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "AND"
        assert len(tree.children) == 3
        assert evaluate_phrase_logic_tree(groups, {"a", "b", "c"}) is True
        assert evaluate_phrase_logic_tree(groups, {"a", "b"}) is False


# ═══════════════════════════════════════════════════════════════════════
# 3. OR (ИЛИ)
# ═══════════════════════════════════════════════════════════════════════


class TestOrCombination:
    def test_or_shape(self) -> None:
        """A ИЛИ B → OR[PHRASE(A), PHRASE(B)]."""
        groups = [_pg(["отказ"]), _pg(["расторгнуть"], operator="OR")]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "OR"
        assert len(tree.children) == 2

    def test_or_evaluates_true_if_any_matches(self) -> None:
        groups = [_pg(["отказ"]), _pg(["расторгнуть"], operator="OR")]
        assert evaluate_phrase_logic_tree(groups, {"отказ"}) is True
        assert evaluate_phrase_logic_tree(groups, {"расторгнуть"}) is True
        assert evaluate_phrase_logic_tree(groups, {"отказ", "расторгнуть"}) is True
        assert evaluate_phrase_logic_tree(groups, set()) is False
        assert evaluate_phrase_logic_tree(groups, {"другое"}) is False


# ═══════════════════════════════════════════════════════════════════════
# 4. NOT (НЕ)
# ═══════════════════════════════════════════════════════════════════════


class TestNotCombination:
    def test_not_shape(self) -> None:
        """НЕ A → NOT[PHRASE(A)]."""
        groups = [_pg(["исключение"], is_negated=True)]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "NOT"
        assert len(tree.children) == 1
        assert tree.children[0].node_type == "PHRASE"

    def test_not_evaluates_true_if_not_matched(self) -> None:
        groups = [_pg(["исключение"], is_negated=True)]
        assert evaluate_phrase_logic_tree(groups, set()) is True
        assert evaluate_phrase_logic_tree(groups, {"что-то"}) is True

    def test_not_evaluates_false_if_matched(self) -> None:
        groups = [_pg(["исключение"], is_negated=True)]
        assert evaluate_phrase_logic_tree(groups, {"исключение"}) is False


# ═══════════════════════════════════════════════════════════════════════
# 5. Combination with precedence (И > ИЛИ)
# ═══════════════════════════════════════════════════════════════════════


class TestPrecedence:
    def test_or_and_precedence_shape(self) -> None:
        """A ИЛИ B И C → OR[PHRASE(A), AND[PHRASE(B), PHRASE(C)]].

        И binds tighter than ИЛИ (same precedence rules as
        build_attribute_tree: NOT > AND > OR).
        """
        groups = [
            _pg(["a"]),
            _pg(["b"], operator="OR"),
            _pg(["c"], operator="AND"),
        ]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "OR"
        assert len(tree.children) == 2
        assert tree.children[0].node_type == "PHRASE"
        assert tree.children[1].node_type == "AND"
        assert len(tree.children[1].children) == 2

    def test_or_and_evaluates_correctly(self) -> None:
        """A OR B AND C: True iff (A) OR (B AND C)."""
        groups = [
            _pg(["a"]),
            _pg(["b"], operator="OR"),
            _pg(["c"], operator="AND"),
        ]
        # Only A → True
        assert evaluate_phrase_logic_tree(groups, {"a"}) is True
        # B and C → True
        assert evaluate_phrase_logic_tree(groups, {"b", "c"}) is True
        # A + B + C → True
        assert evaluate_phrase_logic_tree(groups, {"a", "b", "c"}) is True
        # Only B → False (need C too)
        assert evaluate_phrase_logic_tree(groups, {"b"}) is False
        # Only C → False
        assert evaluate_phrase_logic_tree(groups, {"c"}) is False
        # None → False
        assert evaluate_phrase_logic_tree(groups, set()) is False

    def test_or_and_or_chain(self) -> None:
        """A ИЛИ B И C ИЛИ D → OR[A, AND[B, C], D]."""
        groups = [
            _pg(["a"]),
            _pg(["b"], operator="OR"),
            _pg(["c"], operator="AND"),
            _pg(["d"], operator="OR"),
        ]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "OR"
        assert len(tree.children) == 3
        assert tree.children[1].node_type == "AND"
        # A alone → True
        assert evaluate_phrase_logic_tree(groups, {"a"}) is True
        # D alone → True
        assert evaluate_phrase_logic_tree(groups, {"d"}) is True
        # B+C → True
        assert evaluate_phrase_logic_tree(groups, {"b", "c"}) is True
        # B alone → False
        assert evaluate_phrase_logic_tree(groups, {"b"}) is False


# ═══════════════════════════════════════════════════════════════════════
# 6. NOT + AND/OR combination
# ═══════════════════════════════════════════════════════════════════════


class TestNotInCombination:
    def test_not_wraps_phrase_tightly(self) -> None:
        """A И НЕ B → AND[PHRASE(A), NOT[PHRASE(B)]]."""
        groups = [
            _pg(["a"]),
            _pg(["b"], operator="AND", is_negated=True),
        ]
        tree = build_phrase_logic_tree(groups)
        assert tree.node_type == "AND"
        assert len(tree.children) == 2
        assert tree.children[0].node_type == "PHRASE"
        assert tree.children[1].node_type == "NOT"

    def test_not_and_evaluates_correctly(self) -> None:
        """A И НЕ B: True iff A matched AND B NOT matched."""
        groups = [
            _pg(["a"]),
            _pg(["b"], operator="AND", is_negated=True),
        ]
        assert evaluate_phrase_logic_tree(groups, {"a"}) is True
        assert evaluate_phrase_logic_tree(groups, {"a", "b"}) is False
        assert evaluate_phrase_logic_tree(groups, {"b"}) is False
        assert evaluate_phrase_logic_tree(groups, set()) is False


# ═══════════════════════════════════════════════════════════════════════
# 7. Edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_phrase_groups_returns_true(self) -> None:
        """Empty phrase_groups → True (no conditions = gate open)."""
        assert evaluate_phrase_logic_tree([], set()) is True
        assert evaluate_phrase_logic_tree([], {"anything"}) is True

    def test_empty_phrase_groups_tree_shape(self) -> None:
        tree = build_phrase_logic_tree([])
        assert tree.node_type == "AND"
        assert tree.children == []

    def test_unknown_operator_defaults_to_and(self) -> None:
        """If operator is not 'AND'/'OR' (e.g. empty for non-first), default AND.

        The first group has operator=''. For subsequent groups with garbage
        operator strings, the parser falls back to AND.
        """
        groups = [
            _pg(["a"]),
            _pg(["b"], operator=""),  # empty for non-first → defaults to AND
        ]
        tree = build_phrase_logic_tree(groups)
        # Empty operator between groups → treated as AND (left-to-right chain)
        assert tree.node_type == "AND"

    def test_multi_word_phrase_text(self) -> None:
        """Multi-word phrase preserves joined text in payload."""
        groups = [_pg(["отказ", "от", "услуги"])]
        tree = build_phrase_logic_tree(groups)
        assert tree.payload["text"] == "отказ от услуги"
        assert evaluate_phrase_logic_tree(groups, {"отказ от услуги"}) is True
        assert evaluate_phrase_logic_tree(groups, {"другое"}) is False

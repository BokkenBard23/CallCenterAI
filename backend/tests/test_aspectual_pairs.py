"""Tests for _ASPECTUAL_PAIRS deduplication (IP-1.3).

Verifies that the _ASPECTUAL_PAIRS dictionary has no redundant
reverse-direction entries (i.e. no duplicate frozenset pairs).
"""

from __future__ import annotations

import pytest


def test_no_duplicate_aspectual_pairs():
    """Verify no duplicate frozenset pairs exist in _ASPECTUAL_PAIRS.

    Each unique pair {A, B} should appear exactly once in the dict.
    Having both A→B and B→A is redundant because _LEMMA_GROUPS
    already handles bidirectional lookup.
    """
    from app.services.morph_matcher import _ASPECTUAL_PAIRS

    pair_seen: set[frozenset] = set()
    duplicates: list[tuple[str, str]] = []

    for key, val in _ASPECTUAL_PAIRS.items():
        pair = frozenset({key, val})
        if pair in pair_seen:
            duplicates.append((key, val))
        else:
            pair_seen.add(pair)

    assert duplicates == [], (
        f"Found {len(duplicates)} duplicate pair(s) in _ASPECTUAL_PAIRS. "
        f"Each pair should appear only once (reverse direction is handled "
        f"by _LEMMA_GROUPS). Duplicates: {duplicates}"
    )


def test_aspectual_pairs_not_empty():
    """Verify _ASPECTUAL_PAIRS is not empty."""
    from app.services.morph_matcher import _ASPECTUAL_PAIRS

    assert len(_ASPECTUAL_PAIRS) > 0, "_ASPECTUAL_PAIRS should not be empty"


def test_aspectual_pairs_all_string_values():
    """Verify all keys and values are non-empty strings."""
    from app.services.morph_matcher import _ASPECTUAL_PAIRS

    for key, val in _ASPECTUAL_PAIRS.items():
        assert isinstance(key, str) and len(key) > 0, f"Invalid key: {key!r}"
        assert isinstance(val, str) and len(val) > 0, f"Invalid value for {key!r}: {val!r}"


def test_aspectual_pairs_keys_are_distinct():
    """Verify no duplicate Python dict keys (same string appears twice).

    Python silently keeps the last value for duplicate keys in dict
    literals, so this test catches accidental key duplication.
    """
    from app.services.morph_matcher import _ASPECTUAL_PAIRS

    # Re-read the source to detect Python-level key dedup
    import ast
    import inspect
    source = inspect.getsource(
        __import__("app.services.morph_matcher", fromlist=["morph_matcher"])
    )
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_ASPECTUAL_PAIRS":
                    dict_node = node.value
                    if isinstance(dict_node, ast.Dict):
                        keys = []
                        for k in dict_node.keys:
                            if isinstance(k, ast.Constant):
                                keys.append(k.value)
                        from collections import Counter
                        counts = Counter(keys)
                        dups = {k: v for k, v in counts.items() if v > 1}
                        assert dups == {}, (
                            f"Found {len(dups)} duplicate Python dict key(s). "
                            f"Python silently deduplicates, keeping only the last "
                            f"value. Duplicates: {dups}"
                        )


def test_lemma_groups_cover_all_pairs():
    """Verify _LEMMA_GROUPS covers all entries in _ASPECTUAL_PAIRS.

    Every key and value in _ASPECTUAL_PAIRS should have a lemma group.
    """
    from app.services.morph_matcher import _ASPECTUAL_PAIRS, _LEMMA_GROUPS

    for key, val in _ASPECTUAL_PAIRS.items():
        assert key in _LEMMA_GROUPS, f"Key {key!r} not in _LEMMA_GROUPS"
        assert val in _LEMMA_GROUPS, f"Value {val!r} not in _LEMMA_GROUPS"
        assert _LEMMA_GROUPS[key] == _LEMMA_GROUPS[val], (
            f"Key {key!r} (group {_LEMMA_GROUPS[key]}) and "
            f"value {val!r} (group {_LEMMA_GROUPS[val]}) "
            f"should be in the same lemma group"
        )


def test_same_lemma_after_dedup():
    """Verify same_lemma still works correctly after deduplication.

    Key bidirectional pairs should still match.
    """
    from app.services.morph_matcher import same_lemma

    # Perfective ↔ Imperfective pairs that must match
    assert same_lemma("перейти", "переходить"), "перейти ↔ переходить must match"
    assert same_lemma("переключить", "переключать"), "переключить ↔ переключать must match"
    assert same_lemma("отключить", "отключать"), "отключить ↔ отключать must match"
    assert same_lemma("подключить", "подключать"), "подключить ↔ подключать must match"
    assert same_lemma("расторгнуть", "расторгать"), "расторгнуть ↔ расторгать must match"
    assert same_lemma("отказаться", "отказываться"), "отказаться ↔ отказываться must match"
    assert same_lemma("купить", "покупать"), "купить ↔ покупать must match"
    assert same_lemma("решить", "решать"), "решить ↔ решать must match"

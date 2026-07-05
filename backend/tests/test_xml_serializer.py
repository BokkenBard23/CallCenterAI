"""Tests for app.services.xml_serializer — round-trip XML serialization.

Strategy:
  1. Parse canonical XML examples from docs/chat → DictionaryNode.
  2. Serialize back to bytes via serialize_dictionary_to_xml.
  3. Re-parse the serialized bytes → second DictionaryNode.
  4. Compare token streams (text, type, channel, word_distance) of
     the two trees — they must be token-equivalent.

  Also tests: idempotency (serialize(parse(serialize(x))) == serialize(x)).
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import List, Tuple

import pytest
from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import DictionaryNode, TokenModel
from app.services.xml_parser import parse_xml_bytes
from app.services.xml_serializer import (
    _conditions_to_tokens,
    serialize_dictionary_to_xml,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


_DOCS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "chat"
)


def _load_doc(name: str) -> bytes:
    path = os.path.join(_DOCS_DIR, name)
    with open(path, "rb") as f:
        return f.read()


def _token_stream(node: DictionaryNode) -> List[Tuple[str, str, str, str]]:
    """Flatten token sections of a DictionaryNode tree into comparable tuples."""
    out: List[Tuple[str, str, str, str]] = []
    if node.token_section:
        for t in node.token_section.tokens:
            out.append((t.text, t.type, t.channel, t.word_distance))
    for c in node.children:
        out.extend(_token_stream(c))
    return out


def _node_names(node: DictionaryNode) -> List[str]:
    """Flatten node names (depth-first) for structure comparison."""
    out = [node.name]
    for c in node.children:
        out.extend(_node_names(c))
    return out


# ═══════════════════════════════════════════════════════════════════════
# Round-trip: canonical examples
# ═══════════════════════════════════════════════════════════════════════


class TestRoundTripCanonical:
    def test_round_trip_main_example(self) -> None:
        """Parse → serialize → re-parse → token streams must match."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node1, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        ts1 = _token_stream(node1)

        xml2 = serialize_dictionary_to_xml(node1, pretty=True)
        node2, _ = asyncio.run(parse_xml_bytes(xml2, "b.xml"))
        ts2 = _token_stream(node2)

        assert ts1 == ts2, (
            f"Token streams differ: original={len(ts1)}, re-parsed={len(ts2)}"
        )

    def test_round_trip_preserves_node_names(self) -> None:
        xml = _load_doc("Пример XML словаря для llm.txt")
        node1, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        names1 = _node_names(node1)

        xml2 = serialize_dictionary_to_xml(node1, pretty=True)
        node2, _ = asyncio.run(parse_xml_bytes(xml2, "b.xml"))
        names2 = _node_names(node2)

        assert names1 == names2

    def test_round_trip_level_3_brackets_and_ne(self) -> None:
        """The Уровень 3 example exercises brackets, ИЛИ, и, НЕ, и не."""
        xml = _load_doc("Пример XML Уровень 3 (1b-2 (1b)).txt")
        node1, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        ts1 = _token_stream(node1)

        xml2 = serialize_dictionary_to_xml(node1, pretty=True)
        node2, _ = asyncio.run(parse_xml_bytes(xml2, "b.xml"))
        ts2 = _token_stream(node2)

        assert ts1 == ts2

    def test_idempotency(self) -> None:
        """serialize(parse(serialize(x))) == serialize(x) (byte-equivalent)."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node1, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        xml1 = serialize_dictionary_to_xml(node1, pretty=True)

        node2, _ = asyncio.run(parse_xml_bytes(xml1, "b.xml"))
        xml2 = serialize_dictionary_to_xml(node2, pretty=True)

        assert xml1 == xml2

    def test_root_has_empty_tokens(self) -> None:
        """Canonical: root <SpeechLabRequest> has empty <Tokens/>."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        serialized = serialize_dictionary_to_xml(node, pretty=True)
        root = etree.fromstring(serialized)
        tokens_elem = root.find("Tokens")
        assert tokens_elem is not None
        # Empty Tokens means no Token children
        assert tokens_elem.findall("Token") == []

    def test_root_has_requests_with_children(self) -> None:
        xml = _load_doc("Пример XML словаря для llm.txt")
        node, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        serialized = serialize_dictionary_to_xml(node, pretty=True)
        root = etree.fromstring(serialized)
        requests_elem = root.find("Requests")
        assert requests_elem is not None
        children = requests_elem.findall("SpeechLabRequest")
        remainder = requests_elem.findall("SpeechLabRemainderRequest")
        assert len(children) == 2  # Уровень 1a, Уровень 1b
        assert len(remainder) == 1  # Остаток

    def test_whitespace_always_wd_2(self) -> None:
        """Canonical fix B5: WHITESPACE always has WordDistance=2."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        serialized = serialize_dictionary_to_xml(node, pretty=True)
        root = etree.fromstring(serialized)
        # Walk all <Token> elements with Type=WHITESPACE and verify WD=2
        for tok in root.iter("Token"):
            type_elem = tok.find("Type")
            if type_elem is None or type_elem.text != "WHITESPACE":
                continue
            props = tok.find("Properties")
            assert props is not None
            assert props.get("WordDistance") == "2"

    def test_lexeme_terminal_any_wd_2(self) -> None:
        """LEXEME / TERMINAL always carry Channel=ANY, WordDistance=2."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        serialized = serialize_dictionary_to_xml(node, pretty=True)
        root = etree.fromstring(serialized)
        for tok in root.iter("Token"):
            type_elem = tok.find("Type")
            if type_elem is None:
                continue
            ttype = type_elem.text
            if ttype not in ("LEXEME", "TERMINAL"):
                continue
            props = tok.find("Properties")
            assert props is not None
            assert props.get("Channel") == "ANY"
            assert props.get("WordDistance") == "2"

    def test_last_update_time_7_digits(self) -> None:
        """B6 fix: LastUpdateTime has 7-digit fractional seconds."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        serialized = serialize_dictionary_to_xml(node, pretty=True)
        root = etree.fromstring(serialized)
        ss_elem = root.find("SavedState")
        assert ss_elem is not None
        ts = ss_elem.findtext("LastUpdateTime", "")
        # Format: YYYY-MM-DDTHH:MM:SS.{7digits}Z
        assert ts.endswith("Z")
        assert "." in ts
        frac = ts.split(".")[1].rstrip("Z")
        assert len(frac) == 7, f"Expected 7 fractional digits, got {len(frac)}: {ts}"

    def test_quoted_phrase_no_ws_between_quote_and_word(self) -> None:
        """Canonical exception: no WHITESPACE between `"` and WORD inside quotes."""
        xml = _load_doc("Пример XML словаря для llm.txt")
        node, _ = asyncio.run(parse_xml_bytes(xml, "a.xml"))
        ts1 = _token_stream(node)

        # Find a quoted phrase section (in Уровень 2 (ост) there's "Перешёл к вам")
        # Walk the stream and assert that immediately after a `"` TERMINAL
        # the next token is a WORD (NOT WHITESPACE).
        for i, (text, ttype, _, _) in enumerate(ts1):
            if ttype == "TERMINAL" and text == '"':
                # If next exists and it's a WORD, no WS — that's the open-quote case.
                if i + 1 < len(ts1):
                    next_text, next_type, _, _ = ts1[i + 1]
                    if next_type == "WORD":
                        # OK: this is the canonical exception
                        continue
                    if next_type == "WHITESPACE":
                        # Only acceptable if the next-next is also a TERMINAL (closing quote of empty phrase)
                        # or the WHITESPACE is a separator to another operand.
                        # For our canonical examples this should never happen for opening quotes.
                        # Closing quote: previous is WORD, this is `"`, next is WS or LEXEME.
                        # Distinguish open vs close by checking the previous token.
                        if i > 0 and ts1[i - 1][1] == "WORD":
                            continue
                        pytest.fail(
                            f"WHITESPACE between open quote and WORD at index {i}"
                        )


# ═══════════════════════════════════════════════════════════════════════
# _conditions_to_tokens (rebuild path)
# ═══════════════════════════════════════════════════════════════════════


class TestConditionsToTokens:
    def test_single_phrase(self) -> None:
        from app.models import DictionaryCondition
        cond = DictionaryCondition(
            text="hello world",
            word_distance=2,
            word_count=2,
            channel_constraint="CLIENT",
        )
        tokens = _conditions_to_tokens([cond])
        # No trailing WS, single phrase → 2 WORDs + 1 WS between
        assert len(tokens) == 3
        assert tokens[0].text == "hello"
        assert tokens[0].type == "WORD"
        assert tokens[0].channel == "CLIENT"
        assert tokens[1].type == "WHITESPACE"
        assert tokens[2].text == "world"

    def test_quoted_phrase(self) -> None:
        from app.models import DictionaryCondition
        cond = DictionaryCondition(
            text='привет мир',
            word_distance=2,
            word_count=2,
            channel_constraint="CLIENT",
            is_exact=True,
        )
        tokens = _conditions_to_tokens([cond])
        # Expected: " WORD WS WORD "
        assert tokens[0].type == "TERMINAL"
        assert tokens[0].text == '"'
        assert tokens[1].type == "WORD"
        assert tokens[2].type == "WHITESPACE"
        assert tokens[3].type == "WORD"
        assert tokens[4].type == "TERMINAL"
        assert tokens[4].text == '"'

    def test_phrase_with_word_distance_zero(self) -> None:
        from app.models import DictionaryCondition
        cond = DictionaryCondition(
            text="слово1 слово2",
            word_distance=0,
            word_count=2,
            channel_constraint="ANY",
        )
        tokens = _conditions_to_tokens([cond])
        # WORD tokens carry WD=0
        word_tokens = [t for t in tokens if t.type == "WORD"]
        assert all(t.word_distance == "0" for t in word_tokens)
        # Inter-word WHITESPACE still WD=2 (canonical)
        ws_tokens = [t for t in tokens if t.type == "WHITESPACE"]
        assert all(t.word_distance == "2" for t in ws_tokens)

    def test_negation_at_idx_0_emits_ne_lexeme(self) -> None:
        from app.models import DictionaryCondition
        cond = DictionaryCondition(
            text="привет",
            word_distance=2,
            word_count=1,
            channel_constraint="ANY",
            is_exception=True,
        )
        tokens = _conditions_to_tokens([cond])
        assert tokens[0].type == "LEXEME"
        assert tokens[0].text == "НЕ"
        assert tokens[1].type == "WHITESPACE"
        assert tokens[2].type == "WORD"
        assert tokens[2].text == "привет"

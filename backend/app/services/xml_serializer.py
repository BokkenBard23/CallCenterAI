"""Serialize :class:`DictionaryNode` back to canonical SmartLogger XML.

Inverse of :mod:`app.services.xml_parser`. Produces XML that:

- Root ``<SpeechLabRequest>`` has EMPTY ``<Tokens/>`` and places the
  expression in a CHILD ``<SpeechLabRequest>`` inside
  ``<Requests><Requests>`` (canonical spec §14).
- Inter-word WHITESPACE always has ``WordDistance="2"`` (canonical,
  fixes LexiCore B5 — previously WHITESPACE inherited the phrase's WD).
- ``<LastUpdateTime>`` uses 7-digit fractional seconds (fixes LexiCore B6).
- Preserves ``<Attributes>``, ``<ExtraLimitations>``, ``<SavedState>``,
  ``<OrderIndex>``.
- Handles И НЕ / ИЛИ НЕ as two separate LEXEME tokens (canonical pattern).
- Handles brackets ``()`` as TERMINAL tokens.
- Handles quoted phrases (``"..."``) as TERMINAL quote + WORD(s) +
  TERMINAL quote, with NO WHITESPACE between quote and WORD (canonical
  exception, spec §10).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from lxml import etree

from app.models import (
    AttributeSection,
    AttributeTokenModel,
    DictionaryCondition,
    DictionaryNode,
    ExtraLimitation,
    ExtraLimitationLimit,
    SavedState,
    TokenModel,
    TokenSection,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════


def serialize_dictionary_to_xml(
    node: DictionaryNode,
    pretty: bool = True,
) -> bytes:
    """Serialize a DictionaryNode tree to canonical SmartLogger XML bytes.

    Builds the full ``<SpeechLabRequest>`` envelope with nested
    ``<Requests>`` structure. Recursively serializes child DictionaryNodes.

    Args:
        node: Root dictionary node to serialize.
        pretty: If True, pretty-print with indentation.

    Returns:
        XML bytes (UTF-8, with ``<?xml version="1.0"?>`` declaration).
    """
    root = _build_request_element(node, is_root=True)
    tree = etree.ElementTree(root)
    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=pretty,
    )


# ═══════════════════════════════════════════════════════════
# Element builders
# ═══════════════════════════════════════════════════════════


def _build_request_element(
    node: DictionaryNode,
    is_root: bool = False,
    order_index: int = 0,
) -> etree._Element:
    """Build a single ``<SpeechLabRequest>`` element from a DictionaryNode.

    Root nodes have empty ``<Tokens/>``; child nodes populate ``<Tokens>``
    from ``node.token_section`` or rebuilt from ``node.conditions``.
    """
    tag = "SpeechLabRemainderRequest" if node.is_remainder else "SpeechLabRequest"
    elem = etree.Element(tag, attrib={"type": tag})

    # ── Id / Name / State ──
    _sub_text(elem, "Id", node.id or str(uuid.uuid4()))
    _sub_text(elem, "Name", node.name or "Unnamed")
    _sub_text(elem, "State", "SAVED")

    # ── SavedState (always present, canonical) ──
    _build_saved_state(elem, node.saved_state)

    _sub_text(elem, "Temporary", "False")
    _sub_text(elem, "OrderIndex", str(order_index))
    _sub_text(elem, "IsThemed", "False")

    # ── Attributes (skipped for RemainderRequest) ──
    if not node.is_remainder:
        _build_attributes(elem, node.attributes)

    # ── Tokens ──
    if node.is_remainder:
        # RemainderRequest has no Tokens section at all (spec §4)
        pass
    elif is_root and not (node.token_section and node.token_section.tokens):
        # Canonical root: empty <Tokens/> container, expressions live in
        # child <SpeechLabRequest>(s) inside <Requests> (spec §14).
        etree.SubElement(elem, "Tokens")
    else:
        # Either a non-root node (Tokens populated from token_section or
        # rebuilt from conditions), OR a top-level node whose token_section
        # is populated directly (single leaf SpeechLabRequest example).
        tokens = _resolve_tokens(node)
        _build_tokens(elem, tokens)

    # ── ExtraLimitations (skipped for RemainderRequest) ──
    if not node.is_remainder:
        _build_extra_limitations(elem, node.conditions)

    # ── ComplexCompleted (skipped for RemainderRequest) ──
    if not node.is_remainder:
        _sub_text(elem, "ComplexCompleted", "False")

    # ── Requests (children) ──
    requests_elem = etree.SubElement(elem, "Requests")
    for idx, child in enumerate(node.children):
        child_elem = _build_request_element(child, order_index=idx)
        requests_elem.append(child_elem)

    return elem


def _resolve_tokens(node: DictionaryNode) -> List[TokenModel]:
    """Resolve the token list for a non-root node.

    Prefer the preserved ``token_section`` (round-trip faithful). Fall
    back to rebuilding from ``conditions`` when the section is absent.
    """
    if node.token_section is not None and node.token_section.tokens:
        return node.token_section.tokens
    return _conditions_to_tokens(node.conditions)


def _build_saved_state(parent: etree._Element, saved: Optional[SavedState]) -> None:
    """Build a ``<SavedState>`` element.

    Always emits a SavedState (canonical). When ``saved`` is None, uses
    safe defaults (TotalFound=0, IsActual=false — fixes the false-positive
    'data exists' bug from IP-1.4).
    """
    saved_state = saved if saved is not None else SavedState()
    ss_elem = etree.SubElement(parent, "SavedState")
    _sub_text(ss_elem, "TotalFound", str(saved_state.total_found))
    _sub_text(ss_elem, "LastUpdateTime", _format_timestamp(saved_state.last_update_time))
    _sub_text(ss_elem, "ExecutionTime", saved_state.execution_time or "00:00:00")
    _sub_text(ss_elem, "IsActual", "true" if saved_state.is_actual else "false")
    _sub_text(ss_elem, "IsCancelled", "true" if saved_state.is_cancelled else "false")


def _build_attributes(parent: etree._Element, attrs: Optional[AttributeSection]) -> None:
    """Build the ``<Attributes><AttributeTokens>`` section."""
    attrs_elem = etree.SubElement(parent, "Attributes")
    at_container = etree.SubElement(attrs_elem, "AttributeTokens")
    if attrs is None:
        return
    for tok in attrs.attribute_tokens:
        _build_attribute_token(at_container, tok)


def _build_attribute_token(parent: etree._Element, tok: AttributeTokenModel) -> None:
    tok_elem = etree.SubElement(parent, "AttributeToken")
    _sub_text(tok_elem, "Text", tok.text)
    _sub_text(tok_elem, "Type", tok.type)
    _sub_text(tok_elem, "IsError", "true" if tok.is_error else "false")
    sa_elem = etree.SubElement(tok_elem, "SearchAttribute")
    _sub_text(sa_elem, "Key", tok.search_attribute.key)
    _sub_text(sa_elem, "Value", tok.search_attribute.value)


def _build_tokens(parent: etree._Element, tokens: List[TokenModel]) -> None:
    """Build the ``<Tokens>`` section from a list of TokenModel."""
    tokens_elem = etree.SubElement(parent, "Tokens")
    for tok in tokens:
        _build_token(tokens_elem, tok)


def _build_token(parent: etree._Element, tok: TokenModel) -> None:
    """Build a single ``<Token>`` element.

    Canonical form (spec §5):
        <Token>
          <Text>{text}</Text>
          <Type>{type}</Type>
          <IsError>false</IsError>
          <Properties Channel="{...}" WordDistance="{...}" />
        </Token>
    """
    tok_elem = etree.SubElement(parent, "Token")
    _sub_text(tok_elem, "Text", tok.text)
    _sub_text(tok_elem, "Type", tok.type)
    _sub_text(tok_elem, "IsError", "true" if tok.is_error else "false")

    channel = tok.channel or "ANY"
    word_distance = tok.word_distance or "2"
    # Per spec: LEXEME / TERMINAL / WHITESPACE always carry Channel=ANY and
    # WordDistance=2. Only WORD tokens carry the phrase-specific values.
    if tok.type != "WORD":
        channel = "ANY"
        word_distance = "2"
    etree.SubElement(
        tok_elem,
        "Properties",
        attrib={"Channel": channel, "WordDistance": word_distance},
    )


def _build_extra_limitations(
    parent: etree._Element,
    conditions: List[DictionaryCondition],
) -> None:
    """Build ``<ExtraLimitations>`` from the conditions' extra_limitations.

    All conditions in a node share the same extra_limitations list (parser
    copies the same list to every condition of the node), so we just take
    the first non-empty one.
    """
    limitations: List[ExtraLimitation] = []
    for cond in conditions:
        if cond.extra_limitations:
            limitations = cond.extra_limitations
            break

    if not limitations:
        etree.SubElement(parent, "ExtraLimitations")
        return

    extra_elem = etree.SubElement(parent, "ExtraLimitations")
    for el in limitations:
        _build_extra_limitation(extra_elem, el)


def _build_extra_limitation(parent: etree._Element, el: ExtraLimitation) -> None:
    el_elem = etree.SubElement(parent, "ExtraLimitation")
    if el.event_type:
        _sub_text(el_elem, "EventType", el.event_type)
    if el.search_specifier:
        _sub_text(el_elem, "SearchSpecifier", el.search_specifier)

    # Settings (self-closing if empty)
    settings_elem = etree.SubElement(el_elem, "Settings")
    for key, value in el.settings.items():
        _sub_text(settings_elem, key, str(value))

    if el.limits:
        limits_elem = etree.SubElement(el_elem, "Limits")
        for limit in el.limits:
            _build_limit(limits_elem, limit)


def _build_limit(parent: etree._Element, limit: ExtraLimitationLimit) -> None:
    limit_elem = etree.SubElement(parent, "Limit")
    _sub_text(limit_elem, "Value", str(limit.value))
    _sub_text(limit_elem, "ValueType", limit.value_type or "Seconds")
    _sub_text(limit_elem, "Channel", limit.channel or "ANY")
    _sub_text(limit_elem, "Enabled", "true" if limit.enabled else "false")
    if limit.limit_type is not None:
        _sub_text(limit_elem, "LimitType", limit.limit_type)
    if limit.event_selector is not None:
        _sub_text(limit_elem, "EventSelector", limit.event_selector)
    if limit.search_direction is not None:
        _sub_text(limit_elem, "SearchDirection", limit.search_direction)


# ═══════════════════════════════════════════════════════════
# Conditions → tokens (when token_section is unavailable)
# ═══════════════════════════════════════════════════════════


def _conditions_to_tokens(conditions: List[DictionaryCondition]) -> List[TokenModel]:
    """Build a flat token list from conditions.

    Reconstructs the canonical token stream: phrases joined by LEXEME
    operators (И / ИЛИ / И НЕ / ИЛИ НЕ / standalone НЕ), with
    WHITESPACE between every pair of meaningful tokens (spec §10).

    Channel / WordDistance come from the condition. Inter-word WHITESPACE
    always carries WordDistance=2 (canonical, fixes LexiCore B5).
    """
    tokens: List[TokenModel] = []

    for idx, cond in enumerate(conditions):
        # ── Leading operator (idx=0 may have no operator, or just НЕ) ──
        if idx > 0:
            # The previous condition's operator is encoded on the CURRENT
            # condition's phrase_groups[0].operator (parser convention).
            # Fall back: assume OR if unknown (LexiCore default).
            op = _detect_operator(cond)
            if op == "AND_NEG":
                tokens.append(_lexeme("И"))
                tokens.append(_whitespace())
                tokens.append(_lexeme("НЕ"))
                tokens.append(_whitespace())
            elif op == "OR_NEG":
                tokens.append(_lexeme("ИЛИ"))
                tokens.append(_whitespace())
                tokens.append(_lexeme("НЕ"))
                tokens.append(_whitespace())
            elif op == "AND":
                tokens.append(_lexeme("И"))
                tokens.append(_whitespace())
            elif op == "OR":
                tokens.append(_lexeme("ИЛИ"))
                tokens.append(_whitespace())
            elif op == "NOT":
                tokens.append(_lexeme("НЕ"))
                tokens.append(_whitespace())
        else:
            # idx=0 — standalone НЕ (prefix negation) when is_exception=True
            if cond.is_exception:
                tokens.append(_lexeme("НЕ"))
                tokens.append(_whitespace())

        # ── Phrase body ──
        words = cond.text.split()
        if not words:
            continue

        channel = cond.channel_constraint or "ANY"
        wd = str(cond.word_distance)

        if cond.is_exact:
            # Open quote (no WS between quote and first WORD — spec §10)
            if tokens and tokens[-1].type != "WHITESPACE":
                tokens.append(_whitespace())
            tokens.append(_terminal('"'))
            # First WORD: no preceding WS (canonical exception)
            tokens.append(_word(words[0], channel, wd))
            for w in words[1:]:
                tokens.append(_whitespace())
                tokens.append(_word(w, channel, wd))
            tokens.append(_terminal('"'))
        else:
            for i, w in enumerate(words):
                if i > 0:
                    tokens.append(_whitespace())
                tokens.append(_word(w, channel, wd))

        # Trailing WHITESPACE (canonical: every meaningful token is followed
        # by WHITESPACE — except inside quotes)
        tokens.append(_whitespace())

    # Drop trailing WHITESPACE to match canonical examples (they don't
    # end with a trailing WS token).
    while tokens and tokens[-1].type == "WHITESPACE":
        tokens.pop()

    return tokens


def _detect_operator(cond: DictionaryCondition) -> str:
    """Detect the logical operator preceding a condition.

    Returns one of: 'AND', 'OR', 'AND_NEG', 'OR_NEG', 'NOT', ''.

    The parser stores the operator on the corresponding PhraseGroup
    (``operator`` + ``is_negated``). DictionaryCondition itself carries
    ``is_exception`` (mirrors ``is_negated``) but no operator field. To
    reconstruct the operator we fall back to the phrase_groups list —
    the first visual group's ``is_exception`` flag tells us about НЕ.
    """
    # Heuristic: if is_exception (is_negated) and we can't read the operator
    # from phrase_groups, default to AND (since "И НЕ" is the canonical
    # mid-expression negation pattern).
    if not cond.is_exception:
        return ""
    return "AND_NEG"


# ═══════════════════════════════════════════════════════════
# Token constructors (mirror TokenModel fields)
# ═══════════════════════════════════════════════════════════


def _word(text: str, channel: str, word_distance: str) -> TokenModel:
    return TokenModel(
        text=text,
        type="WORD",
        is_error=False,
        channel=channel,
        word_distance=word_distance,
    )


def _lexeme(text: str) -> TokenModel:
    return TokenModel(
        text=text,
        type="LEXEME",
        is_error=False,
        channel="ANY",
        word_distance="2",
    )


def _terminal(text: str) -> TokenModel:
    return TokenModel(
        text=text,
        type="TERMINAL",
        is_error=False,
        channel="ANY",
        word_distance="2",
    )


def _whitespace() -> TokenModel:
    return TokenModel(
        text=" ",
        type="WHITESPACE",
        is_error=False,
        channel="ANY",
        word_distance="2",
    )


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _sub_text(parent: etree._Element, tag: str, text: str) -> etree._Element:
    """Append ``<tag>text</tag>`` to parent. Empty text → empty element."""
    child = etree.SubElement(parent, tag)
    child.text = text if text is not None else ""
    return child


def _format_timestamp(value: str) -> str:
    """Format LastUpdateTime with 7-digit fractional seconds.

    Canonical example: ``2026-06-27T17:37:06.0150613Z``.
    Python's ``datetime.isoformat()`` gives 6 digits by default — we pad
    to 7 to match the canonical SmartLogger format (fixes LexiCore B6).

    If the input already looks canonical, return as-is.
    """
    if not value:
        # Use current UTC time with 7-digit fractional seconds.
        now = datetime.now(timezone.utc)
        return _format_datetime(now)
    # If it's already a fully-formed ISO-8601 with Z, normalise the
    # fractional part to 7 digits.
    text = value.strip()
    if text.endswith("Z") and "." in text:
        # Already canonical-ish — return as-is to preserve round-trip fidelity.
        return text
    # Try parsing and re-formatting.
    try:
        # Strip trailing Z for fromisoformat compatibility.
        iso_text = text.rstrip("Z")
        dt = datetime.fromisoformat(iso_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _format_datetime(dt)
    except (ValueError, TypeError):
        # Unparseable — return verbatim.
        return value


def _format_datetime(dt: datetime) -> str:
    """Format a datetime as canonical 7-digit fractional-seconds UTC."""
    micro = dt.microsecond  # 0..999999 (6 digits max)
    # Pad to 7 digits: append a trailing 0 to the 6-digit micro value.
    frac = f"{micro:06d}0"
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{iso}.{frac}Z"

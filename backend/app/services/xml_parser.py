"""XML dictionary parser service.

Parses SpeechLabRequest XML dictionaries used for dialogue analysis.

CRITICAL RULES (from SmartLogger XML spec [4]):
  - Quotes fix ONLY morphology (exact word form), NOT word order
  - Word order is ALWAYS free (both with and without quotes)
  - WordDistance controls intermediate words allowed between phrase words
  - WordDistance=0 is VALID — means no intermediate words (NOT a fallback)
  - НЕ (LEXEME, uppercase) is a negation OPERATOR — NOT a word
  - не (WORD, lowercase) is a regular search word — part of the phrase
  - All words in a phrase have the SAME Channel (CLIENT/OPERATOR/ANY)
  - Channel CLIENT+OPERATOR in one phrase is impossible per spec [4]

KEY CHANGES from original:
  1. Removed WD=0→2 substitution (WD=0 is valid) [1][2][4]
  2. Fixed НЕ-detection: uses pg.is_negated from logic_builder, NOT words[0] [1][2][4]
  3. Moved _extract_nested_phrases() outside the loop (O(n+m) not O(n×m)) [1]
  4. _extract_nested_phrases() now splits by ALL LEXEME separators [1][2]
  5. Removed dead code: _PHRASE_SEPARATORS, _resolve_channel(), _parse_properties() [1][2]
  6. Removed duplicate seen_phrases check (now in logic_builder.detect_warnings) [1][2]
  7. word_count = len(pg.words) instead of re-tokenizing [1]
  8. Simplified channel resolution (impossible CLIENT+OPERATOR case removed) [4]
  9. async functions use asyncio.to_thread for CPU-bound XML parsing [1]
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Set, Tuple

from lxml import etree

from app.models import (
    AttributeSection,
    AttributeTokenModel,
    DictionaryCondition,
    DictionaryNode,
    DictionaryValidation,
    DisplayToken,
    LogicNode,
    PhraseGroup,
    SavedState,
    SearchAttribute,
    TokenModel,
    TokenSection,
)
from app.services.logic_builder import (
    _ALL_LEXEME_SEPARATORS,
    build_attribute_tree,
    build_phrase_groups,
    detect_warnings,
)

logger = logging.getLogger(__name__)

# Valid channel values from XML Properties
_VALID_CHANNELS = {"CLIENT", "OPERATOR", "ANY"}

# LEXEME tokens that produce DisplayToken(type=LEXEME) for frontend
_LEXEME_KEYWORDS = {"ИЛИ", "OR", "И", "AND", "НЕ", "NOT"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def parse_xml_bytes(
    xml_bytes: bytes, filename: str
) -> Tuple[DictionaryNode, DictionaryValidation]:
    """Parse XML dictionary bytes into a DictionaryNode tree.

    Uses asyncio.to_thread to avoid blocking the event loop
    during CPU-bound lxml parsing.
    """
    try:
        tree = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Invalid XML in '{filename}': {exc}") from exc

    return await asyncio.to_thread(
        _parse_speech_lab_request, tree, filename, None, False
    )


async def parse_xml_file(
    file_path: str, filename: Optional[str] = None
) -> Tuple[DictionaryNode, DictionaryValidation]:
    """Parse an XML dictionary file by path."""
    try:
        tree = etree.parse(file_path)
        root = tree.getroot()
    except (etree.XMLSyntaxError, OSError) as exc:
        raise ValueError(
            f"Cannot parse XML file '{filename or file_path}': {exc}"
        ) from exc

    return await asyncio.to_thread(
        _parse_speech_lab_request, root, filename or file_path, None, False
    )


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------


def _parse_bool(text: Optional[str]) -> bool:
    if not text:
        return False
    return text.strip().lower() == "true"


def _get_text(element: etree._Element, tag: str) -> Optional[str]:
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _get_text_or_empty(element: etree._Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _get_local_tag(elem: etree._Element) -> str:
    """Get local tag name, stripping namespace if present."""
    return (
        etree.QName(elem.tag).localname if "}" in elem.tag else elem.tag
    )


# ---------------------------------------------------------------------------
# SavedState, AttributeSection, TokenSection parsing
# ---------------------------------------------------------------------------


def _parse_saved_state(parent: etree._Element) -> Optional[SavedState]:
    ss_elem = parent.find("SavedState")
    if ss_elem is None:
        return None
    return SavedState(
        total_found=int(_get_text_or_empty(ss_elem, "TotalFound") or "0"),
        last_update_time=_get_text_or_empty(ss_elem, "LastUpdateTime"),
        execution_time=_get_text_or_empty(ss_elem, "ExecutionTime"),
        is_actual=_parse_bool(
            _get_text_or_empty(ss_elem, "IsActual") or "false"
        ),
        is_cancelled=_parse_bool(
            _get_text_or_empty(ss_elem, "IsCancelled") or "false"
        ),
    )


def _parse_search_attribute(at_elem: etree._Element) -> SearchAttribute:
    sa_elem = at_elem.find("SearchAttribute")
    if sa_elem is None:
        return SearchAttribute(key="", value="")
    return SearchAttribute(
        key=_get_text_or_empty(sa_elem, "Key"),
        value=_get_text_or_empty(sa_elem, "Value"),
    )


def _parse_attribute_section(parent: etree._Element) -> AttributeSection:
    attrs_elem = parent.find("Attributes")
    if attrs_elem is None:
        return AttributeSection()
    at_container = attrs_elem.find("AttributeTokens")
    if at_container is None:
        return AttributeSection()
    tokens: List[AttributeTokenModel] = []
    for at_elem in at_container.findall("AttributeToken"):
        token = AttributeTokenModel(
            text=_get_text_or_empty(at_elem, "Text"),
            type=_get_text_or_empty(at_elem, "Type") or "ATTRIBUTE",
            search_attribute=_parse_search_attribute(at_elem),
            is_error=_parse_bool(
                _get_text_or_empty(at_elem, "IsError") or "false"
            ),
        )
        tokens.append(token)
    return AttributeSection(attribute_tokens=tokens)


def _parse_token_section(parent: etree._Element) -> TokenSection:
    tokens_elem = parent.find("Tokens")
    if tokens_elem is None:
        return TokenSection()
    tokens: List[TokenModel] = []
    for tok_elem in tokens_elem.findall("Token"):
        props = tok_elem.find("Properties")
        channel = ""
        word_distance = ""
        if props is not None:
            channel = props.get("Channel", "")
            word_distance = props.get("WordDistance", "")
            if not channel:
                ch_elem = props.find("Channel")
                if ch_elem is not None and ch_elem.text:
                    channel = ch_elem.text.strip()
            if not word_distance:
                wd_elem = props.find("WordDistance")
                if wd_elem is not None and wd_elem.text:
                    word_distance = wd_elem.text.strip()
        tokens.append(
            TokenModel(
                text=_get_text_or_empty(tok_elem, "Text"),
                type=_get_text_or_empty(tok_elem, "Type") or "WORD",
                is_error=_parse_bool(
                    _get_text_or_empty(tok_elem, "IsError") or "false"
                ),
                channel=channel,
                word_distance=word_distance,
            )
        )
    return TokenSection(tokens=tokens)


# ---------------------------------------------------------------------------
# Main parsing logic
# ---------------------------------------------------------------------------


_MAX_RECURSION_DEPTH = 20


def _parse_speech_lab_request(
    element: etree._Element,
    filename: str,
    parent_name: Optional[str] = None,
    is_remainder: bool = False,
    _depth: int = 0,
) -> Tuple[DictionaryNode, DictionaryValidation]:
    """Parse a single <SpeechLabRequest> element recursively.

    Added _depth parameter to prevent infinite recursion on malformed XML.
    """
    if _depth > _MAX_RECURSION_DEPTH:
        raise ValueError(
            f"Maximum recursion depth ({_MAX_RECURSION_DEPTH}) exceeded "
            f"while parsing '{filename}'"
        )

    dict_id = _get_text(element, "Id") or uuid.uuid4().hex[:12]
    dict_name = _get_text(element, "Name") or "Unnamed"

    parent_id_text = _get_text(element, "parent_id")
    if parent_id_text:
        parent_name = parent_id_text.strip()

    saved_state = _parse_saved_state(element)
    attribute_section = _parse_attribute_section(element)
    token_section = _parse_token_section(element)

    phrase_groups = build_phrase_groups(token_section)

    attribute_tree: Optional[LogicNode] = None
    has_meaningful_attrs = any(
        t.type == "ATTRIBUTE" for t in attribute_section.attribute_tokens
    )
    if has_meaningful_attrs:
        attribute_tree = build_attribute_tree(attribute_section)

    conditions, condition_warnings = _parse_tokens_enriched(
        element, phrase_groups
    )

    children: List[DictionaryNode] = []
    child_warnings: List[str] = []
    requests_elem = element.find("Requests")
    if requests_elem is not None:
        for child_elem in requests_elem:
            tag = _get_local_tag(child_elem)
            if tag not in (
                "SpeechLabRequest",
                "SpeechLabRemainderRequest",
            ):
                continue
            child_is_remainder = tag == "SpeechLabRemainderRequest"
            try:
                child_node, child_val = _parse_speech_lab_request(
                    child_elem,
                    filename,
                    parent_name=dict_name,
                    is_remainder=child_is_remainder,
                    _depth=_depth + 1,
                )
                children.append(child_node)
                child_warnings.extend(child_val.warnings)
            except ValueError as exc:
                child_warnings.append(
                    f"Failed to parse child dictionary: {exc}"
                )
            except Exception as exc:
                child_warnings.append(
                    f"Unexpected error parsing child dictionary: {exc}"
                )

    logic_warnings = detect_warnings(
        attribute_section, token_section, phrase_groups
    )

    all_warnings = condition_warnings + child_warnings
    for w in logic_warnings:
        if w not in all_warnings:
            all_warnings.append(w)

    node = DictionaryNode(
        id=dict_id,
        name=dict_name,
        parent_name=parent_name,
        conditions=conditions,
        children=children,
        condition_count=len(conditions),
        has_children=len(children) > 0,
        children_count=len(children),
        saved_state=saved_state,
        attributes=(
            attribute_section if attribute_section.attribute_tokens else None
        ),
        is_remainder=is_remainder,
        phrase_groups=phrase_groups,
        attribute_tree=attribute_tree,
        token_section=token_section if token_section.tokens else None,
    )

    validation = _validate_node(node, all_warnings)
    return node, validation


# ---------------------------------------------------------------------------
# Token parsing (enriched)
# ---------------------------------------------------------------------------


def _parse_tokens_enriched(
    element: etree._Element,
    phrase_groups: List[PhraseGroup],
) -> Tuple[List[DictionaryCondition], List[str]]:
    """Convert PhraseGroups into DictionaryConditions.

    KEY CHANGES from original [1][2][4]:
      1. WordDistance=0 is preserved (no fallback to 2)
      2. is_exception uses pg.is_negated from logic_builder (not words[0])
      3. _extract_nested_phrases() called ONCE before the loop
      4. word_count = len(pg.words) (no re-tokenization)
    """
    conditions: List[DictionaryCondition] = []
    warnings: List[str] = []

    if not phrase_groups:
        return conditions, warnings

    without_list = _parse_without_list(element)

    # Compute once, share across all conditions of this node
    nested_phrases = _extract_nested_phrases(element)
    all_group_words: List[List[str]] = [
        pg.words for pg in phrase_groups if pg.words
    ]

    for pg in phrase_groups:
        if not pg.words:
            warnings.append("Пустая фразовая группа")
            continue

        phrase_text = " ".join(pg.words)

        # Channel from PhraseGroup — first non-empty value [4]
        channel = pg.channel.upper() if pg.channel else "ANY"
        if channel not in _VALID_CHANNELS:
            channel = "ANY"

        # WordDistance: 0 is VALID — do NOT substitute with 2 [1][2][4]
        word_distance = pg.word_distance

        # word_count = len(pg.words) — no need to re-tokenize [1]
        word_count = len(pg.words)

        # НЕ-detection: use is_negated from logic_builder [1][2][4]
        # Do NOT check words[0].upper() — that confuses WORD "не" with LEXEME "НЕ"
        is_exception = getattr(pg, "is_negated", False)

        exception_phrases: List[str] = []
        if is_exception:
            exception_phrases.append(phrase_text)

        conditions.append(
            DictionaryCondition(
                text=phrase_text,
                word_distance=word_distance,
                word_count=word_count,
                channel_constraint=channel,
                without_list=without_list,
                is_exact=pg.is_exact,
                phrase_groups=list(all_group_words),
                nested_phrases=nested_phrases,
                is_exception=is_exception,
                exception_phrases=exception_phrases,
            )
        )

    return conditions, warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_nested_phrases(element: etree._Element) -> List[str]:
    """Extract phrase texts from child SpeechLabRequest <Tokens> sections.

    FIXED: Now splits by ALL LEXEME separators (И, ИЛИ, НЕ, AND, OR, NOT),
    not just ИЛИ/OR. Uses _ALL_LEXEME_SEPARATORS from logic_builder.

    Called ONCE before the loop in _parse_tokens_enriched() (not inside).

    Args:
        element: The SpeechLabRequest XML element.

    Returns:
        List of phrase text strings from direct child dictionaries.
    """
    nested: List[str] = []
    requests_elem = element.find("Requests")
    if requests_elem is None:
        return nested

    for child_elem in requests_elem:
        tag = _get_local_tag(child_elem)
        if tag not in ("SpeechLabRequest", "SpeechLabRemainderRequest"):
            continue

        tokens_elem = child_elem.find("Tokens")
        if tokens_elem is None:
            continue

        phrase_words: List[str] = []
        for token_elem in tokens_elem.findall("Token"):
            token_type = _get_text(token_elem, "Type") or ""
            text = _get_text(token_elem, "Text") or ""

            if token_type == "WORD" and text:
                phrase_words.append(text)
            elif token_type == "LEXEME" and text.upper() in _ALL_LEXEME_SEPARATORS:
                # Flush current phrase before starting new group
                if phrase_words:
                    nested.append(" ".join(phrase_words))
                    phrase_words = []
        if phrase_words:
            nested.append(" ".join(phrase_words))

    return nested


def _parse_without_list(element: etree._Element) -> List[str]:
    """Parse <ExtraLimitations> for WITHOUT phrases.

    FIXED: Now splits by ALL LEXEME separators within ExtraLimitations,
    not just accumulating all WORD tokens into one string.

    Args:
        element: The SpeechLabRequest element.

    Returns:
        List of WITHOUT phrase strings.
    """
    without_list: List[str] = []
    extra_elem = element.find("ExtraLimitations")
    if extra_elem is None:
        return without_list

    for limitation in extra_elem.findall("ExtraLimitation"):
        tokens_elem = limitation.find("Tokens")
        if tokens_elem is None:
            continue

        phrase_words: List[str] = []
        for token_elem in tokens_elem.findall("Token"):
            text = _get_text(token_elem, "Text") or ""
            token_type = _get_text(token_elem, "Type") or ""

            if token_type == "WORD" and text:
                phrase_words.append(text)
            elif token_type == "LEXEME" and text.upper() in _ALL_LEXEME_SEPARATORS:
                # Flush: each LEXEME-separated group is a separate WITHOUT phrase
                if phrase_words:
                    without_list.append(" ".join(phrase_words))
                    phrase_words = []

        if phrase_words:
            without_list.append(" ".join(phrase_words))

    return without_list


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_node(
    node: DictionaryNode,
    additional_warnings: List[str],
) -> DictionaryValidation:
    """Validate a parsed DictionaryNode.

    Checks:
    - At least one WORD token condition present (unless has children or is remainder)
    - No cycles in parent-child hierarchy
    - Valid channel values

    Args:
        node: The parsed dictionary node.
        additional_warnings: Warnings from parsing.

    Returns:
        DictionaryValidation with results.
    """
    errors: List[str] = []
    warnings: List[str] = list(additional_warnings)

    # Check for conditions (remainder nodes may have no conditions)
    if node.condition_count == 0 and not node.has_children and not node.is_remainder:
        errors.append(
            f"Dictionary '{node.name}' has no search conditions (WORD tokens) "
            "and no child dictionaries"
        )

    # Check for cycles in hierarchy
    cycle_names = _detect_cycles(node)
    if cycle_names:
        errors.append(
            f"Cycle detected in dictionary hierarchy: {' → '.join(cycle_names)}"
        )

    # Validate channel values
    for cond in node.conditions:
        if cond.channel_constraint not in _VALID_CHANNELS:
            errors.append(
                f"Invalid channel '{cond.channel_constraint}' in phrase '{cond.text}'"
            )

    return DictionaryValidation(
        valid=len(errors) == 0,
        warnings=warnings,
        errors=errors,
    )


def _detect_cycles(node: DictionaryNode) -> List[str]:
    """Detect cycles in the parent-child hierarchy using DFS.

    Uses node ID (unique GUID) for identity — not name.
    Fixed: uses ID-based path tracking to avoid ValueError
    when names are duplicated.

    Args:
        node: Root node to start from.

    Returns:
        List of names forming a cycle, or empty if no cycle.
    """
    visited: set = set()
    in_stack: set = set()
    path_names: List[str] = []
    path_ids: List[str] = []

    def dfs(current: DictionaryNode) -> List[str]:
        if current.id in in_stack:
            # Find cycle start by ID, not by name
            try:
                cycle_start = path_ids.index(current.id)
            except ValueError:
                return [current.name]
            return path_names[cycle_start:] + [current.name]

        if current.id in visited:
            return []

        visited.add(current.id)
        in_stack.add(current.id)
        path_names.append(current.name)
        path_ids.append(current.id)

        for child in current.children:
            result = dfs(child)
            if result:
                return result

        path_names.pop()
        path_ids.pop()
        in_stack.discard(current.id)
        return []

    return dfs(node)


# ---------------------------------------------------------------------------
# DisplayToken conversion (SpeechLab UI)
# ---------------------------------------------------------------------------


def resolve_phrase_channel(channels: set) -> str:
    """Determine the channel for a group of WORD tokens.

    Per SmartLogger spec [4]: all words in a phrase have the SAME channel.
    Just take any non-empty, non-ANY value.

    Args:
        channels: Set of channel strings from WORD token Properties.

    Returns:
        Resolved channel: "OPERATOR", "CLIENT", or "ANY".
    """
    if not channels:
        return "ANY"
    for ch in channels:
        if ch and ch not in ("ANY", ""):
            return ch
    return "ANY"


def group_into_display_tokens(token_section: TokenSection) -> List[DisplayToken]:
    """Convert a TokenSection into a list of DisplayTokens for frontend rendering.

    Algorithm:
      1. Iterate tokens left to right.
      2. TERMINAL '"' → toggle in_quotes (opens/closes exact phrase).
      3. TERMINAL '(' or ')' → flush current group → DisplayToken(type=BRACKET).
      4. WORD → accumulate into current group.
      5. LEXEME → flush current group → DisplayToken(type=LEXEME).
      6. WHITESPACE → skip.

    Args:
        token_section: Parsed TokenSection from the XML.

    Returns:
        List of DisplayToken instances ready for frontend rendering.
    """
    tokens = token_section.tokens
    if not tokens:
        return []

    result: List[DisplayToken] = []
    current_words: List[str] = []
    current_channels: set = set()
    current_distances: List[int] = []
    current_has_error = False
    in_quotes = False

    def flush_group() -> None:
        nonlocal current_words, current_channels, current_distances
        nonlocal current_has_error

        if not current_words:
            return

        text = " ".join(current_words)
        channel = resolve_phrase_channel(current_channels)
        word_distance = max(current_distances) if current_distances else 2
        is_exact = in_quotes

        if is_exact or len(current_words) > 1:
            token_type = "PHRASE"
        else:
            token_type = "WORD"

        result.append(
            DisplayToken(
                text=text,
                type=token_type,
                channel=channel,
                word_distance=word_distance,
                is_error=current_has_error,
                is_exact=is_exact,
            )
        )

        current_words = []
        current_channels = set()
        current_distances = []
        current_has_error = False

    for tok in tokens:
        if tok.type == "WHITESPACE":
            continue

        if tok.type == "TERMINAL":
            if tok.text == '"':
                if in_quotes:
                    flush_group()
                    in_quotes = False
                else:
                    if current_words:
                        flush_group()
                    in_quotes = True
            elif tok.text in ("(", ")"):
                flush_group()
                result.append(
                    DisplayToken(
                        text=tok.text,
                        type="BRACKET",
                        channel="ANY",
                        word_distance=2,
                        is_error=False,
                        is_exact=False,
                    )
                )
            continue

        if tok.type == "LEXEME" and tok.text.upper() in _LEXEME_KEYWORDS:
            flush_group()
            result.append(
                DisplayToken(
                    text=tok.text.lower(),
                    type="LEXEME",
                    channel="ANY",
                    word_distance=2,
                    is_error=tok.is_error,
                    is_exact=False,
                )
            )
            continue

        if tok.type == "WORD":
            current_words.append(tok.text)
            if tok.channel and tok.channel.strip().upper() not in ("", "ANY"):
                current_channels.add(tok.channel.strip().upper())
            if tok.word_distance:
                try:
                    current_distances.append(int(tok.word_distance))
                except (ValueError, TypeError):
                    pass
            if tok.is_error:
                current_has_error = True
            continue

    flush_group()
    return result

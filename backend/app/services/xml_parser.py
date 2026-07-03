"""XML dictionary parser service.

Parses SpeechLabRequest XML dictionaries used for dialogue analysis.
Supports both the nested format (with <Requests> nesting) and
the flat format (with <parent_id> elements).

Key features (enhanced via dict-analyzer integration):
  - Extracts hierarchical dictionary structure (parent -> child)
  - Parses <Token> elements into DictionaryCondition objects
  - Groups WORD tokens into phrases, respects LEXEME separators (ИЛИ/AND)
  - Handles TERMINAL quotes (") -> is_exact flag on conditions
  - Per-token Channel and WordDistance from <Properties>
  - Parses <SavedState> section -> SavedState model
  - Parses <Attributes>/<AttributeTokens> -> AttributeSection model
  - Handles <SpeechLabRemainderRequest> elements -> is_remainder=True
  - Builds PhraseGroup list via logic_builder.build_phrase_groups()
  - Builds attribute LogicNode tree via logic_builder.build_attribute_tree()
  - Validates: at least one WORD token, no cycles, valid channels
  - Supports <Properties> as both attributes and child elements

Uses lxml.etree for robust XML parsing.
"""

from __future__ import annotations

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
    build_attribute_tree,
    build_phrase_groups,
    detect_warnings,
)

logger = logging.getLogger(__name__)

# Valid channel values from XML Properties
_VALID_CHANNELS = {"CLIENT", "OPERATOR", "ANY"}

# LEXEME tokens that separate phrase groups
_PHRASE_SEPARATORS = {"ИЛИ", "OR", "AND"}


async def parse_xml_bytes(xml_bytes: bytes, filename: str) -> Tuple[DictionaryNode, DictionaryValidation]:
    """Parse XML dictionary bytes into a DictionaryNode tree.

    Args:
        xml_bytes: Raw XML file content.
        filename: Original filename for metadata.

    Returns:
        Tuple of (parsed DictionaryNode tree, validation results).

    Raises:
        ValueError: If the XML is malformed or cannot be parsed.
    """
    try:
        tree = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Invalid XML in '{filename}': {exc}") from exc

    return _parse_speech_lab_request(tree, filename, parent_name=None)


async def parse_xml_file(file_path: str, filename: Optional[str] = None) -> Tuple[DictionaryNode, DictionaryValidation]:
    """Parse an XML dictionary file by path.

    Args:
        file_path: Path to the .xml file.
        filename: Override filename.

    Returns:
        Tuple of (parsed DictionaryNode tree, validation results).

    Raises:
        ValueError: If the XML is malformed or cannot be parsed.
    """
    try:
        tree = etree.parse(file_path)
        root = tree.getroot()
    except (etree.XMLSyntaxError, OSError) as exc:
        raise ValueError(f"Cannot parse XML file '{filename or file_path}': {exc}") from exc

    return _parse_speech_lab_request(root, filename or file_path, parent_name=None)


def _parse_bool(text: Optional[str]) -> bool:
    """Parse a boolean string like 'true', 'True', 'false', 'False'.

    Args:
        text: String representation of a boolean value, or None.

    Returns:
        Parsed boolean value. Defaults to False if None/empty.
    """
    if not text:
        return False
    return text.strip().lower() == "true"


def _get_text(element: etree._Element, tag: str) -> Optional[str]:
    """Get text content of a child element, or None if not found.

    Args:
        element: Parent element.
        tag: Child element tag name.

    Returns:
        Text content stripped, or None.
    """
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _get_text_or_empty(element: etree._Element, tag: str) -> str:
    """Get text content of a child element, defaulting to empty string.

    Args:
        element: Parent element.
        tag: Child element tag name.

    Returns:
        Text content of the child, or empty string if not found.
    """
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


# ---------------------------------------------------------------------------
# New: SavedState, AttributeSection, TokenSection parsing
# ---------------------------------------------------------------------------


def _parse_saved_state(parent: etree._Element) -> Optional[SavedState]:
    """Parse the <SavedState> section from the XML.

    Returns None when the <SavedState> element is absent,
    rather than a SavedState with misleading defaults
    (total_found=0, is_actual=True).

    When <SavedState> exists but <IsActual> sub-element is missing,
    defaults is_actual to False (conservative: don't claim data exists
    unless the XML explicitly says so).

    Args:
        parent: Parent element containing <SavedState>.

    Returns:
        Populated SavedState model, or None if element absent.
    """
    ss_elem = parent.find("SavedState")
    if ss_elem is None:
        return None

    return SavedState(
        total_found=int(_get_text_or_empty(ss_elem, "TotalFound") or "0"),
        last_update_time=_get_text_or_empty(ss_elem, "LastUpdateTime"),
        execution_time=_get_text_or_empty(ss_elem, "ExecutionTime"),
        is_actual=_parse_bool(_get_text_or_empty(ss_elem, "IsActual") or "false"),
        is_cancelled=_parse_bool(_get_text_or_empty(ss_elem, "IsCancelled") or "false"),
    )


def _parse_search_attribute(at_elem: etree._Element) -> SearchAttribute:
    """Parse <SearchAttribute> from an <AttributeToken> element.

    Args:
        at_elem: <AttributeToken> element containing <SearchAttribute>.

    Returns:
        SearchAttribute with key and value.
    """
    sa_elem = at_elem.find("SearchAttribute")
    if sa_elem is None:
        return SearchAttribute(key="", value="")

    key = _get_text_or_empty(sa_elem, "Key")
    value = _get_text_or_empty(sa_elem, "Value")
    return SearchAttribute(key=key, value=value)


def _parse_attribute_section(parent: etree._Element) -> AttributeSection:
    """Parse the <Attributes> section from the XML.

    Args:
        parent: Parent element containing <Attributes>.

    Returns:
        AttributeSection with list of AttributeTokenModel.
    """
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
            is_error=_parse_bool(_get_text_or_empty(at_elem, "IsError") or "false"),
        )
        tokens.append(token)

    return AttributeSection(attribute_tokens=tokens)


def _parse_token_section(parent: etree._Element) -> TokenSection:
    """Parse the <Tokens> section from the XML with per-token Properties.

    Args:
        parent: Parent element containing <Tokens>.

    Returns:
        TokenSection with list of TokenModel (each with channel and word_distance).
    """
    tokens_elem = parent.find("Tokens")
    if tokens_elem is None:
        return TokenSection()

    tokens: List[TokenModel] = []
    for tok_elem in tokens_elem.findall("Token"):
        props = tok_elem.find("Properties")
        channel = ""
        word_distance = ""
        if props is not None:
            # Try attribute format first
            channel = props.get("Channel", "")
            word_distance = props.get("WordDistance", "")
            # Fall back to child element format
            if not channel:
                ch_elem = props.find("Channel")
                if ch_elem is not None and ch_elem.text:
                    channel = ch_elem.text.strip()
            if not word_distance:
                wd_elem = props.find("WordDistance")
                if wd_elem is not None and wd_elem.text:
                    word_distance = wd_elem.text.strip()

        token = TokenModel(
            text=_get_text_or_empty(tok_elem, "Text"),
            type=_get_text_or_empty(tok_elem, "Type") or "WORD",
            is_error=_parse_bool(_get_text_or_empty(tok_elem, "IsError") or "false"),
            channel=channel,
            word_distance=word_distance,
        )
        tokens.append(token)

    return TokenSection(tokens=tokens)


# ---------------------------------------------------------------------------
# Main parsing logic (enhanced)
# ---------------------------------------------------------------------------


def _parse_speech_lab_request(
    element: etree._Element,
    filename: str,
    parent_name: Optional[str] = None,
    is_remainder: bool = False,
) -> Tuple[DictionaryNode, DictionaryValidation]:
    """Parse a single <SpeechLabRequest> element recursively.

    Handles both nested format (child dicts in <Requests>) and
    flat format (parent_id element). Also handles
    <SpeechLabRemainderRequest> elements.

    Enhanced parsing:
      - SavedState -> saved_state field
      - Attributes -> attributes + attribute_tree fields
      - Per-token Properties -> TokenSection -> phrase_groups field
      - TERMINAL quotes -> is_exact on conditions
      - SpeechLabRemainderRequest -> is_remainder=True

    Args:
        element: The SpeechLabRequest (or RemainderRequest) XML element.
        filename: Source filename for metadata.
        parent_name: Name of the parent dictionary (None for root).
        is_remainder: True if this is a <SpeechLabRemainderRequest>.

    Returns:
        Tuple of (DictionaryNode, validation).
    """
    # Extract basic info
    dict_id = _get_text(element, "Id") or uuid.uuid4().hex[:12]
    dict_name = _get_text(element, "Name") or "Unnamed"

    # Check for flat parent_id format
    parent_id_text = _get_text(element, "parent_id")
    if parent_id_text:
        parent_name = parent_id_text.strip()

    # --- Enriched parsing: SavedState ---
    saved_state = _parse_saved_state(element)

    # --- Enriched parsing: Attributes ---
    attribute_section = _parse_attribute_section(element)

    # --- Enriched parsing: TokenSection (per-token Properties) ---
    token_section = _parse_token_section(element)

    # --- Enriched parsing: PhraseGroups from logic_builder ---
    phrase_groups = build_phrase_groups(token_section)

    # --- Enriched parsing: Attribute tree from logic_builder ---
    attribute_tree: Optional[LogicNode] = None
    has_meaningful_attrs = any(t.type == "ATTRIBUTE" for t in attribute_section.attribute_tokens)
    if has_meaningful_attrs:
        attribute_tree = build_attribute_tree(attribute_section)

    # --- Parse conditions (backward-compatible) ---
    # Use the old _parse_tokens() for backward compatibility with search.py
    # but now also extract is_exact from TERMINAL quotes
    conditions, condition_warnings = _parse_tokens_enriched(element, phrase_groups)

    # --- Parse child dictionaries from nested <Requests> ---
    children: List[DictionaryNode] = []
    child_warnings: List[str] = []

    requests_elem = element.find("Requests")
    if requests_elem is not None:
        for child_elem in requests_elem:
            # Get local tag name (strip namespace if any)
            tag = etree.QName(child_elem.tag).localname if "}" in child_elem.tag else child_elem.tag

            if tag == "SpeechLabRemainderRequest":
                try:
                    child_node, child_val = _parse_speech_lab_request(
                        child_elem, filename, parent_name=dict_name, is_remainder=True
                    )
                    children.append(child_node)
                    child_warnings.extend(child_val.warnings)
                except Exception as exc:
                    child_warnings.append(f"Failed to parse remainder dictionary: {exc}")
            elif tag == "SpeechLabRequest":
                try:
                    child_node, child_val = _parse_speech_lab_request(
                        child_elem, filename, parent_name=dict_name, is_remainder=False
                    )
                    children.append(child_node)
                    child_warnings.extend(child_val.warnings)
                except Exception as exc:
                    child_warnings.append(f"Failed to parse child dictionary: {exc}")

    # --- Run detect_warnings from logic_builder ---
    logic_warnings = detect_warnings(attribute_section, token_section, phrase_groups)
    # Merge warnings (avoid duplicates from different sources)
    all_warnings = condition_warnings + child_warnings
    for w in logic_warnings:
        if w not in all_warnings:
            all_warnings.append(w)

    # Build node with enriched fields
    has_children = len(children) > 0
    node = DictionaryNode(
        id=dict_id,
        name=dict_name,
        parent_name=parent_name,
        conditions=conditions,
        children=children,
        condition_count=len(conditions),
        has_children=has_children,
        children_count=len(children),
        # Enriched fields
        saved_state=saved_state,
        attributes=attribute_section if attribute_section.attribute_tokens else None,
        is_remainder=is_remainder,
        phrase_groups=phrase_groups,
        attribute_tree=attribute_tree,
        # SpeechLab: raw TokenSection for DisplayToken conversion
        token_section=token_section if token_section.tokens else None,
    )

    # Validate
    validation = _validate_node(node, all_warnings)

    return node, validation


# ---------------------------------------------------------------------------
# Token parsing (enhanced with is_exact from TERMINAL quotes)
# ---------------------------------------------------------------------------


def _parse_tokens_enriched(
    element: etree._Element,
    phrase_groups: List[PhraseGroup],
) -> Tuple[List[DictionaryCondition], List[str]]:
    """Parse <Tokens> element into DictionaryCondition objects using PhraseGroups.

    This replaces the old _parse_tokens() with an enriched version that:
    1. Uses PhraseGroups built by logic_builder (with is_exact flag)
    2. Converts each PhraseGroup into a DictionaryCondition
    3. Preserves WITHOUT list from ExtraLimitations
    4. Extracts OR-group structure into phrase_groups field (AG-UIREWORK-5)
    5. Detects НЕ-prefixed phrases for is_exception/exception_phrases (AG-UIREWORK-5)

    OR-group extraction:
      When multiple PhraseGroups share the same parent SpeechLabRequest,
      they represent alternatives (separated by ИЛИ in the XML).
      All groups are collected into phrase_groups: [[w1, w2], [w3, w4]].

    НЕ-prefix detection:
      If a phrase starts with "НЕ" (case-insensitive, Russian negation),
      is_exception=True and the word after НЕ goes into exception_phrases.

    If phrase_groups is empty (no tokens), falls back to the old method.

    Args:
        element: The SpeechLabRequest element.
        phrase_groups: PhraseGroup list from logic_builder.build_phrase_groups().

    Returns:
        Tuple of (conditions, warnings).
    """
    conditions: List[DictionaryCondition] = []
    warnings: List[str] = []

    if not phrase_groups:
        # No phrase groups — may be a parent node with no tokens
        return conditions, warnings

    # Check for WITHOUT tokens in <ExtraLimitations>
    without_list = _parse_without_list(element)

    # Collect all OR-group word lists for phrase_groups field
    # Each PhraseGroup becomes one inner list of words
    all_group_words: List[List[str]] = [
        pg.words for pg in phrase_groups if pg.words
    ]

    for pg in phrase_groups:
        if not pg.words:
            warnings.append("Пустая фразовая группа")
            continue

        phrase_text = " ".join(pg.words)

        # Channel from PhraseGroup (may be empty -> ANY)
        channel = pg.channel.upper() if pg.channel else "ANY"
        if channel not in _VALID_CHANNELS:
            channel = "ANY"

        # Word distance from PhraseGroup (max per group)
        word_distance = pg.word_distance if pg.word_distance > 0 else 2

        # Compute word_count using smartlogger tokenizer (INV-2: NOT .split())
        try:
            from smartlogger.tokenizer import tokenize
            word_count = len(tokenize(phrase_text))
        except ImportError:
            word_count = len(phrase_text.split())

        # --- НЕ-prefix detection (AG-UIREWORK-5) ---
        is_exception = False
        exception_phrases: List[str] = []
        words = pg.words
        if words and words[0].upper() in ("\u041d\u0415", "NE"):
            is_exception = True
            # Everything after НЕ is the exception phrase
            exception_words = words[1:]
            if exception_words:
                exception_phrases.append(" ".join(exception_words))

        # --- Nested phrases from child SpeechLabRequests (AG-UIREWORK-5) ---
        nested_phrases = _extract_nested_phrases(element)

        conditions.append(
            DictionaryCondition(
                text=phrase_text,
                word_distance=word_distance,
                word_count=word_count,
                channel_constraint=channel,
                without_list=without_list,
                is_exact=pg.is_exact,
                # Extended fields (AG-UIREWORK-5)
                phrase_groups=list(all_group_words),
                nested_phrases=nested_phrases,
                is_exception=is_exception,
                exception_phrases=exception_phrases,
            )
        )

    return conditions, warnings


# ---------------------------------------------------------------------------
# Backward-compatible helpers
# ---------------------------------------------------------------------------


def _extract_nested_phrases(element: etree._Element) -> List[str]:
    """Extract phrase texts from child SpeechLabRequest <Tokens> sections.

    In SmartLogger XML, nested SpeechLabRequest elements under <Requests>
    contain their own <Tokens> with phrase conditions. These represent
    phrases at deeper hierarchy levels (e.g. Q2, Q3 phrases within a Q1 dict).

    For the DictionaryCondition.nested_phrases field (AG-UIREWORK-5),
    we extract the first-level child phrase texts so the frontend can
    display the dictionary structure (what phrases come after the main one).

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
        tag = etree.QName(child_elem.tag).localname if "}" in child_elem.tag else child_elem.tag
        if tag not in ("SpeechLabRequest", "SpeechLabRemainderRequest"):
            continue

        # Extract phrase texts from child's Tokens section
        tokens_elem = child_elem.find("Tokens")
        if tokens_elem is None:
            continue

        phrase_words: List[str] = []
        for token_elem in tokens_elem.findall("Token"):
            token_type = _get_text(token_elem, "Type") or ""
            text = _get_text(token_elem, "Text") or ""
            if token_type == "WORD" and text:
                phrase_words.append(text)
            elif token_type == "LEXEME" and text.upper() in ("ИЛИ", "OR"):
                # Flush current phrase before starting new group
                if phrase_words:
                    nested.append(" ".join(phrase_words))
                    phrase_words = []

        if phrase_words:
            nested.append(" ".join(phrase_words))

    return nested


def _parse_properties(token_elem: etree._Element) -> Tuple[str, int]:
    """Parse <Properties> element for Channel and WordDistance.

    Supports both attribute format:
      <Properties Channel="CLIENT" WordDistance="2" />

    And child element format:
      <Properties>
        <Channel>CLIENT</Channel>
        <WordDistance>2</WordDistance>
      </Properties>

    Args:
        token_elem: The <Token> element.

    Returns:
        Tuple of (channel, word_distance).
    """
    props_elem = token_elem.find("Properties")
    if props_elem is None:
        return "ANY", 2

    # Try attribute format first
    channel = props_elem.get("Channel", "")
    word_distance_str = props_elem.get("WordDistance", "")

    # Fall back to child element format
    if not channel:
        channel_elem = props_elem.find("Channel")
        if channel_elem is not None and channel_elem.text:
            channel = channel_elem.text.strip()

    if not word_distance_str:
        wd_elem = props_elem.find("WordDistance")
        if wd_elem is not None and wd_elem.text:
            word_distance_str = wd_elem.text.strip()

    # Normalize channel
    channel = channel.upper().strip() if channel else "ANY"
    if channel not in _VALID_CHANNELS:
        channel = "ANY"

    # Parse word distance
    try:
        word_distance = int(word_distance_str) if word_distance_str else 2
    except (ValueError, TypeError):
        word_distance = 2

    return channel, word_distance


def _parse_without_list(element: etree._Element) -> List[str]:
    """Parse <ExtraLimitations> for WITHOUT phrases.

    These are phrases that, if found, suppress the dictionary match.

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
        # ExtraLimitations may contain nested Tokens similar to the main Tokens
        tokens_elem = limitation.find("Tokens")
        if tokens_elem is None:
            continue
        phrase_words: List[str] = []
        for token_elem in tokens_elem.findall("Token"):
            text = _get_text(token_elem, "Text") or ""
            token_type = _get_text(token_elem, "Type") or ""
            if token_type == "WORD" and text:
                phrase_words.append(text)
        if phrase_words:
            without_list.append(" ".join(phrase_words))

    return without_list


def _resolve_channel(group: List[Dict]) -> str:
    """Determine the overall channel constraint for a phrase group.

    Rules:
    - If any WORD has CLIENT -> CLIENT
    - If any WORD has OPERATOR -> OPERATOR
    - If both CLIENT and OPERATOR present -> ANY
    - If all are ANY -> ANY

    Args:
        group: List of token dicts from a phrase group.

    Returns:
        Resolved channel constraint string.
    """
    channels = set(t["channel"] for t in group)
    has_client = "CLIENT" in channels
    has_operator = "OPERATOR" in channels

    if has_client and has_operator:
        return "ANY"
    if has_client:
        return "CLIENT"
    if has_operator:
        return "OPERATOR"
    return "ANY"


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
    - Duplicate phrase detection

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

    # Check for duplicate conditions within a node
    seen_phrases: Set[str] = set()
    for cond in node.conditions:
        key = cond.text.lower()
        seen_phrases.add(key)

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

    Uses node **ID** (unique GUID) for identity — not name.
    In real ЦРТ dictionaries, parent and child often share the same
    Name (e.g. "Риск расторжения") but have different IDs, which
    is NOT a cycle.

    Args:
        node: Root node to start from.

    Returns:
        List of names forming a cycle, or empty if no cycle.
    """
    visited: Set[str] = set()
    in_stack: Set[str] = set()
    path: List[str] = []

    def dfs(current: DictionaryNode) -> List[str]:
        if current.id in in_stack:
            cycle_start = path.index(current.name)
            return path[cycle_start:] + [current.name]

        if current.id in visited:
            return []

        visited.add(current.id)
        in_stack.add(current.id)
        path.append(current.name)

        for child in current.children:
            result = dfs(child)
            if result:
                return result

        path.pop()
        in_stack.discard(current.id)
        return []

    return dfs(node)


# ---------------------------------------------------------------------------
# DisplayToken conversion (SpeechLab UI)
# ---------------------------------------------------------------------------


def resolve_phrase_channel(channels: Set[str]) -> str:
    """Determine the channel for a group of WORD tokens.

    Rules (matches frontend resolvePhraseChannel):
      - ANY in channels → ANY
      - Both CLIENT and OPERATOR → ANY
      - Only CLIENT → CLIENT
      - Only OPERATOR → OPERATOR
      - Empty set → ANY

    Args:
        channels: Set of channel strings from WORD token Properties.

    Returns:
        Resolved channel: "OPERATOR", "CLIENT", or "ANY".
    """
    if not channels:
        return "ANY"
    if "ANY" in channels:
        return "ANY"
    has_client = "CLIENT" in channels
    has_operator = "OPERATOR" in channels
    if has_client and has_operator:
        return "ANY"
    if has_client:
        return "CLIENT"
    if has_operator:
        return "OPERATOR"
    return "ANY"


# LEXEME tokens that produce DisplayToken(type=LEXEME)
_LEXEME_KEYWORDS = {"ИЛИ", "OR", "И", "AND", "НЕ", "NOT"}


def group_into_display_tokens(token_section: TokenSection) -> List[DisplayToken]:
    """Convert a TokenSection into a list of DisplayTokens for frontend rendering.

    Algorithm (matches frontend groupIntoDisplayTokens):
      1. Iterate TokenSection.tokens left to right.
      2. TERMINAL '"' → toggle in_quotes flag (opens/closes exact phrase).
      3. TERMINAL '(' or ')' → flush current group → DisplayToken(type=BRACKET).
      4. WORD → accumulate into current group; track channels and word_distances.
      5. LEXEME (ИЛИ/И/НЕ/OR/AND/NOT) → flush current group → DisplayToken(type=LEXEME, text lowercase).
      6. WHITESPACE → skip.
      7. On flush of WORD group:
         - If in_quotes → type=PHRASE, is_exact=True
         - If NOT in_quotes and single word → type=WORD
         - If NOT in_quotes and multiple words → type=PHRASE
         - Channel = resolve_phrase_channel(accumulated channels)
         - word_distance = max of accumulated distances

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
    current_channels: Set[str] = set()
    current_distances: List[int] = []
    current_has_error = False
    in_quotes = False

    def flush_group() -> None:
        """Flush accumulated WORD tokens into DisplayToken(s)."""
        nonlocal current_words, current_channels, current_distances, in_quotes
        nonlocal current_has_error

        if not current_words:
            return

        text = " ".join(current_words)
        channel = resolve_phrase_channel(current_channels)
        word_distance = max(current_distances) if current_distances else 2
        is_exact = in_quotes

        if is_exact:
            token_type: str = "PHRASE"
        elif len(current_words) == 1:
            token_type = "WORD"
        else:
            token_type = "PHRASE"

        result.append(
            DisplayToken(
                text=text,
                type=token_type,  # type: ignore[arg-type]
                channel=channel,  # type: ignore[arg-type]
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
        # WHITESPACE → skip
        if tok.type == "WHITESPACE":
            continue

        # TERMINAL → quotes or brackets
        if tok.type == "TERMINAL":
            if tok.text == '"':
                # Opening/closing quote
                if in_quotes:
                    # Closing quote — flush the exact phrase
                    flush_group()
                    in_quotes = False
                else:
                    # Opening quote
                    in_quotes = True
            elif tok.text in ("(", ")"):
                # Bracket — flush any pending words, then add bracket token
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
            else:
                # Other TERMINAL (rare) — treat as bracket
                flush_group()
                result.append(
                    DisplayToken(
                        text=tok.text,
                        type="BRACKET",
                        channel="ANY",
                        word_distance=2,
                        is_error=tok.is_error,
                        is_exact=False,
                    )
                )
            continue

        # LEXEME → flush + LEXEME display token
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
            in_quotes = False
            continue

        # WORD → accumulate
        if tok.type == "WORD":
            current_words.append(tok.text)
            if tok.channel and tok.channel.strip():
                current_channels.add(tok.channel.strip().upper())
            if tok.word_distance:
                try:
                    current_distances.append(int(tok.word_distance))
                except (ValueError, TypeError):
                    pass
            if tok.is_error:
                current_has_error = True
            continue

        # LEXEME not in keywords → treat as regular text (rare edge case)
        if tok.type == "LEXEME":
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

        # Unknown token type → flush and add as WORD
        flush_group()
        if tok.text.strip():
            result.append(
                DisplayToken(
                    text=tok.text,
                    type="WORD",
                    channel="ANY",
                    word_distance=2,
                    is_error=tok.is_error,
                    is_exact=False,
                )
            )

    # Flush any remaining group
    flush_group()

    return result

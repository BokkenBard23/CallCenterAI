"""Logic tree builder: tokens/attributes -> AND/OR/NOT tree + attribute decoding.

Ported from <legacy>/src/dict_analyzer/logic.py and adapted for
CallCenterAI's model namespace (app.models).

Key functions:
    build_phrase_groups(token_section) -> list[PhraseGroup]
    build_attribute_tree(attribute_section) -> LogicNode
    decode_attribute(key, value) -> DecodedAttribute
    detect_warnings(attributes, token_section, phrase_groups) -> list[str]

Decoding rules:
    Duration          - "00:00:30;10675199.02:48:05" -> ">= 30 сек"
    CallDirection     - PhoneCallDirectionIngoing -> "Входящий"
    RemotePhoneNumber - NotStartsWith|07 -> "Номер не начинается с 07"
    UserDef5          - Equals|, val1 , val2 -> "SIP-сервер из списка (N шт.)"
    ExternalDictionary - UUID1,UUID2|OR -> "Внешний словарь (2 шт., логика OR)"
    Channel           - from Properties -> "Канал: Клиент / Оператор / Любой"
    WordDistance      - from Properties -> "Расстояние: до N слов"
"""

from __future__ import annotations

from collections import Counter
from typing import List, Optional, Tuple

from app.models import (
    AttributeSection,
    AttributeTokenModel,
    DecodedAttribute,
    LogicNode,
    PhraseGroup,
    TokenSection,
)


# ---------------------------------------------------------------------------
# TimeSpan parsing helpers
# ---------------------------------------------------------------------------

_TIMESPAN_MAX_DAYS_THRESHOLD = 1_000_000


def _parse_timespan(ts: str) -> int:
    """Parse a .NET TimeSpan string into total seconds.

    Formats supported:
        - HH:MM:SS
        - DD.HH:MM:SS
        - DD.HH:MM:SS.fffffff

    Args:
        ts: TimeSpan string representation.

    Returns:
        Total number of seconds.
    """
    ts = ts.strip()
    if not ts:
        return 0

    # Split off fractional seconds after decimal point
    main_part = ts
    if "." in ts:
        parts_by_dot = ts.split(".")
        if len(parts_by_dot) >= 2:
            if ":" in parts_by_dot[-1]:
                # e.g. "10675199.02:48:05" — no fractional seconds
                main_part = ts
            else:
                # e.g. "00:00:30.4775807" — strip fractional
                main_part = ".".join(parts_by_dot[:-1])

    # Replace day separator dot with ':' for uniform splitting
    time_parts = main_part.replace(".", ":").split(":")

    if len(time_parts) == 3:
        hours, minutes, seconds = int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
        return hours * 3600 + minutes * 60 + seconds
    elif len(time_parts) == 4:
        days, hours, minutes, seconds = (
            int(time_parts[0]),
            int(time_parts[1]),
            int(time_parts[2]),
            int(time_parts[3]),
        )
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    else:
        return 0


def _is_timespan_max_value(ts: str) -> bool:
    """Check if a TimeSpan string represents TimeSpan.MaxValue (no upper bound).

    Args:
        ts: TimeSpan string representation.

    Returns:
        True if the value represents TimeSpan.MaxValue.
    """
    try:
        main_part = ts
        if "." in ts:
            parts_by_dot = ts.split(".")
            if ":" not in parts_by_dot[-1]:
                main_part = ".".join(parts_by_dot[:-1])

        day_str = main_part.split(".")[0].split(":")[0]
        return int(day_str) >= _TIMESPAN_MAX_DAYS_THRESHOLD
    except (ValueError, IndexError):
        return False


def _format_duration_seconds(total_seconds: int) -> str:
    """Format a duration in seconds to a human-readable Russian string.

    Args:
        total_seconds: Duration in seconds.

    Returns:
        Human-readable string like "30 сек" or "6 мин".
    """
    if total_seconds < 60:
        return f"{total_seconds} сек"
    if total_seconds % 60 == 0:
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes} мин"
        if minutes % 60 == 0:
            hours = minutes // 60
            return f"{hours} ч"
        return f"{minutes} мин"
    minutes = total_seconds // 60
    return f"{minutes} мин"


# ---------------------------------------------------------------------------
# decode_attribute
# ---------------------------------------------------------------------------


def decode_attribute(key: str, value: str) -> DecodedAttribute:
    """Decode a raw attribute key/value into a human-readable form.

    Decoding rules by key:
        Duration          - "min;max" (TimeSpan) -> ">= N сек" or "N сек - M сек"
        CallDirection     - enum string -> "Входящий" / "Исходящий" / "Внутренний"
        RemotePhoneNumber - "Operator|value" -> "Номер <operator> <value>"
        UserDef5          - "Operator|, val1 , val2 , ..." -> "SIP-сервер из списка (N шт.)"
        ExternalDictionary - "UUID1,UUID2|OR" -> "Внешний словарь (N шт., логика OR)"
        Channel           - from Properties -> "Канал: Клиент / Оператор / Любой"
        WordDistance      - from Properties -> "Расстояние: до N слов"

    Unknown keys -> DecodedAttribute with human_readable="<key> = <raw_value>".

    Args:
        key:   attribute key string.
        value: raw attribute value string.

    Returns:
        DecodedAttribute with human_readable field populated.
    """
    if key == "Duration":
        return _decode_duration(value)
    elif key == "CallDirection":
        return _decode_call_direction(value)
    elif key == "RemotePhoneNumber":
        return _decode_remote_phone(value)
    elif key == "UserDef5":
        return _decode_userdef5(value)
    elif key == "ExternalDictionary":
        return _decode_external_dictionary(value)
    elif key == "Channel":
        return _decode_channel(value)
    elif key == "WordDistance":
        return _decode_word_distance(value)
    else:
        return DecodedAttribute(
            key=key,
            raw_value=value,
            human_readable=f"{key} = {value}",
            operator="",
        )


def _decode_duration(value: str) -> DecodedAttribute:
    """Decode Duration attribute: 'min;max' TimeSpan format."""
    parts = value.split(";")
    min_ts = parts[0].strip() if len(parts) > 0 else "00:00:00"
    max_ts = parts[1].strip() if len(parts) > 1 else ""

    min_seconds = _parse_timespan(min_ts)

    if not max_ts or _is_timespan_max_value(max_ts):
        human = f"Длительность >= {_format_duration_seconds(min_seconds)}"
    else:
        max_seconds = _parse_timespan(max_ts)
        human = f"Длительность {_format_duration_seconds(min_seconds)} — {_format_duration_seconds(max_seconds)}"

    return DecodedAttribute(
        key="Duration",
        raw_value=value,
        human_readable=human,
        operator=">=",
    )


def _decode_call_direction(value: str) -> DecodedAttribute:
    """Decode CallDirection attribute."""
    direction_map: dict[str, str] = {
        "PhoneCallDirectionIngoing": "Входящий",
        "PhoneCallDirectionOutgoing": "Исходящий",
        "PhoneCallDirectionInternal": "Внутренний",
    }
    human = f"Направление: {direction_map.get(value, value)}"

    return DecodedAttribute(
        key="CallDirection",
        raw_value=value,
        human_readable=human,
        operator="Equals",
    )


def _decode_remote_phone(value: str) -> DecodedAttribute:
    """Decode RemotePhoneNumber attribute: 'Operator|value'."""
    if "|" in value:
        operator, phone_val = value.split("|", 1)
    else:
        operator = "Equals"
        phone_val = value

    operator_map: dict[str, str] = {
        "NotStartsWith": "Номер не начинается с",
        "StartsWith": "Номер начинается с",
        "Equals": "Номер =",
        "Contains": "Номер содержит",
    }

    operator_russian = operator_map.get(operator, operator)
    human = f"{operator_russian} {phone_val}"

    return DecodedAttribute(
        key="RemotePhoneNumber",
        raw_value=value,
        human_readable=human,
        operator=operator,
    )


def _decode_userdef5(value: str) -> DecodedAttribute:
    """Decode UserDef5 attribute: 'Operator|, val1 , val2 , ...'."""
    if "|" in value:
        operator, raw_list = value.split("|", 1)
    else:
        operator = "Equals"
        raw_list = value

    # Strip leading comma and spaces
    raw_list = raw_list.strip()
    if raw_list.startswith(","):
        raw_list = raw_list[1:]
    raw_list = raw_list.strip()

    # Split by comma and strip each value
    items: list[str] = []
    if raw_list:
        items = [item.strip() for item in raw_list.split(",") if item.strip()]

    count = len(items)

    operator_russian_map: dict[str, str] = {
        "Equals": "=",
        "Contains": "содержит",
    }
    operator_russian = operator_russian_map.get(operator, operator)

    human = f"SIP-сервер из списка ({count} шт.)"

    return DecodedAttribute(
        key="UserDef5",
        raw_value=value,
        human_readable=human,
        operator=operator_russian,
    )


def _decode_external_dictionary(value: str) -> DecodedAttribute:
    """Decode ExternalDictionary attribute: 'UUID1,UUID2|OR'."""
    if "|" in value:
        uuids_part, logic = value.rsplit("|", 1)
    else:
        uuids_part = value
        logic = "OR"

    uuids = [u.strip() for u in uuids_part.split(",") if u.strip()]
    count = len(uuids)

    human = f"Внешний словарь ({count} шт., логика {logic})"

    return DecodedAttribute(
        key="ExternalDictionary",
        raw_value=value,
        human_readable=human,
        operator=logic,
    )


def _decode_channel(value: str) -> DecodedAttribute:
    """Decode Channel attribute."""
    channel_map: dict[str, str] = {
        "CLIENT": "Клиент",
        "OPERATOR": "Оператор",
        "ANY": "Любой",
    }
    human_channel = channel_map.get(value, value)
    human = f"Канал: {human_channel}"

    return DecodedAttribute(
        key="Channel",
        raw_value=value,
        human_readable=human,
        operator="Equals",
    )


def _decode_word_distance(value: str) -> DecodedAttribute:
    """Decode WordDistance attribute."""
    human = f"Расстояние между словами: до {value} слов"

    return DecodedAttribute(
        key="WordDistance",
        raw_value=value,
        human_readable=human,
        operator="",
    )


# ---------------------------------------------------------------------------
# build_attribute_tree
# ---------------------------------------------------------------------------


def _is_or_token(tok: AttributeTokenModel) -> bool:
    """Check if an attribute token is an OR lexeme."""
    return tok.type == "LEXEME" and tok.text.upper() in ("OR", "ИЛИ")


def _is_and_token(tok: AttributeTokenModel) -> bool:
    """Check if an attribute token is an AND lexeme."""
    return tok.type == "LEXEME" and tok.text.upper() in ("AND", "И")


def _is_not_token(tok: AttributeTokenModel) -> bool:
    """Check if an attribute token is a NOT lexeme."""
    return tok.type == "LEXEME" and tok.text.upper() == "NOT"


def _is_open_paren(tok: AttributeTokenModel) -> bool:
    """Check if an attribute token is an opening parenthesis."""
    return tok.type == "TERMINAL" and tok.text.strip() == "("


def _is_close_paren(tok: AttributeTokenModel) -> bool:
    """Check if an attribute token is a closing parenthesis."""
    return tok.type == "TERMINAL" and tok.text.strip() == ")"


def _make_attribute_leaf(tok: AttributeTokenModel) -> LogicNode:
    """Create an ATTRIBUTE leaf node from an attribute token."""
    decoded = decode_attribute(tok.search_attribute.key, tok.search_attribute.value)
    return LogicNode(
        node_type="ATTRIBUTE",
        children=[],
        payload=decoded.model_dump(),
    )


def _parse_expression(
    tokens: List[AttributeTokenModel],
    index: int,
) -> Tuple[LogicNode, int]:
    """Parse an expression: and_expr (OR and_expr)*.

    Args:
        tokens: Full list of attribute tokens.
        index: Current position in the token list.

    Returns:
        Tuple of (parsed LogicNode, next index after parsing).
    """
    left, index = _parse_and_expr(tokens, index)

    or_children: List[LogicNode] = [left]
    while index < len(tokens) and _is_or_token(tokens[index]):
        index += 1  # skip OR
        right, index = _parse_and_expr(tokens, index)
        or_children.append(right)

    if len(or_children) == 1:
        return or_children[0], index
    return LogicNode(node_type="OR", children=or_children, payload={}), index


def _parse_and_expr(
    tokens: List[AttributeTokenModel],
    index: int,
) -> Tuple[LogicNode, int]:
    """Parse an AND expression: not_expr (AND not_expr)*."""
    left, index = _parse_not_expr(tokens, index)

    and_children: List[LogicNode] = [left]
    while index < len(tokens) and _is_and_token(tokens[index]):
        index += 1  # skip AND
        right, index = _parse_not_expr(tokens, index)
        and_children.append(right)

    if len(and_children) == 1:
        return and_children[0], index
    return LogicNode(node_type="AND", children=and_children, payload={}), index


def _parse_not_expr(
    tokens: List[AttributeTokenModel],
    index: int,
) -> Tuple[LogicNode, int]:
    """Parse a NOT expression: NOT not_expr | atom."""
    if index < len(tokens) and _is_not_token(tokens[index]):
        index += 1  # skip NOT
        child, index = _parse_not_expr(tokens, index)
        return LogicNode(node_type="NOT", children=[child], payload={}), index

    return _parse_atom(tokens, index)


def _parse_atom(
    tokens: List[AttributeTokenModel],
    index: int,
) -> Tuple[LogicNode, int]:
    """Parse an atom: '(' expression ')' | ATTRIBUTE."""
    if index >= len(tokens):
        return LogicNode(node_type="ATTRIBUTE", children=[], payload={}), index

    tok = tokens[index]

    if _is_open_paren(tok):
        index += 1  # skip '('
        node, index = _parse_expression(tokens, index)
        # skip ')'
        if index < len(tokens) and _is_close_paren(tokens[index]):
            index += 1
        return node, index

    if tok.type == "ATTRIBUTE":
        leaf = _make_attribute_leaf(tok)
        return leaf, index + 1

    # Skip unknown tokens (LEXEME operators are handled at higher levels)
    return LogicNode(node_type="ATTRIBUTE", children=[], payload={}), index + 1


def build_attribute_tree(attribute_section: AttributeSection) -> LogicNode:
    """Build AND/OR/NOT tree from AttributeToken list.

    Precedence: parentheses > NOT > AND > OR.

    Args:
        attribute_section: parsed AttributeSection from the XML.

    Returns:
        Root LogicNode of the attribute tree.
    """
    tokens = attribute_section.attribute_tokens
    if not tokens:
        return LogicNode(node_type="AND", children=[], payload={})

    # Filter out whitespace/empty tokens
    meaningful_tokens = [
        t
        for t in tokens
        if not (t.type == "LEXEME" and t.text.strip() == "")
        and not (t.type == "TERMINAL" and t.text.strip() == "")
    ]

    if not meaningful_tokens:
        return LogicNode(node_type="AND", children=[], payload={})

    node, _ = _parse_expression(meaningful_tokens, 0)
    return node


# ---------------------------------------------------------------------------
# build_phrase_groups
# ---------------------------------------------------------------------------


def build_phrase_groups(token_section: TokenSection) -> List[PhraseGroup]:
    """Extract PhraseGroups from the <Tokens> section.

    Traversal rules (left to right):
        TERMINAL '"'   -> start/end of exact phrase (is_exact=True)
        WORD tokens    -> grouped into PhraseGroup
        LEXEME 'ИЛИ'/'OR' -> separator between phrase groups
        WHITESPACE     -> ignored as word separator

    Channel is taken from WORD token Properties (not ANY).
    WordDistance is taken from each WORD token Properties individually (max per group).

    Args:
        token_section: parsed TokenSection from the XML.

    Returns:
        List of PhraseGroup instances.
    """
    tokens = token_section.tokens
    if not tokens:
        return []

    groups: List[PhraseGroup] = []
    current_words: List[str] = []
    current_channels: List[str] = []
    current_distances: List[int] = []
    in_quotes = False
    group_is_exact = False

    for tok in tokens:
        if tok.type == "WHITESPACE":
            continue

        if tok.type == "LEXEME" and tok.text.upper() in ("ИЛИ", "OR"):
            # Flush current phrase group
            if current_words:
                groups.append(
                    _build_phrase_group(
                        current_words, current_channels, current_distances, group_is_exact
                    )
                )
                current_words = []
                current_channels = []
                current_distances = []
            group_is_exact = False
            in_quotes = False
            continue

        if tok.type == "TERMINAL":
            if tok.text == '"':
                if in_quotes:
                    # Closing quote — end of exact phrase
                    in_quotes = False
                    if current_words:
                        groups.append(
                            _build_phrase_group(
                                current_words, current_channels, current_distances, True
                            )
                        )
                        current_words = []
                        current_channels = []
                        current_distances = []
                        group_is_exact = False
                else:
                    # Opening quote — start of exact phrase
                    in_quotes = True
                    group_is_exact = True
            elif tok.text == "(":
                # Parenthesis — flush current phrase if any
                if current_words:
                    groups.append(
                        _build_phrase_group(
                            current_words, current_channels, current_distances, group_is_exact
                        )
                    )
                    current_words = []
                    current_channels = []
                    current_distances = []
                    group_is_exact = False
                    in_quotes = False
            elif tok.text == ")":
                # Close paren — flush current phrase
                if current_words:
                    groups.append(
                        _build_phrase_group(
                            current_words, current_channels, current_distances, group_is_exact
                        )
                    )
                    current_words = []
                    current_channels = []
                    current_distances = []
                    group_is_exact = False
                    in_quotes = False
            continue

        if tok.type == "WORD":
            current_words.append(tok.text)
            if tok.channel and tok.channel != "ANY":
                current_channels.append(tok.channel)
            if tok.word_distance:
                try:
                    current_distances.append(int(tok.word_distance))
                except ValueError:
                    pass

    # Flush any remaining phrase
    if current_words:
        groups.append(
            _build_phrase_group(current_words, current_channels, current_distances, group_is_exact)
        )

    return groups


def _build_phrase_group(
    words: List[str],
    channels: List[str],
    distances: List[int],
    is_exact: bool,
) -> PhraseGroup:
    """Build a PhraseGroup from collected words, channels and distances.

    Channel resolution rules (matches xml_parser._resolve_channel):
      - If any WORD has CLIENT  → has_client = True
      - If any WORD has OPERATOR → has_operator = True
      - Both CLIENT and OPERATOR  → ANY  (phrase may come from either speaker)
      - Only CLIENT               → CLIENT
      - Only OPERATOR             → OPERATOR
      - All ANY / empty           → ""  (will become ANY downstream)

    WordDistance resolution:
      - min(distances): the strictest (smallest) distance wins.
        If any word requires distance 0 (strict sequential match),
        the entire phrase must respect that constraint.

    Args:
        words: List of word texts.
        channels: List of non-ANY channel values.
        distances: List of word distances.
        is_exact: Whether the phrase was quoted.

    Returns:
        Populated PhraseGroup.
    """
    # Determine channel: CLIENT + OPERATOR → ANY (SmartLogger semantics)
    channel = ""
    if channels:
        channel_set = set(channels)
        has_client = "CLIENT" in channel_set
        has_operator = "OPERATOR" in channel_set
        if has_client and has_operator:
            channel = "ANY"
        elif has_client:
            channel = "CLIENT"
        elif has_operator:
            channel = "OPERATOR"
        else:
            # Fallback: most common non-ANY channel (e.g. if new values appear)
            counter = Counter(channels)
            channel = counter.most_common(1)[0][0]

    # Determine word_distance: min value (strictest constraint wins)
    word_distance = min(distances) if distances else 0

    return PhraseGroup(
        words=list(words),
        channel=channel,
        word_distance=word_distance,
        is_exact=is_exact,
    )


# ---------------------------------------------------------------------------
# detect_warnings
# ---------------------------------------------------------------------------


def detect_warnings(
    attributes: AttributeSection,
    token_section: TokenSection,
    phrase_groups: List[PhraseGroup],
) -> List[str]:
    """Detect potential issues in the dictionary.

    Checks:
        - Any token with is_error=True
        - Duplicate phrases (same words in same order, case-insensitive)
        - Redundant quoting (all phrases in quotes)
        - Empty phrase groups
        - No <Attributes> section (dictionary matches all calls)

    Args:
        attributes: parsed AttributeSection from the XML.
        token_section: parsed TokenSection from the XML.
        phrase_groups: extracted PhraseGroup list.

    Returns:
        List of warning description strings.
    """
    warnings: List[str] = []

    # 1. Check for error tokens in attribute section
    for tok in attributes.attribute_tokens:
        if tok.is_error:
            warnings.append(f"Токен с ошибкой: {tok.text}")

    # 2. Check for error tokens in token section
    for tok in token_section.tokens:
        if tok.is_error:
            warnings.append(f"Токен с ошибкой: {tok.text}")

    # 3. Empty phrase groups
    for pg in phrase_groups:
        if not pg.words:
            warnings.append("Пустая фразовая группа")

    # 4. Duplicate phrases (case-insensitive)
    seen_phrases: dict[str, int] = {}
    for pg in phrase_groups:
        key = " ".join(pg.words).lower()
        if key in seen_phrases:
            seen_phrases[key] += 1
        else:
            seen_phrases[key] = 1

    for phrase_key, count in seen_phrases.items():
        if count > 1:
            warnings.append(f"Дублирующая фраза: {phrase_key}")

    # 5. All phrases in quotes
    if phrase_groups and all(pg.is_exact for pg in phrase_groups):
        warnings.append(
            "Все фразы в кавычках — возможно, стоит использовать поиск без кавычек для расширения покрытия"
        )

    # 6. No <Attributes> section with meaningful data
    has_meaningful_attrs = any(t.type == "ATTRIBUTE" for t in attributes.attribute_tokens)
    if not has_meaningful_attrs:
        warnings.append("Словарь без атрибутных фильтров — сработает на любых звонках")

    return warnings

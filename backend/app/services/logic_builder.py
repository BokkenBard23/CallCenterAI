"""Logic tree builder: tokens/attributes -> AND/OR/NOT tree + phrase groups.

Key functions:
    build_phrase_groups(token_section) -> list[PhraseGroup]
    build_attribute_tree(attribute_section) -> LogicNode
    decode_attribute(key, value) -> DecodedAttribute
    detect_warnings(attributes, token_section, phrase_groups) -> list[str]

CRITICAL RULES (from SmartLogger XML spec):
  - ALL LEXEME tokens (И, ИЛИ, НЕ) break phrases into separate operands
  - НЕ (LEXEME, uppercase) is a prefix negation OPERATOR — NOT a word
  - не (WORD, lowercase) is a regular search word — part of the phrase
  - Parentheses () group sub-expressions but do NOT create nested PhraseGroups
  - WordDistance is per-phrase (all words in a phrase have the same value)
  - Channel is per-phrase (all words in a phrase have the same value)
"""

from __future__ import annotations

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
# Единственный источник истины для LEXEME-разделителей
# ---------------------------------------------------------------------------

_ALL_LEXEME_SEPARATORS = {"ИЛИ", "OR", "И", "AND", "НЕ", "NOT"}

# ---------------------------------------------------------------------------
# build_phrase_groups
# ---------------------------------------------------------------------------


def build_phrase_groups(token_section: TokenSection) -> List[PhraseGroup]:
    """Extract PhraseGroups from the <Tokens> section.

    Traversal rules (left to right):
        TERMINAL '"'       -> start/end of exact phrase (is_exact=True)
        TERMINAL '(' / ')' -> flush current group (grouping tracked separately)
        WORD tokens        -> grouped into current PhraseGroup
        LEXEME 'ИЛИ'/'OR'  -> flush + next group has operator='OR'
        LEXEME 'И'/'AND'   -> flush + next group has operator='AND'
        LEXEME 'НЕ'/'NOT'  -> flush + next group has is_negated=True
        WHITESPACE         -> ignored

    Channel: taken from WORD token Properties. Per spec, all words in a
    phrase have the SAME channel — we take the first non-empty value.
    WordDistance: taken from WORD token Properties. Per spec, all words
    in a phrase have the SAME value — we take the first non-zero value,
    or keep 0 if all are 0 (which is valid: means no intermediate words).

    Args:
        token_section: parsed TokenSection from the XML.

    Returns:
        List of PhraseGroup instances with is_negated and operator fields.
    """
    tokens = token_section.tokens
    if not tokens:
        return []

    groups: List[PhraseGroup] = []

    # Accumulator state
    current_words: List[str] = []
    current_channel: str = ""
    current_word_distance: Optional[int] = None  # None = not yet set
    in_quotes: bool = False

    # Flags for the NEXT group
    next_is_negated: bool = False
    next_operator: str = ""  # "", "OR", "AND"

    def _flush() -> None:
        """Flush accumulated words into a PhraseGroup."""
        nonlocal current_words, current_channel, current_word_distance
        nonlocal next_is_negated, next_operator, in_quotes

        if not current_words:
            # No words accumulated — but if НЕ was pending and nothing follows,
            # we still reset the flag (edge case: trailing НЕ with no operand)
            return

        wd = current_word_distance if current_word_distance is not None else 2
        groups.append(
            PhraseGroup(
                words=list(current_words),
                channel=current_channel,
                word_distance=wd,
                is_exact=in_quotes,
                is_negated=next_is_negated,
            )
        )
        # Reset accumulator
        current_words = []
        current_channel = ""
        current_word_distance = None
        next_is_negated = False
        next_operator = ""

    for tok in tokens:
        # --- WHITESPACE: skip ---
        if tok.type == "WHITESPACE":
            continue

        # --- TERMINAL: quotes or brackets ---
        if tok.type == "TERMINAL":
            if tok.text == '"':
                if in_quotes:
                    # Closing quote — flush the exact phrase
                    _flush()
                    in_quotes = False
                else:
                    # Opening quote — flush any pending non-quoted words first
                    if current_words:
                        _flush()
                    in_quotes = True
            elif tok.text in ("(", ")"):
                # Parentheses flush the current group
                # (logical grouping is handled at a higher level)
                if current_words:
                    _flush()
                in_quotes = False
            continue

        # --- LEXEME: logical operators ---
        if tok.type == "LEXEME":
            text_upper = tok.text.upper()
            if text_upper in _ALL_LEXEME_SEPARATORS:
                # Flush current group before processing operator
                if current_words:
                    _flush()
                # Determine what this operator means for the NEXT group
                if text_upper in ("НЕ", "NOT"):
                    next_is_negated = True
                elif text_upper in ("И", "AND"):
                    next_operator = "AND"
                elif text_upper in ("ИЛИ", "OR"):
                    next_operator = "OR"
            # Unknown LEXEME — ignore silently
            continue

        # --- WORD: accumulate into current phrase ---
        if tok.type == "WORD":
            current_words.append(tok.text)
            # Channel: take first non-empty, non-ANY value
            if not current_channel and tok.channel and tok.channel.upper() != "ANY":
                current_channel = tok.channel.upper()
            # WordDistance: take from first WORD that has it set
            if current_word_distance is None and tok.word_distance:
                try:
                    current_word_distance = int(tok.word_distance)
                except (ValueError, TypeError):
                    pass
            continue

    # Flush any remaining words
    if current_words:
        _flush()

    return groups


# ---------------------------------------------------------------------------
# build_attribute_tree
# ---------------------------------------------------------------------------


def _is_or_token(tok: AttributeTokenModel) -> bool:
    return tok.type == "LEXEME" and tok.text.upper() in ("OR", "ИЛИ")


def _is_and_token(tok: AttributeTokenModel) -> bool:
    return tok.type == "LEXEME" and tok.text.upper() in ("AND", "И")


def _is_not_token(tok: AttributeTokenModel) -> bool:
    return tok.type == "LEXEME" and tok.text.upper() in ("NOT", "НЕ")


def _is_open_paren(tok: AttributeTokenModel) -> bool:
    return tok.type == "TERMINAL" and tok.text.strip() == "("


def _is_close_paren(tok: AttributeTokenModel) -> bool:
    return tok.type == "TERMINAL" and tok.text.strip() == ")"


def _make_attribute_leaf(tok: AttributeTokenModel) -> LogicNode:
    decoded = decode_attribute(tok.search_attribute.key, tok.search_attribute.value)
    return LogicNode(
        node_type="ATTRIBUTE",
        children=[],
        payload=decoded.model_dump(),
    )


def _parse_expression(
    tokens: List[AttributeTokenModel], index: int
) -> Tuple[LogicNode, int]:
    """Parse: and_expr (OR and_expr)*."""
    left, index = _parse_and_expr(tokens, index)
    or_children: List[LogicNode] = [left]
    while index < len(tokens) and _is_or_token(tokens[index]):
        index += 1
        right, index = _parse_and_expr(tokens, index)
        or_children.append(right)
    if len(or_children) == 1:
        return or_children[0], index
    return LogicNode(node_type="OR", children=or_children, payload={}), index


def _parse_and_expr(
    tokens: List[AttributeTokenModel], index: int
) -> Tuple[LogicNode, int]:
    """Parse: not_expr (AND not_expr)*."""
    left, index = _parse_not_expr(tokens, index)
    and_children: List[LogicNode] = [left]
    while index < len(tokens) and _is_and_token(tokens[index]):
        index += 1
        right, index = _parse_not_expr(tokens, index)
        and_children.append(right)
    if len(and_children) == 1:
        return and_children[0], index
    return LogicNode(node_type="AND", children=and_children, payload={}), index


def _parse_not_expr(
    tokens: List[AttributeTokenModel], index: int
) -> Tuple[LogicNode, int]:
    """Parse: NOT not_expr | atom."""
    if index < len(tokens) and _is_not_token(tokens[index]):
        index += 1
        child, index = _parse_not_expr(tokens, index)
        return LogicNode(node_type="NOT", children=[child], payload={}), index
    return _parse_atom(tokens, index)


def _parse_atom(
    tokens: List[AttributeTokenModel], index: int
) -> Tuple[LogicNode, int]:
    """Parse: '(' expression ')' | ATTRIBUTE."""
    if index >= len(tokens):
        return LogicNode(node_type="ATTRIBUTE", children=[], payload={}), index
    tok = tokens[index]
    if _is_open_paren(tok):
        index += 1
        node, index = _parse_expression(tokens, index)
        if index < len(tokens) and _is_close_paren(tokens[index]):
            index += 1
        return node, index
    if tok.type == "ATTRIBUTE":
        leaf = _make_attribute_leaf(tok)
        return leaf, index + 1
    # Skip unknown tokens
    return LogicNode(node_type="ATTRIBUTE", children=[], payload={}), index + 1


def build_attribute_tree(attribute_section: AttributeSection) -> LogicNode:
    """Build AND/OR/NOT tree from AttributeToken list.

    Precedence: parentheses > NOT > AND > OR.
    """
    tokens = attribute_section.attribute_tokens
    if not tokens:
        return LogicNode(node_type="AND", children=[], payload={})
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
# decode_attribute
# ---------------------------------------------------------------------------


def decode_attribute(key: str, value: str) -> DecodedAttribute:
    """Decode a raw attribute key/value into human-readable form."""
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
            key=key, raw_value=value, human_readable=f"{key} = {value}", operator=""
        )


# --- Duration ---

_TIMESPAN_MAX_DAYS_THRESHOLD = 1_000_000


def _parse_timespan(ts: str) -> int:
    ts = ts.strip()
    if not ts:
        return 0
    main_part = ts
    if "." in ts:
        parts_by_dot = ts.split(".")
        if len(parts_by_dot) >= 2:
            if ":" not in parts_by_dot[-1]:
                main_part = ".".join(parts_by_dot[:-1])
    time_parts = main_part.replace(".", ":").split(":")
    if len(time_parts) == 3:
        h, m, s = int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
        return h * 3600 + m * 60 + s
    elif len(time_parts) == 4:
        d, h, m, s = (
            int(time_parts[0]),
            int(time_parts[1]),
            int(time_parts[2]),
            int(time_parts[3]),
        )
        return d * 86400 + h * 3600 + m * 60 + s
    return 0


def _is_timespan_max_value(ts: str) -> bool:
    try:
        main_part = ts
        if "." in ts:
            parts_by_dot = ts.split(".")
            if len(parts_by_dot) >= 2:
                if ":" not in parts_by_dot[-1]:
                    main_part = ".".join(parts_by_dot[:-1])
        day_str = main_part.split(".")[0].split(":")[0]
        return int(day_str) >= _TIMESPAN_MAX_DAYS_THRESHOLD
    except (ValueError, IndexError):
        return False


def _format_duration_seconds(total_seconds: int) -> str:
    if total_seconds < 60:
        return f"{total_seconds} сек"
    if total_seconds % 60 == 0:
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes} мин"
        if minutes % 60 == 0:
            return f"{minutes // 60} ч"
        return f"{minutes} мин"
    return f"{total_seconds // 60} мин"


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
        human = (
            f"Длительность {_format_duration_seconds(min_seconds)} — "
            f"{_format_duration_seconds(max_seconds)}"
        )
    return DecodedAttribute(
        key="Duration",
        raw_value=value,
        human_readable=human,
        operator=">=",
    )


def _decode_call_direction(value: str) -> DecodedAttribute:
    """Decode CallDirection attribute."""
    direction_map = {
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
    operator_map = {
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
    raw_list = raw_list.strip()
    if raw_list.startswith(","):
        raw_list = raw_list[1:]
    raw_list = raw_list.strip()
    items: list[str] = []
    if raw_list:
        items = [item.strip() for item in raw_list.split(",") if item.strip()]
    count = len(items)
    human = f"SIP-сервер из списка ({count} шт.)"
    return DecodedAttribute(
        key="UserDef5",
        raw_value=value,
        human_readable=human,
        operator=operator,
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
    channel_map = {
        "CLIENT": "Клиент",
        "OPERATOR": "Оператор",
        "ANY": "Любой",
    }
    human = f"Канал: {channel_map.get(value, value)}"
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
# detect_warnings
# ---------------------------------------------------------------------------


def detect_warnings(
    attributes: AttributeSection,
    token_section: TokenSection,
    phrase_groups: List[PhraseGroup],
) -> List[str]:
    """Detect potential issues in the parsed dictionary node.

    Checks:
        - Any token with is_error=True
        - Duplicate phrases (same words, case-insensitive)
        - All phrases in quotes (warning about coverage)
        - Empty phrase groups
        - No attribute filters (matches all calls)

    Args:
        attributes: parsed AttributeSection from the XML.
        token_section: parsed TokenSection from the XML.
        phrase_groups: extracted PhraseGroup list.

    Returns:
        List of warning description strings.
    """
    warnings: List[str] = []

    # 1. Error tokens in attributes
    for tok in attributes.attribute_tokens:
        if tok.is_error:
            warnings.append(f"Атрибутный токен с ошибкой: {tok.text}")

    # 2. Error tokens in token section
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
        if not pg.words:
            continue
        key = " ".join(pg.words).lower()
        seen_phrases[key] = seen_phrases.get(key, 0) + 1
    for phrase_key, count in seen_phrases.items():
        if count > 1:
            warnings.append(f"Дублирующая фраза ({count}×): «{phrase_key}»")

    # 5. All phrases in quotes — possible over-restriction
    if phrase_groups and all(pg.is_exact for pg in phrase_groups):
        warnings.append(
            "Все фразы в кавычках — морфологический поиск отключён, "
            "возможно снижение покрытия"
        )

    # 6. No attribute filters
    has_meaningful_attrs = any(
        t.type == "ATTRIBUTE" for t in attributes.attribute_tokens
    )
    if not has_meaningful_attrs:
        warnings.append(
            "Словарь без атрибутных фильтров — сработает на любых звонках"
        )

    return warnings

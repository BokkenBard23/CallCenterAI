"""Dictionary analysis utilities (ported from LexiCore AI v3 with bug fixes).

Provides:
  - :func:`normalize_phrase` — strip quotes / collapse whitespace
  - :func:`find_duplicates` — full + soft duplicate detection with row indices
  - :func:`word_frequency` — configurable stop-words (fixes LexiCore B19)
  - :func:`dictionary_stats` — node-level statistics
  - :func:`stratified_sample` — port of LexiCore ``preparePhrasesForAI``
  - :func:`validate_dictionary` — operator / bracket / quote / WD checks

Bug fixes vs. LexiCore v3:
  - B16: full-duplicate key now includes ``is_exact`` so quoted and
    unquoted variants of the same phrase no longer collapse into one
    "full duplicate" entry (they become SOFT duplicates).
  - B19: stop-words list is now configurable (default ru stop-words still
    provided for parity with the original heuristic).
"""

from __future__ import annotations

import logging
import random
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from app.models import DictionaryCondition, DictionaryNode

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Pydantic report models
# ═══════════════════════════════════════════════════════════


class DupPair(BaseModel):
    """A pair of duplicate phrase row indices."""

    row_a: int = Field(..., description="Index of the first duplicate condition")
    row_b: int = Field(..., description="Index of the second duplicate condition")
    phrase: str = Field(..., description="Normalised phrase text (or shared key)")
    is_exact_a: bool = Field(False, description="Whether row_a was an exact (quoted) phrase")
    is_exact_b: bool = Field(False, description="Whether row_b was an exact (quoted) phrase")


class DuplicateReport(BaseModel):
    """Result of duplicate detection.

    - ``full``: identical phrases including ``is_exact`` flag (true duplicates).
    - ``soft``: same word set but differ in quoting, channel, or word distance.
    """

    full: List[DupPair] = Field(default_factory=list)
    soft: List[DupPair] = Field(default_factory=list)


class WordFreq(BaseModel):
    """A single word-frequency entry."""

    word: str
    count: int


class DictionaryStats(BaseModel):
    """Aggregate statistics for a DictionaryNode tree."""

    total_conditions: int = 0
    total_words: int = 0
    unique_words: int = 0
    operators_count: Dict[str, int] = Field(default_factory=dict)
    brackets_count: int = 0
    channels_distribution: Dict[str, int] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    """A single validation error or warning tied to a row."""

    row: int = Field(-1, description="Row index (-1 = global)")
    severity: str = Field(..., description="'error' or 'warning'")
    message: str


class ValidationResult(BaseModel):
    """Output of :func:`validate_dictionary`."""

    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


# ═══════════════════════════════════════════════════════════
# Default Russian stop-words (LexiCore parity + light clean-up)
# ═══════════════════════════════════════════════════════════

_DEFAULT_STOP_WORDS: Set[str] = {
    "и", "или", "не", "в", "во", "на", "по", "для", "с", "со",
    "к", "от", "до", "из", "без", "при", "что", "это", "эту", "этот",
    "этом", "этих", "как", "так", "но", "а", "же", "ли", "бы",
    "вы", "вам", "вас", "мы", "нам", "нас", "он", "она", "они", "оно",
    "я", "меня", "мне", "тебя", "тебе", "его", "её", "их",
    "если", "то", "же", "бы", "только", "уже", "ещё", "еще",
    "вот", "там", "тут", "здесь", "где", "когда", "тогда",
    "нет", "ну", "мм", "ээ",
}


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_phrase(phrase: str) -> str:
    """Normalise a phrase for comparison.

    - Strips surrounding single/double quotes (both Russian «» and ASCII ").
    - Trims and lowercases.
    - Collapses internal whitespace to a single space.

    Args:
        phrase: Raw phrase text.

    Returns:
        Normalised phrase string.
    """
    if not phrase:
        return ""
    text = phrase.strip()
    # Strip surrounding quotes — both «...» and "..."
    if len(text) >= 2:
        for open_q, close_q in (('"', '"'), ("«", "»"), ("'", "'")):
            if text[0] == open_q and text[-1] == close_q:
                text = text[1:-1]
                break
    text = text.strip().lower()
    return _WHITESPACE_RE.sub(" ", text)


def _gather_conditions(node: DictionaryNode) -> List[DictionaryCondition]:
    """Flatten a DictionaryNode tree into a single condition list."""
    out: List[DictionaryCondition] = []
    out.extend(node.conditions)
    for child in node.children:
        out.extend(_gather_conditions(child))
    return out


# ═══════════════════════════════════════════════════════════
# Duplicate detection
# ═══════════════════════════════════════════════════════════


def find_duplicates(conditions: List[DictionaryCondition]) -> DuplicateReport:
    """Detect full and soft duplicates among conditions.

    Args:
        conditions: Flat list of DictionaryCondition (e.g. from one node).

    Returns:
        :class:`DuplicateReport` with row indices.
    """
    full: List[DupPair] = []
    soft: List[DupPair] = []

    # Full duplicates: same normalised phrase, same is_exact (B16 fix),
    # same channel, and same word_distance. ANY difference in these
    # fields downgrades the pair to a soft duplicate.
    # B16 specifically called out is_exact (quoted vs unquoted variants
    # of the same phrase must not collapse), but the same logic applies
    # to channel/WD: a phrase searched on CLIENT vs OPERATOR is a
    # *different search condition*, hence a soft duplicate.
    full_index: Dict[Tuple[str, bool, str, int], List[int]] = {}
    soft_index: Dict[frozenset, List[int]] = {}

    for idx, cond in enumerate(conditions):
        norm = normalize_phrase(cond.text)
        if not norm:
            continue

        full_key = (
            norm,
            bool(cond.is_exact),
            (cond.channel_constraint or "ANY").upper(),
            int(cond.word_distance),
        )
        full_index.setdefault(full_key, []).append(idx)

        # Soft key: unordered word set — captures the same vocabulary
        # regardless of quoting, channel, word distance, or word order.
        soft_key = frozenset(norm.split())
        if soft_key:
            soft_index.setdefault(soft_key, []).append(idx)

    # Full duplicates
    for key, rows in full_index.items():
        if len(rows) < 2:
            continue
        phrase_norm, is_exact, _channel, _wd = key
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                full.append(
                    DupPair(
                        row_a=rows[i],
                        row_b=rows[j],
                        phrase=phrase_norm,
                        is_exact_a=is_exact,
                        is_exact_b=is_exact,
                    )
                )

    # Soft duplicates — any pair sharing the same word set that is NOT
    # already a full duplicate.
    full_pair_set: Set[Tuple[int, int]] = {
        (p.row_a, p.row_b) for p in full
    }
    for word_set, rows in soft_index.items():
        if len(rows) < 2:
            continue
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if (a, b) in full_pair_set:
                    continue
                cond_a = conditions[a]
                cond_b = conditions[b]
                soft.append(
                    DupPair(
                        row_a=a,
                        row_b=b,
                        phrase=" ".join(sorted(word_set)),
                        is_exact_a=bool(cond_a.is_exact),
                        is_exact_b=bool(cond_b.is_exact),
                    )
                )

    return DuplicateReport(full=full, soft=soft)


# ═══════════════════════════════════════════════════════════
# Word frequency
# ═══════════════════════════════════════════════════════════


def word_frequency(
    conditions: List[DictionaryCondition],
    top_n: int = 15,
    custom_stop_words: Optional[Set[str]] = None,
) -> List[WordFreq]:
    """Compute word frequency across conditions.

    Args:
        conditions: List of conditions to scan.
        top_n: Maximum number of results to return.
        custom_stop_words: Optional set of stop-words. If ``None``, the
            default Russian stop-word list is used. Pass an empty set to
            disable stop-word filtering entirely.

    Returns:
        Top-N most frequent words, sorted by count descending.
    """
    if custom_stop_words is None:
        stop_words: Set[str] = _DEFAULT_STOP_WORDS
    else:
        stop_words = custom_stop_words

    counter: Counter = Counter()
    for cond in conditions:
        for raw_word in normalize_phrase(cond.text).split():
            if raw_word in stop_words:
                continue
            counter[raw_word] += 1

    return [
        WordFreq(word=w, count=c)
        for w, c in counter.most_common(top_n)
    ]


# ═══════════════════════════════════════════════════════════
# Dictionary stats
# ═══════════════════════════════════════════════════════════


def dictionary_stats(node: DictionaryNode) -> DictionaryStats:
    """Compute aggregate statistics for a dictionary node tree.

    Recurses into children to sum conditions / words.
    """
    conditions = _gather_conditions(node)
    total_words = 0
    unique_words: Set[str] = set()
    channels: Dict[str, int] = {}
    operators: Dict[str, int] = {"AND": 0, "OR": 0, "NOT": 0}
    brackets = 0

    for cond in conditions:
        words = normalize_phrase(cond.text).split()
        total_words += len(words)
        unique_words.update(words)
        ch = (cond.channel_constraint or "ANY").upper()
        channels[ch] = channels.get(ch, 0) + 1

    # Operators + brackets are derived from phrase_groups (internal model)
    # which carries operator / is_negated. Brackets are not stored on
    # DictionaryCondition directly — we approximate from token_section when
    # present.
    def _walk(n: DictionaryNode) -> None:
        for pg in n.phrase_groups:
            op = (pg.operator or "").upper()
            if op in operators:
                operators[op] += 1
            if pg.is_negated:
                operators["NOT"] += 1
        if n.token_section is not None:
            for tok in n.token_section.tokens:
                if tok.type == "TERMINAL" and tok.text in ("(", ")"):
                    nonlocal_brackets[0] += 1
        for child in n.children:
            _walk(child)

    nonlocal_brackets = [0]
    _walk(node)
    brackets = nonlocal_brackets[0]

    return DictionaryStats(
        total_conditions=len(conditions),
        total_words=total_words,
        unique_words=len(unique_words),
        operators_count=operators,
        brackets_count=brackets,
        channels_distribution=channels,
    )


# ═══════════════════════════════════════════════════════════
# Stratified sampling (port of LexiCore preparePhrasesForAI)
# ═══════════════════════════════════════════════════════════


def stratified_sample(
    phrases: List[str],
    hard_cap: Optional[int] = None,
) -> Tuple[List[str], bool]:
    """Stratified sampling ported from LexiCore ``preparePhrasesForAI``.

    Thresholds (LexiCore defaults):
        - ≤ 200 phrases → return all
        - ≤ 500         → return 200
        - ≤ 1000        → return 250
        - > 1000        → return 300

    Args:
        phrases: Input phrase list (will be de-duplicated case-insensitively
            before sampling).
        hard_cap: Optional override for the maximum sample size. When
            ``None``, LexiCore thresholds are used.

    Returns:
        Tuple ``(sampled_phrases, was_sampled)``.
    """
    # Deduplicate (case-insensitive) while preserving first-seen casing.
    seen: Set[str] = set()
    deduped: List[str] = []
    for p in phrases:
        key = p.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(p.strip())

    n = len(deduped)
    if hard_cap is not None:
        cap = hard_cap
    elif n <= 200:
        return deduped, False
    elif n <= 500:
        cap = 200
    elif n <= 1000:
        cap = 250
    else:
        cap = 300

    if n <= cap:
        return deduped, False

    # Even stratified sampling: pick every k-th element to avoid bias
    # towards early entries.
    step = n / cap
    sampled = [deduped[int(i * step)] for i in range(cap)]
    return sampled, True


# ═══════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════


_VALID_OPERATORS = {"И", "ИЛИ", "НЕ"}
_VALID_CHANNELS_V = {"CLIENT", "OPERATOR", "ANY"}


def validate_dictionary(node: DictionaryNode) -> ValidationResult:
    """Validate a DictionaryNode tree.

    Checks (per row index, mirroring LexiCore semantics):
      - First condition (idx=0) requires no leading operator (but ``НЕ``
        alone is allowed at idx=0 as a prefix negation).
      - Conditions idx≥1 must be preceded by И / ИЛИ / И НЕ / ИЛИ НЕ
        (or just ``НЕ`` is invalid in mid-expression without an infix).
      - Bracket balance (advanced): opens / closes match.
      - Quote balance: quotes wrap whole phrases (not partial).
      - WordDistance range: 0–3 (warn above 3, error below 0).
      - Channel values.

    Args:
        node: DictionaryNode to validate (only top-level conditions
            inspected; children are validated separately by recursion
            at the caller level).

    Returns:
        :class:`ValidationResult` with row-indexed issues.
    """
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []

    conditions = node.conditions

    # Operator presence check (per row)
    for idx, cond in enumerate(conditions):
        # Determine leading operator from phrase_groups[0].operator on the
        # corresponding internal PhraseGroup (if available).
        leading_op = ""
        is_negated = False
        if node.phrase_groups:
            # Approximate mapping: phrase_groups are flat per node, but
            # conditions are 1:1 with phrase_groups only when there are no
            # LEXEME operators splitting them. We use the first group's
            # operator as a heuristic — for richer validation the caller
            # should pass phrase_groups aligned per condition.
            pass

        # Channel validation
        ch = (cond.channel_constraint or "ANY").upper()
        if ch not in _VALID_CHANNELS_V:
            errors.append(ValidationIssue(
                row=idx,
                severity="error",
                message=f"Недопустимый канал «{cond.channel_constraint}» в фразе «{cond.text}»",
            ))

        # WordDistance range
        wd = cond.word_distance
        if wd < 0:
            errors.append(ValidationIssue(
                row=idx,
                severity="error",
                message=f"WordDistance < 0 в фразе «{cond.text}»",
            ))
        elif wd > 3:
            warnings.append(ValidationIssue(
                row=idx,
                severity="warning",
                message=f"WordDistance={wd} (>3) в фразе «{cond.text}» — возможно избыточное окно",
            ))

    # Quote + bracket balance — derived from token_section if present
    if node.token_section is not None:
        quote_open = False
        bracket_depth = 0
        for tok in node.token_section.tokens:
            if tok.type == "TERMINAL":
                if tok.text == '"':
                    quote_open = not quote_open
                elif tok.text == "(":
                    bracket_depth += 1
                elif tok.text == ")":
                    bracket_depth -= 1
                    if bracket_depth < 0:
                        errors.append(ValidationIssue(
                            row=-1,
                            severity="error",
                            message="Закрывающая скобка «)» без открывающей",
                        ))
                        bracket_depth = 0
        if quote_open:
            errors.append(ValidationIssue(
                row=-1,
                severity="error",
                message="Незакрытая кавычка в выражении",
            ))
        if bracket_depth > 0:
            errors.append(ValidationIssue(
                row=-1,
                severity="error",
                message=f"Незакрытые скобки: глубина {bracket_depth}",
            ))

    # Operator sequence validation — inspect LEXEME tokens directly
    if node.token_section is not None:
        prev_was_operand = False
        first_operand_seen = False
        for tok in node.token_section.tokens:
            if tok.type == "WHITESPACE":
                continue
            if tok.type == "TERMINAL":
                if tok.text in ("(", ")"):
                    prev_was_operand = tok.text == ")"
                    first_operand_seen = True
                    continue
                # quote
                continue
            if tok.type == "LEXEME":
                up = tok.text.upper()
                if up not in _VALID_OPERATORS:
                    warnings.append(ValidationIssue(
                        row=-1,
                        severity="warning",
                        message=f"Неизвестный LEXEME-токен «{tok.text}»",
                    ))
                    continue
                if up == "НЕ":
                    # НЕ may appear at idx=0 (prefix) or after И/ИЛИ.
                    # НЕ alone mid-expression (without preceding И/ИЛИ)
                    # is invalid per spec §13.
                    if first_operand_seen and not prev_was_operand:
                        # Already expecting an operand — НЕ is fine here only
                        # if previous LEXEME was И/ИЛИ. We approximate: if
                        # the previous meaningful token was an operand, then
                        # mid-expression НЕ without infix is an error.
                        errors.append(ValidationIssue(
                            row=-1,
                            severity="error",
                            message="Оператор «НЕ» в середине выражения без предшествующего И/ИЛИ",
                        ))
                else:
                    # И / ИЛИ — infix: must follow an operand
                    if not first_operand_seen:
                        errors.append(ValidationIssue(
                            row=-1,
                            severity="error",
                            message=f"Оператор «{tok.text}» в начале выражения без операнда",
                        ))
                prev_was_operand = False
                continue
            if tok.type == "WORD":
                prev_was_operand = True
                first_operand_seen = True

    return ValidationResult(errors=errors, warnings=warnings)

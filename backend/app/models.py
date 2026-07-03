"""Pydantic models for request/response schemas.

Models are organised to match the spec-chunk-2 response formats:
  - RTF upload: DialogueTurn, ParsedDialog, UploadRtfResponse
  - Dictionary upload: DictionaryCondition, DictionaryNode, DictionaryValidation, UploadDictionaryResponse
  - Analysis: TextSegment, DictMatch, SearchResult, AnalysisRequest, AnalysisResponse
  - LLM: LLMResult
  - Embedding (FRIDA): EmbeddingRequest, EmbeddingResponse
  - Chunking: ChunkMetadata, Chunk

CRITICAL: TextSegment and DictMatch field names/types are the frontend contract — do NOT change.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# RTF Upload Models
# ═══════════════════════════════════════════════════════════

class DialogueTurn(BaseModel):
    """A single turn in a parsed dialogue."""

    turn_index: int = Field(..., description="Sequential turn number (0-based)")
    speaker: str = Field(..., description="Speaker role: 'Клиент' or 'Сотрудник'")
    text: str = Field(..., description="Verbatim text of the turn")
    timestamp: Optional[str] = Field(None, description="Timestamp if available in RTF")


class ParsedDialog(BaseModel):
    """Full parsed dialogue extracted from an RTF file."""

    filename: str = Field(..., description="Original RTF filename")
    turns: List[DialogueTurn] = Field(default_factory=list, description="Ordered dialogue turns")
    total_turns: int = Field(0, description="Total number of turns")
    client_turns: int = Field(0, description="Number of client turns")
    employee_turns: int = Field(0, description="Number of employee turns")
    parsed_at: datetime = Field(default_factory=datetime.now, description="Parse timestamp")


class UploadRtfResponse(BaseModel):
    """Response after uploading and parsing an RTF file."""

    session_id: str = Field(..., description="Session identifier for subsequent requests")
    dialogue: Optional[List[DialogueTurn]] = Field(None, description="Parsed dialogue turns")
    turn_count: int = Field(0, description="Total number of turns")
    raw_text_length: int = Field(0, description="Length of raw decoded text")
    error: Optional[str] = Field(None, description="Error message if parsing failed")


# ═══════════════════════════════════════════════════════════
# Dictionary Upload Models (hierarchical XML dictionaries)
# ═══════════════════════════════════════════════════════════

# --- Sub-models ported from dict-analyzer (enriched XML parsing) ---

class SavedState(BaseModel):
    """Meta section from <SavedState> in the XML.

    Default is_actual=False to avoid false-positive 'data exists' signal.
    When the XML <SavedState> element is absent, the parser returns None.
    When <SavedState> exists but <IsActual> is missing, we conservatively
    assume False rather than claiming data was actually found.
    """

    total_found: int = 0
    last_update_time: str = ""
    execution_time: str = ""
    is_actual: bool = False
    is_cancelled: bool = False


class SearchAttribute(BaseModel):
    """Key/Value pair inside <SearchAttribute>."""

    key: str = ""
    value: str = ""


class AttributeTokenModel(BaseModel):
    """Single <AttributeToken> element."""

    text: str = ""
    type: Literal["TERMINAL", "LEXEME", "ATTRIBUTE"] = "ATTRIBUTE"
    search_attribute: SearchAttribute = Field(default_factory=SearchAttribute)
    is_error: bool = False


class AttributeSection(BaseModel):
    """Wrapper for the <Attributes> section."""

    attribute_tokens: List[AttributeTokenModel] = Field(default_factory=list)


class TokenModel(BaseModel):
    """Single <Token> element with per-token Properties."""

    text: str = ""
    type: Literal["TERMINAL", "WHITESPACE", "LEXEME", "WORD"] = "WORD"
    is_error: bool = False
    channel: str = ""
    word_distance: str = ""


class TokenSection(BaseModel):
    """Wrapper for the <Tokens> section."""

    tokens: List[TokenModel] = Field(default_factory=list)


class PhraseGroup(BaseModel):
    """Grouped phrase extracted from <Tokens>.

    words:         list of WORD token texts
    channel:       Channel value (CLIENT / OPERATOR / ANY / "")
    word_distance: WordDistance from token Properties (max per group)
    is_exact:      True if phrase is inside TERMINAL quotes (exact match)
    """

    words: List[str] = Field(default_factory=list)
    channel: str = ""
    word_distance: int = 0
    is_exact: bool = False


class DisplayToken(BaseModel):
    """Token ready for frontend rendering with channel color mapping.

    Bridges the gap between raw TokenModel (from XML) and UI rendering.
    TERMINAL quotes are absorbed into PHRASE type tokens with is_exact=True.

    Channel color mapping (CSS custom properties):
      OPERATOR → --dict-channel-operator (#81c784 green)
      CLIENT   → --dict-channel-client   (#4fc3f7 blue)
      ANY      → --dict-channel-any       (#ffb74d orange)
    """

    text: str = Field(..., description="Display text of the token")
    type: Literal["WORD", "PHRASE", "LEXEME", "BRACKET"] = Field(
        ...,
        description="Display type: WORD (single), PHRASE (grouped), LEXEME (ИЛИ/И/НЕ), BRACKET (parentheses)",
    )
    channel: Literal["OPERATOR", "CLIENT", "ANY"] = Field(
        "ANY",
        description="Channel for color rendering: OPERATOR=green, CLIENT=blue, ANY=orange",
    )
    word_distance: int = Field(2, description="Word distance for this token/group (max of group)")
    is_error: bool = Field(False, description="Whether this token has a parse error")
    is_exact: bool = Field(False, description="True if phrase was inside TERMINAL quotes (exact match)")


class LogicNode(BaseModel):
    """Node of the AND/OR/NOT logic tree.

    node_type: AND | OR | NOT | ATTRIBUTE | PHRASE | GROUP
    children:  child nodes (empty for leaves)
    payload:   decoded data for leaf nodes (e.g. DecodedAttribute dict)
    """

    node_type: Literal["AND", "OR", "NOT", "ATTRIBUTE", "PHRASE", "GROUP"] = "AND"
    children: List["LogicNode"] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)


class DecodedAttribute(BaseModel):
    """Attribute with decoded (human-readable) value."""

    key: str
    raw_value: str
    human_readable: str
    operator: str = ""


# --- Main dictionary models ---

class DictionaryCondition(BaseModel):
    """A single search condition extracted from XML dictionary tokens.

    Maps from XML <Token> elements with Type=WORD.
    Consecutive WORD tokens form a single phrase.

    Extended fields (AG-UIREWORK-5):
      phrase_groups:   OR groups of words — [[w1, w2], [w3, w4]] from ИЛИ-separated tokens.
      nested_phrases:  Phrases after the main phrase (from parent-child token structure).
      is_exception:    Whether the phrase is prefixed with НЕ (negation/exclusion).
      exception_phrases: Phrases that come after НЕ (exception keywords).
    """

    text: str = Field(..., description="Phrase text to search for (from concatenated WORD tokens)")
    word_distance: int = Field(2, description="Allowed word distance for sliding window")
    word_count: int = Field(0, description="Number of words in phrase (from tokenizer)")
    channel_constraint: str = Field(
        "ANY",
        description="Channel filter: CLIENT, OPERATOR, or ANY",
    )
    without_list: List[str] = Field(
        default_factory=list,
        description="WITHOUT phrases that suppress this condition if found",
    )
    is_exact: bool = Field(
        False,
        description="If True, phrase must match EXACTLY (no morphological variation, no word reordering)",
    )
    # --- Extended fields for UI/UX rework (AG-UIREWORK-5) ---
    phrase_groups: List[List[str]] = Field(
        default_factory=list,
        description="OR groups of words: [[w1, w2], [w3, w4]] — each inner list is an alternative",
    )
    nested_phrases: List[str] = Field(
        default_factory=list,
        description="Phrases after the main phrase (from nested token structure)",
    )
    is_exception: bool = Field(
        False,
        description="Whether this phrase is prefixed with НЕ (negation/exclusion marker)",
    )
    exception_phrases: List[str] = Field(
        default_factory=list,
        description="Exception phrases (words/phrases after НЕ — exclusion keywords)",
    )


class DictionaryNode(BaseModel):
    """A parsed dictionary node with hierarchical parent-child support.

    Maps from XML <SpeechLabRequest> element.
    Children come from nested <Requests>/<SpeechLabRequest> elements.
    """

    id: str = Field(..., description="Dictionary unique identifier (from XML <Id>)")
    name: str = Field(..., description="Dictionary name (from XML <Name>)")
    parent_name: Optional[str] = Field(
        None,
        description="Parent dictionary name (None = root dictionary)",
    )
    conditions: List[DictionaryCondition] = Field(
        default_factory=list,
        description="Search conditions extracted from tokens",
    )
    children: List["DictionaryNode"] = Field(
        default_factory=list,
        description="Child dictionaries (from nested SpeechLabRequest)",
    )
    condition_count: int = Field(0, description="Number of search conditions")
    has_children: bool = Field(False, description="Whether this dictionary has children")
    children_count: int = Field(0, description="Number of child dictionaries")
    # --- Enriched fields from dict-analyzer integration ---
    saved_state: Optional[SavedState] = Field(
        None,
        description="Parsed <SavedState> metadata (total_found, is_actual, etc.)",
    )
    attributes: Optional[AttributeSection] = Field(
        None,
        description="Parsed <Attributes>/<AttributeTokens> section",
    )
    is_remainder: bool = Field(
        False,
        description="True if this node is a <SpeechLabRemainderRequest>",
    )
    phrase_groups: List[PhraseGroup] = Field(
        default_factory=list,
        description="Phrase groups with per-word Channel/WordDistance and is_exact flag",
    )
    attribute_tree: Optional[LogicNode] = Field(
        None,
        description="AND/OR/NOT logic tree built from attribute tokens",
    )
    # --- SpeechLab display token support ---
    token_section: Optional[TokenSection] = Field(
        None,
        description="Raw parsed <Tokens> section for DisplayToken conversion (SpeechLab UI)",
    )


class DictionaryValidation(BaseModel):
    """Validation results for a parsed XML dictionary."""

    valid: bool = Field(True, description="Whether the dictionary passed validation")
    warnings: List[str] = Field(default_factory=list, description="Non-critical issues")
    errors: List[str] = Field(default_factory=list, description="Critical validation errors")


class UploadDictionaryResponse(BaseModel):
    """Response after uploading and parsing an XML dictionary."""

    session_id: str = Field(..., description="Session identifier for subsequent requests")
    dictionary: Optional[DictionaryNode] = Field(None, description="Parsed dictionary tree")
    validation: DictionaryValidation = Field(
        default_factory=DictionaryValidation,
        description="Validation results",
    )
    error: Optional[str] = Field(None, description="Error message if parsing failed")
    # --- SpeechLab display tokens (pre-grouped for frontend rendering) ---
    display_tokens: Optional[List[DisplayToken]] = Field(
        None,
        description="Pre-grouped display tokens for the root dictionary (SpeechLab UI)",
    )


# ═══════════════════════════════════════════════════════════
# Analysis Models
# ═══════════════════════════════════════════════════════════

class TextSegment(BaseModel):
    """A text segment within a dialogue turn for matching.

    FRONTEND CONTRACT — do NOT change field names or types.
    """

    turn_index: int = Field(..., description="Turn index in the dialogue")
    text: str = Field(..., description="Text content of the segment")
    speaker: str = Field(..., description="Speaker role")


class DictMatch(BaseModel):
    """A match result for a dictionary phrase against the dialogue.

    FRONTEND CONTRACT — do NOT change field names or types.
    The `quarter` field carries the dictionary name.
    The `word_distance_used` field encodes hierarchy level (1=root, 2=child, ...).
    The `cascade_order` field (new) indicates dictionary position in cascade (1-based).

    Highlight level formula (frontend):
      highlight_level = (cascade_order - 1) * 2 + word_distance_used
    This gives:
      Dict 1 root→L1(yellow), child→L2(green)
      Dict 2 root→L3(cyan),   child→L4(pink)
      Dict 3 root→L5(purple), child→L6(orange)

    NEW FIELDS for correct highlighting:
      matched_text: the actual text from the dialogue that matched (may differ from phrase_text
                    due to morphological variations, word reordering, or extra filler words)
      matched_start: character offset of match start within the turn text
      matched_end: character offset of match end within the turn text
    """

    phrase_text: str = Field(..., description="Dictionary phrase text (from dictionary, NOT from dialog)")
    matched_text: str = Field("", description="Actual matched text from the dialog (for highlighting)")
    matched_start: int = Field(-1, description="Character offset of match start in turn text (-1 = not computed)")
    matched_end: int = Field(-1, description="Character offset of match end in turn text (-1 = not computed)")
    quarter: str = Field(..., description="Dictionary name that found this match")
    turn_index: int = Field(..., description="Turn where the match was found")
    speaker: str = Field(..., description="Speaker of the matched turn")
    match_type: str = Field("sliding_window", description="Match algorithm used")
    word_distance_used: int = Field(0, description="Hierarchy level within dictionary (1=root, 2=child, ...)")
    cascade_order: int = Field(1, description="Dictionary position in cascade sequence (1-based)")
    is_exact_match: bool = Field(
        False,
        description="True if this match was found using exact (non-morphological) matching",
    )
    # --- Extended fields for UI/UX rework (AG-UIREWORK-1, AG-UIREWORK-5) ---
    word_distance: int = Field(
        0,
        description="Original word_distance from the DictionaryCondition (0 = exact word match, higher = more flexible window)",
    )
    channel_constraint: str = Field(
        "ANY",
        description="Channel constraint from the DictionaryCondition: CLIENT, OPERATOR, or ANY",
    )
    dict_level: int = Field(
        1,
        description="Dictionary level in hierarchy (1=Q1, 2=Q2, 3=Q3). Alias for word_distance_used, explicit for frontend.",
    )


class AnalysisRequest(BaseModel):
    """Request to run analysis on a session's dialogue."""

    session_id: str = Field(..., description="Session with uploaded dialogue")
    dictionary_ids: List[str] = Field(
        default_factory=list,
        description="Dictionary names to include in search (empty = all)",
    )
    llm_provider: str = Field("ollama", description="LLM provider: ollama, yandexgpt, gigachat, beeline")
    llm_model: Optional[str] = Field(None, description="Optional model override")
    include_summary: bool = Field(False, description="Whether to include LLM summary")
    include_restructured: bool = Field(
        False,
        description="Whether to include restructured dialogue",
    )


class SearchResult(BaseModel):
    """Search results from hierarchical dictionary matching."""

    segments: List[TextSegment] = Field(
        default_factory=list,
        description="Dialogue segments for rendering",
    )
    total_matches: int = Field(0, description="Total phrase matches found")
    matches: List[DictMatch] = Field(
        default_factory=list,
        description="All matches found across all dictionaries",
    )
    matches_by_level: Dict[str, int] = Field(
        default_factory=dict,
        description="Match counts by hierarchy level (e.g. {'1': 2, '2': 1})",
    )
    search_source: Optional[str] = Field(
        None,
        description="Search method used: 'morph' (morphological), 'semantic' (FRIDA only), "
        "'hybrid' (combined), or None (not specified)",
    )


class AnalysisResponse(BaseModel):
    """Full analysis response combining search results and optional LLM insights."""

    analysis_id: str = Field("", description="Unique analysis identifier")
    session_id: str = Field(..., description="Session identifier")
    status: str = Field("pending", description="Analysis status: pending, running, completed, failed, partial")
    search_result: Optional[SearchResult] = Field(None, description="Dictionary matching results")
    llm_result: Optional[LLMResult] = Field(None, description="LLM analysis results (if requested)")
    error: Optional[str] = Field(None, description="Error message if analysis failed")
    warning: Optional[str] = Field(None, description="Warning message for partial success")


# ═══════════════════════════════════════════════════════════
# LLM Enums (validation-only — LLMResult fields stay str for API compat)
# ═══════════════════════════════════════════════════════════

class ClientSentiment(str, enum.Enum):
    """Valid client sentiment values.

    Accepts both English and Russian forms; the *value* is always
    the canonical English string so that downstream code can compare
    against ``ClientSentiment.positive`` etc.
    """

    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    mixed = "mixed"


class Resolution(str, enum.Enum):
    """Valid resolution values.

    Accepts both English and Russian forms; the *value* is always
    the canonical English string.
    """

    resolved = "resolved"
    unresolved = "unresolved"
    escalated = "escalated"
    partial = "partial"


# Mapping from Russian → canonical English enum value.
_CLIENT_SENTIMENT_RU_MAP: Dict[str, str] = {
    "позитивный": ClientSentiment.positive.value,
    "нейтральный": ClientSentiment.neutral.value,
    "негативный": ClientSentiment.negative.value,
    "смешанный": ClientSentiment.mixed.value,
}

_RESOLUTION_RU_MAP: Dict[str, str] = {
    "решено": Resolution.resolved.value,
    "не решено": Resolution.unresolved.value,
    "эскалация": Resolution.escalated.value,
    "частично": Resolution.partial.value,
}


# ═══════════════════════════════════════════════════════════
# LLM Models
# ═══════════════════════════════════════════════════════════

class LLMResult(BaseModel):
    """Structured result from LLM analysis of a dialogue."""

    summary: str = Field("", description="Brief summary of the dialogue")
    restructured_dialogue: str = Field(
        "",
        description="LLM-restructured dialogue with alternating short replicas",
    )
    topic: str = Field("", description="Identified topic of the dialogue")
    result: str = Field("", description="Overall outcome / resolution status")
    key_points: List[str] = Field(
        default_factory=list,
        description="Key points discussed in the dialogue",
    )
    client_sentiment: str = Field(
        "",
        description="Assessed client sentiment (positive/neutral/negative/mixed)",
    )
    resolution: str = Field(
        "",
        description="How the dialogue was resolved (resolved/unresolved/escalated/partial)",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")
    raw_response: Optional[Any] = Field(
        None,
        description="Raw LLM response for debugging (optional)",
    )


# ═══════════════════════════════════════════════════════════
# LLM Analysis Models (IP-3.2 – IP-3.5)
# ═══════════════════════════════════════════════════════════

# --- IP-3.2: Sentiment Analysis (per-utterance) ---

class UtteranceSentiment(BaseModel):
    """Sentiment assessment for a single dialogue utterance."""

    turn_index: int = Field(..., description="Sequential turn number (0-based)")
    speaker: str = Field(..., description="Speaker role: 'Клиент' or 'Сотрудник'")
    sentiment: str = Field(
        "neutral",
        description="Sentiment: positive / neutral / negative / mixed",
    )
    confidence: float = Field(
        0.5,
        description="Confidence score [0.0, 1.0]",
    )
    text_snippet: str = Field(
        "",
        description="Short excerpt of the utterance text",
    )


class SentimentAnalysisResult(BaseModel):
    """Result of per-utterance sentiment analysis."""

    utterances: List[UtteranceSentiment] = Field(
        default_factory=list,
        description="Per-utterance sentiment assessments",
    )
    overall_sentiment: str = Field(
        "neutral",
        description="Overall dialogue sentiment: positive / neutral / negative / mixed",
    )
    sentiment_trajectory: str = Field(
        "stable",
        description="Sentiment trajectory over the dialogue: improving / declining / stable / volatile",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# --- IP-3.3: Conflict Detection ---

class EscalationPoint(BaseModel):
    """A moment in the dialogue where conflict escalates."""

    turn_index: int = Field(..., description="Turn number where escalation occurs")
    speaker: str = Field(..., description="Speaker who escalates")
    trigger: str = Field(..., description="What triggered the escalation")
    level: str = Field(
        "low",
        description="Escalation level at this point: none / low / medium / high",
    )


class ConflictAnalysisResult(BaseModel):
    """Result of conflict / aggression detection analysis."""

    has_conflict: bool = Field(False, description="Whether any conflict was detected")
    conflict_level: str = Field(
        "none",
        description="Overall conflict level: none / low / medium / high / critical",
    )
    escalation_points: List[EscalationPoint] = Field(
        default_factory=list,
        description="Specific escalation moments in the dialogue",
    )
    de_escalation_attempts: int = Field(
        0,
        description="Number of de-escalation attempts by the employee",
    )
    justification: str = Field(
        "",
        description="Textual justification of the conflict assessment",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# --- IP-3.4: Profanity Detection ---

class ProfanityInstance(BaseModel):
    """A single instance of profanity or offensive language."""

    turn_index: int = Field(..., description="Turn number where profanity occurs")
    speaker: str = Field(..., description="Speaker who used profanity")
    category: str = Field(
        "slang",
        description="Category: obscenity / insult / slur / slang",
    )
    severity: str = Field(
        "low",
        description="Severity level: low / medium / high",
    )
    context: str = Field(
        "",
        description="Surrounding context for the profanity instance",
    )


class ProfanityAnalysisResult(BaseModel):
    """Result of profanity / offensive language detection."""

    has_profanity: bool = Field(
        False, description="Whether any profanity was detected"
    )
    instances: List[ProfanityInstance] = Field(
        default_factory=list,
        description="All detected profanity instances",
    )
    total_count: int = Field(
        0, description="Total number of profanity instances found"
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# --- IP-3.5: Topic Detection ---

class DetectedTopic(BaseModel):
    """A topic detected in the dialogue."""

    name: str = Field(..., description="Topic name / label")
    confidence: float = Field(
        0.5,
        description="Confidence score [0.0, 1.0]",
    )
    key_phrases: List[str] = Field(
        default_factory=list,
        description="Key phrases associated with this topic",
    )
    turn_indices: List[int] = Field(
        default_factory=list,
        description="Turn indices where this topic is discussed",
    )


class TopicAnalysisResult(BaseModel):
    """Result of topic detection analysis."""

    topics: List[DetectedTopic] = Field(
        default_factory=list,
        description="All detected topics",
    )
    primary_topic: str = Field(
        "",
        description="The main topic of the dialogue",
    )
    topic_count: int = Field(
        0, description="Number of distinct topics detected"
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# ═══════════════════════════════════════════════════════════
# IP-4.1: Quality Scoring (12 categories for dialogue evaluation)
# ═══════════════════════════════════════════════════════════


class QualityLevel(str, enum.Enum):
    """Quality level for a category assessment.

    Values are lowercase English, consistent with ClientSentiment / Resolution.
    """

    high = "high"
    medium = "medium"
    low = "low"


class QualityCategory(str, enum.Enum):
    """12 quality categories for call-centre dialogue evaluation.

    Values are snake_case English — stable identifiers that IP-4.2 UI will
    reference. Do NOT rename enum members (backward-compat contract).
    """

    communication_skills = "communication_skills"
    problem_solving = "problem_solving"
    product_knowledge = "product_knowledge"
    responsiveness = "responsiveness"
    professionalism = "professionalism"
    empathy = "empathy"
    accuracy = "accuracy"
    efficiency = "efficiency"
    follow_up_procedures = "follow_up_procedures"
    conflict_resolution = "conflict_resolution"
    compliance = "compliance"
    customer_education = "customer_education"


# Human-readable Russian labels for each category (used in prompts & UI).
QUALITY_CATEGORY_LABELS: Dict[str, str] = {
    QualityCategory.communication_skills.value: "Навыки общения",
    QualityCategory.problem_solving.value: "Решение проблем",
    QualityCategory.product_knowledge.value: "Знание продукта",
    QualityCategory.responsiveness.value: "Отзывчивость",
    QualityCategory.professionalism.value: "Профессионализм",
    QualityCategory.empathy.value: "Эмпатия",
    QualityCategory.accuracy.value: "Точность информации",
    QualityCategory.efficiency.value: "Эффективность",
    QualityCategory.follow_up_procedures.value: "Порядок последующих действий",
    QualityCategory.conflict_resolution.value: "Разрешение конфликтов",
    QualityCategory.compliance.value: "Соблюдение стандартов",
    QualityCategory.customer_education.value: "Обучение клиента",
}


class CategoryScore(BaseModel):
    """Score for a single quality category."""

    category: QualityCategory = Field(
        ..., description="Quality category identifier",
    )
    level: QualityLevel = Field(
        ..., description="Assessment level: high / medium / low",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Numeric score [0.0, 1.0]. low≈0.33, medium≈0.66, high≈1.0",
    )
    justification: str = Field(
        "",
        description="Why this level was assigned (1-2 sentences)",
    )


class QualityScoreResult(BaseModel):
    """Result of quality scoring analysis across 12 categories."""

    session_id: str = Field("", description="Session identifier")
    categories: List[CategoryScore] = Field(
        default_factory=list,
        description="Per-category scores (all 12 categories)",
    )
    overall_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Average of all category scores",
    )
    overall_level: QualityLevel = Field(
        QualityLevel.medium,
        description="Derived from overall_score: low < 0.5, medium 0.5–0.75, high > 0.75",
    )
    strengths: List[str] = Field(
        default_factory=list,
        description="Categories with high score",
    )
    weaknesses: List[str] = Field(
        default_factory=list,
        description="Categories with low score",
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="1-3 actionable improvement suggestions",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# ═══════════════════════════════════════════════════════════
# IP-3.6–3.7: LLM Orchestrator & Unified Annotation
# ═══════════════════════════════════════════════════════════


class ProgressInfo(BaseModel):
    """Progress tracking for sequential LLM analysis steps.

    Designed to be serialisable for future SSE support (IP-2.3).
    """

    current_step: str = Field(
        "pending",
        description="Current step name: sentiment/conflict/profanity/topic/summary/done/pending",
    )
    completed_steps: List[str] = Field(
        default_factory=list,
        description="Steps that completed successfully",
    )
    remaining_steps: List[str] = Field(
        default_factory=list,
        description="Steps not yet started",
    )
    total_steps: int = Field(
        0,
        description="Total number of steps in the pipeline",
    )
    error_steps: List[str] = Field(
        default_factory=list,
        description="Steps that failed but were gracefully degraded",
    )


class AnalysisAnnotation(BaseModel):
    """Unified LLM analysis result combining all analysis types (IP-3.7).

    Wraps individual analysis results and progress info into a single
    model. Individual results are ``None`` when not run or when the
    step failed (graceful degradation).
    """

    session_id: str = Field(..., description="Session identifier")
    # Individual analysis results (None if not run or failed)
    sentiment: Optional[SentimentAnalysisResult] = Field(
        None,
        description="Per-utterance sentiment analysis result",
    )
    conflict: Optional[ConflictAnalysisResult] = Field(
        None,
        description="Conflict / aggression detection result",
    )
    profanity: Optional[ProfanityAnalysisResult] = Field(
        None,
        description="Profanity / offensive language detection result",
    )
    topic: Optional[TopicAnalysisResult] = Field(
        None,
        description="Topic detection result",
    )
    # Original summary analysis
    summary: Optional[LLMResult] = Field(
        None,
        description="Full dialogue summary (from analyze_dialogue)",
    )
    # Progress info
    progress: ProgressInfo = Field(
        ...,
        description="Pipeline progress tracking",
    )
    # Domain context (IP-6.1)
    domain: str = Field(
        "general",
        description="Domain type used for analysis: general | insurance | banking | healthcare | telecom",
    )
    # Metadata
    provider: str = Field(
        "none",
        description="LLM provider used (first successful)",
    )
    model: str = Field(
        "",
        description="LLM model identifier",
    )
    completed_at: str = Field(
        "",
        description="ISO-8601 timestamp when analysis completed",
    )
    analysis_source: str = Field(
        "orchestrator",
        description="Source of analysis: orchestrator | individual | none",
    )


# ═══════════════════════════════════════════════════════════
# Provider Models
# ═══════════════════════════════════════════════════════════

class ProviderInfo(BaseModel):
    """Information about a single LLM provider."""

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Display name")
    models: List[str] = Field(default_factory=list, description="Available models")
    configured: bool = Field(False, description="Whether provider has required credentials")
    available: bool = Field(False, description="Whether provider is currently reachable")


# ═══════════════════════════════════════════════════════════
# Batch Analysis Models
# ═══════════════════════════════════════════════════════════

class BatchAnalysisRequest(BaseModel):
    """Request to analyze multiple RTF files in a batch.

    NOTE: When used with the POST /batch endpoint (which accepts file uploads),
    parameters are sent as Form fields, not as a JSON body.
    """

    session_id: str = Field(..., description="Session with uploaded dictionaries")
    file_indices: List[int] = Field(
        default_factory=list,
        description="Indices of RTF files in the batch (1-based, empty = all)",
    )
    llm_provider: str = Field("ollama", description="LLM provider")
    llm_model: Optional[str] = Field(None, description="Optional model override")
    include_summary: bool = Field(False, description="Whether to include LLM summary")
    include_restructured: bool = Field(
        False,
        description="Whether to include restructured dialogue",
    )
    dictionary_ids: List[str] = Field(
        default_factory=list,
        description="Dictionary names to include in search (empty = all)",
    )


class BatchItemStatus(BaseModel):
    """Status of a single file within a batch."""

    filename: str = Field(..., description="Original RTF filename")
    status: str = Field(
        "pending",
        description="pending | processing | completed | failed",
    )
    analysis_id: Optional[str] = Field(None, description="Analysis ID if completed")
    total_matches: int = Field(0, description="Total matches found")
    matches_by_level: Dict[str, int] = Field(
        default_factory=dict,
        description="Match counts by hierarchy level",
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class BatchAnalysisResponse(BaseModel):
    """Response after submitting a batch analysis."""

    batch_id: str = Field(..., description="Unique batch identifier")
    session_id: str = Field(..., description="Session identifier")
    total_files: int = Field(0, description="Total files in batch")
    status: str = Field(
        "pending",
        description="pending | processing | completed | partial | failed",
    )
    items: List[BatchItemStatus] = Field(
        default_factory=list,
        description="Per-file status items",
    )
    completed_count: int = Field(0, description="Number of completed files")
    failed_count: int = Field(0, description="Number of failed files")
    error: Optional[str] = Field(None, description="Error message if batch failed")


# ═══════════════════════════════════════════════════════════
# Feedback Models (AG-UIREWORK-4)
# ═══════════════════════════════════════════════════════════

class FeedbackRequest(BaseModel):
    """User feedback about a dictionary phrase match.

    Submitted via the PhraseFeedbackPopover UI component.
    """

    phrase_text: str = Field(..., description="Dictionary phrase that was matched")
    session_id: str = Field(..., description="Analysis session identifier")
    match_text: str = Field("", description="Actual matched text from the dialog")
    feedback_text: str = Field(..., description="User feedback comment")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="ISO-8601 timestamp of feedback submission",
    )


class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""

    status: str = Field("ok", description="Submission status: ok or error")
    feedback_id: str = Field("", description="Unique feedback entry identifier")
    message: str = Field("", description="Human-readable status message")


# ═══════════════════════════════════════════════════════════
# Embedding Models (FRIDA)
# ═══════════════════════════════════════════════════════════

class EmbeddingRequest(BaseModel):
    """Request to embed text(s)."""

    texts: List[str] = Field(..., description="Texts to embed")
    model: str = Field("frida", description="Embedding model name")


class EmbeddingResponse(BaseModel):
    """Response from embedding service."""

    embeddings: List[List[float]] = Field(..., description="1536-dim vectors")
    model: str = Field("frida", description="Model used")
    dimensions: int = Field(1536, description="Vector dimensions")
    count: int = Field(..., description="Number of vectors returned")


# ═══════════════════════════════════════════════════════════
# Vector Store Models (FRIDA VectorStore)
# ═══════════════════════════════════════════════════════════

class VectorSearchResult(BaseModel):
    """Результат поиска по векторам."""

    chunk_id: str = Field(..., description="Unique chunk identifier")
    text: str = Field(..., description="Chunk text content")
    dialogue_id: str = Field(..., description="Dialogue/session identifier")
    turn_index: int = Field(..., description="Turn index in the dialogue (0-based)")
    speaker: str = Field(..., description="Speaker role: 'Клиент' or 'Сотрудник'")
    score: float = Field(..., description="Cosine similarity score [0, 1]")
    chunk_type: str = Field(..., description="Chunking strategy: utterance, overlap, full_dialogue")
    entities: List[Dict[str, str]] = Field(
        default_factory=list,
        description="NER entities from ChunkMetadata",
    )


# ═══════════════════════════════════════════════════════════
# Chunking Models (FRIDA Chunker)
# ═══════════════════════════════════════════════════════════

class ChunkMetadata(BaseModel):
    """Metadata for a text chunk produced by Chunker.

    Tracks provenance (dialogue_id, turn_index, speaker),
    chunking strategy (chunk_type), size metrics (token_count, char_count),
    overlap tracking (overlap_with), and NER entities.
    """

    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique chunk identifier (UUID4)")
    dialogue_id: str = Field(..., description="Dialogue/session identifier this chunk belongs to")
    turn_index: int = Field(..., description="Turn index in the dialogue (0-based)")
    speaker: str = Field(..., description="Speaker role: 'Клиент' or 'Сотрудник'")
    chunk_type: Literal["utterance", "overlap", "full_dialogue"] = Field(
        ..., description="Chunking strategy: utterance (short turn), overlap (split long turn), full_dialogue"
    )
    token_count: int = Field(..., description="Number of tokens in chunk text (razdel)")
    char_count: int = Field(..., description="Number of characters in chunk text")
    overlap_with: List[str] = Field(
        default_factory=list, description="IDs of chunks that overlap with this one"
    )
    entities: List[Dict[str, str]] = Field(
        default_factory=list,
        description="NER entities from Natasha: [{'text': '...', 'type': 'PER|LOC|ORG', 'normal': '...'}]",
    )


class Chunk(BaseModel):
    """Text chunk for vectorization by FRIDA embeddings.

    Combines the text content with structured metadata including
    NER entities, overlap tracking, and dialogue provenance.
    """

    text: str = Field(..., description="Chunk text content")
    metadata: ChunkMetadata = Field(..., description="Chunk metadata with entities and provenance")


# ═══════════════════════════════════════════════════════════
# Hybrid Search Models (RRF + NER boost)
# ═══════════════════════════════════════════════════════════

class HybridSearchResult(BaseModel):
    """Результат гибридного поиска.

    Объединяет морфологический, семантический и NER-результаты
    через Reciprocal Rank Fusion (RRF, k=60).
    """

    # Общие поля
    text: str = Field(..., description="Текст чанка/реплики")
    dialogue_id: str = Field(..., description="ID диалога")
    turn_index: int = Field(..., description="Индекс реплики")
    speaker: str = Field(..., description="Спикер")

    # Морфологический поиск
    morph_score: float = Field(0.0, description="1.0 если match, 0.0 если нет")
    morph_match: Optional[DictMatch] = Field(None, description="Детали морфологического совпадения")

    # Семантический поиск
    semantic_score: float = Field(0.0, description="Cosine similarity [0, 1]")

    # NER-ранжирование
    ner_boost: float = Field(0.0, description="Буст за совпадение сущностей")
    matched_entities: List[str] = Field(default_factory=list, description="Совпавшие сущности")

    # Итоговый скор (RRF)
    combined_score: float = Field(0.0, description="RRF score + ner_boost")

    # Источник
    source: str = Field(
        "hybrid",
        description="Источник результата: morph | semantic | hybrid | ner_boost",
    )


# ═══════════════════════════════════════════════════════════
# ID-12: Dialogue Validation
# ═══════════════════════════════════════════════════════════


class DialogueValidationResult(BaseModel):
    """Result of dialogue quality validation (ID-12).

    Determines whether the uploaded text constitutes a meaningful
    client-operator dialogue (vs. noise / artifacts / non-dialogue).
    """

    is_valid_dialogue: bool = Field(
        False,
        description="Whether the text is a meaningful client-operator dialogue",
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score [0.0, 1.0]",
    )
    reason: str = Field(
        "",
        description="Why the dialogue is valid or not (human-readable explanation)",
    )
    language_detected: str = Field(
        "ru",
        description="Detected language code (e.g. 'ru', 'en')",
    )
    provider: str = Field(
        "none",
        description="LLM provider used for this validation",
    )
    model: str = Field(
        "",
        description="LLM model identifier",
    )


# ═══════════════════════════════════════════════════════════
# ID-3: Auto-Resolution + Sentiment Trajectory
# ═══════════════════════════════════════════════════════════


class ResolutionClassification(str, enum.Enum):
    """Classification of dialogue resolution outcome (ID-3).

    Values are lowercase English — stable identifiers that the UI
    will reference. Do NOT rename enum members (backward-compat contract).
    """

    resolved = "resolved"
    unresolved = "unresolved"
    escalated = "escalated"
    redirected = "redirected"


class SentimentTrajectoryPoint(BaseModel):
    """Sentiment assessment at a single turn with cumulative tracking (ID-3)."""

    turn_index: int = Field(..., description="Sequential turn number (0-based)")
    speaker: str = Field(..., description="Speaker role: 'Клиент' or 'Сотрудник'")
    sentiment: str = Field(
        "neutral",
        description="Sentiment at this turn: positive / neutral / negative",
    )
    cumulative_sentiment: float = Field(
        0.0,
        ge=-1.0,
        le=1.0,
        description="Running average sentiment from -1.0 (negative) to 1.0 (positive)",
    )


class ResolutionSentimentResult(BaseModel):
    """Result of auto-resolution classification + sentiment trajectory (ID-3)."""

    session_id: str = Field("", description="Session identifier")
    resolution: ResolutionClassification = Field(
        ResolutionClassification.unresolved,
        description="Dialogue resolution classification",
    )
    resolution_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for resolution classification [0.0, 1.0]",
    )
    resolution_reason: str = Field(
        "",
        description="Human-readable explanation of the resolution classification",
    )
    sentiment_trajectory: List[SentimentTrajectoryPoint] = Field(
        default_factory=list,
        description="Per-utterance sentiment trajectory with cumulative tracking",
    )
    sentiment_start: str = Field(
        "neutral",
        description="Overall sentiment at the beginning of the dialogue",
    )
    sentiment_end: str = Field(
        "neutral",
        description="Overall sentiment at the end of the dialogue",
    )
    trajectory_direction: str = Field(
        "stable",
        description="Sentiment trajectory direction: improving / declining / stable / volatile",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# ═══════════════════════════════════════════════════════════
# IP-5.2: Error Classifier
# ═══════════════════════════════════════════════════════════


class ErrorCategory(str, enum.Enum):
    """Classification categories for dialogue errors (IP-5.2).

    Values are lowercase English — stable identifiers that the UI
    will reference. Do NOT rename enum members (backward-compat contract).
    """

    communication_error = "communication_error"
    procedural_error = "procedural_error"
    information_error = "information_error"
    service_error = "service_error"
    compliance_violation = "compliance_violation"
    empathy_failure = "empathy_failure"
    response_delay = "response_delay"


class ClassifiedError(BaseModel):
    """A single classified error found in a dialogue (IP-5.2)."""

    turn_index: int = Field(..., description="Sequential turn number (0-based)")
    speaker: str = Field(..., description="Speaker role: 'Клиент' or 'Сотрудник'")
    category: ErrorCategory = Field(
        ..., description="Error category classification",
    )
    severity: str = Field(
        "low",
        description="Severity level: low / medium / high",
    )
    description: str = Field(..., description="Description of the error")
    suggested_fix: str = Field("", description="Suggested fix for the error")


class ErrorClassificationResult(BaseModel):
    """Result of dialogue error classification (IP-5.2)."""

    session_id: str = Field("", description="Session identifier")
    has_errors: bool = Field(
        False,
        description="Whether any errors were detected in the dialogue",
    )
    errors: List[ClassifiedError] = Field(
        default_factory=list,
        description="All classified errors found in the dialogue",
    )
    total_errors: int = Field(
        0,
        description="Total number of errors detected",
    )
    errors_by_category: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of errors by category (e.g. {'communication_error': 2})",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")


# ═══════════════════════════════════════════════════════════
# IP-6.1: Domain-Specific Analysis
# ═══════════════════════════════════════════════════════════


class DomainType(str, enum.Enum):
    """Domain type for domain-specific analysis prompts (IP-6.1).

    Values are lowercase English — stable identifiers that the UI
    domain selector will reference. Do NOT rename enum members
    (backward-compat contract).
    """

    general = "general"
    insurance = "insurance"
    banking = "banking"
    healthcare = "healthcare"
    telecom = "telecom"


# ═══════════════════════════════════════════════════════════
# RAG Pipeline Models (Q&A over analyzed dialogues)
# ═══════════════════════════════════════════════════════════

class RagSourceFragment(BaseModel):
    """A source fragment referenced in the RAG answer.

    Citation format: dialogue_id + turn_index + text_snippet.
    This model is the stable contract for future RAG chat UI.
    """

    dialogue_id: str = Field("", description="Dialogue/session identifier")
    turn_index: int = Field(-1, description="Turn index in the dialogue (0-based)")
    speaker: str = Field("", description="Speaker role: 'Клиент' or 'Сотрудник'")
    text_snippet: str = Field("", description="Relevant text excerpt from the dialogue turn")
    relevance_score: float = Field(0.0, description="Search relevance score")
    search_source: str = Field(
        "hybrid",
        description="Search method used: 'morph' | 'semantic' | 'hybrid'",
    )


class RagQueryRequest(BaseModel):
    """Request for RAG Q&A over analyzed dialogues."""

    question: str = Field(
        ..., min_length=1, max_length=2000,
        description="Question about the analyzed dialogues",
    )
    session_id: Optional[str] = Field(
        None,
        description="Restrict search to one session (None = search all indexed dialogues)",
    )
    top_k: int = Field(
        5, ge=1, le=20,
        description="Number of fragments to retrieve and use as context",
    )
    provider_id: str = Field(
        "beeline",
        description="LLM provider for answer generation",
    )


class RagQueryResponse(BaseModel):
    """Response from RAG Q&A.

    Stable model — future RAG chat UI will reference this structure.
    """

    question: str = Field(..., description="Original question")
    answer: str = Field("", description="Generated answer based on retrieved context")
    sources: List[RagSourceFragment] = Field(
        default_factory=list,
        description="Source fragments referenced in the answer",
    )
    context_used: int = Field(
        0,
        description="Number of fragments actually used as context",
    )
    search_source: str = Field(
        "hybrid",
        description="Search method actually used: 'morph' | 'semantic' | 'hybrid'",
    )
    provider: str = Field(
        "none",
        description="LLM provider used for answer generation",
    )
    model: str = Field("", description="LLM model identifier")
    error: Optional[str] = Field(
        None,
        description="Error message if RAG partially or fully failed",
    )


# ═══════════════════════════════════════════════════════════
# Batch RTF Upload Models (IP-2.1)
# ═══════════════════════════════════════════════════════════

class BatchUploadRtfResponse(BaseModel):
    """Response from batch RTF upload.

    Each file is processed independently. If one file fails,
    others still succeed (partial success pattern).
    """

    results: List[UploadRtfResponse] = Field(
        default_factory=list,
        description="Per-file upload results (order matches input)",
    )
    total: int = Field(0, description="Total number of files submitted")
    successful: int = Field(0, description="Number of successfully uploaded files")
    failed: int = Field(0, description="Number of failed uploads")
    errors: List[dict] = Field(
        default_factory=list,
        description="Per-file errors: [{filename: str, error: str}]",
    )


# ═══════════════════════════════════════════════════════════
# Health Check Models (ID-15)
# ═══════════════════════════════════════════════════════════

class HealthCheckResult(BaseModel):
    """Result of the /api/health endpoint.

    Provides system status, version, uptime, and service availability checks.
    """

    status: str = Field(
        ...,
        description="Overall health: 'healthy' | 'degraded' | 'unhealthy'",
    )
    version: str = Field(..., description="Application version")
    uptime_seconds: float = Field(
        0.0,
        description="Seconds since application startup",
    )
    checks: Dict[str, str] = Field(
        default_factory=dict,
        description="Service name → 'ok' | 'error: ...'",
    )
    active_sessions: int = Field(
        0,
        description="Number of active (non-expired) sessions",
    )
    frida_available: bool = Field(
        False,
        description="Whether FRIDA embedding service is reachable",
    )
    vector_store_size: int = Field(
        0,
        description="Number of vectors in the FAISS index",
    )
    pii_masking: Optional[Dict[str, Any]] = Field(
        None,
        description="PII masking subsystem status: enabled, available, circuit_breaker_state",
    )


# ═══════════════════════════════════════════════════════════
# PII Masking Models (152-FZ Compliance)
# ═══════════════════════════════════════════════════════════


class PIIEntityType(str, enum.Enum):
    """PII entity types for compliance 152-FZ.

    Lowercase English values, consistent with ClientSentiment/Resolution pattern.
    Do NOT rename enum members (backward-compat contract).
    """

    person = "person"
    phone_number = "phone_number"
    email_address = "email_address"
    passport = "passport"
    snils = "snils"
    inn = "inn"
    credit_card = "credit_card"
    address = "address"
    contract_number = "contract_number"
    billing_account = "billing_account"


class PIIDetection(BaseModel):
    """Single PII entity detected in text (internal — contains raw PII text).

    WARNING: This model includes the `text` field with raw PII content.
    It MUST NOT be returned through API responses (152-FZ compliance).
    Use PIIDetectionPublic for API responses instead.
    """

    entity_type: PIIEntityType = Field(
        ..., description="Type of detected PII entity",
    )
    start: int = Field(
        ..., ge=0, description="Character offset in original text",
    )
    end: int = Field(
        ..., gt=0, description="Character offset (exclusive) in original text",
    )
    text: str = Field(
        ..., description="Original PII text (internal use ONLY — never expose via API)",
    )
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0",
    )
    recognizer: str = Field(
        ..., description="Which recognizer found this entity",
    )


class PIIDetectionPublic(BaseModel):
    """Sanitized PII detection for API responses (152-FZ compliance).

    Unlike PIIDetection, this model does NOT contain the raw PII text.
    It is safe to return through API endpoints.
    """

    entity_type: PIIEntityType = Field(
        ..., description="Type of detected PII entity",
    )
    start: int = Field(
        ..., ge=0, description="Character offset in original text",
    )
    end: int = Field(
        ..., gt=0, description="Character offset (exclusive) in original text",
    )
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0",
    )
    recognizer: str = Field(
        ..., description="Which recognizer found this entity",
    )


class PIIMaskingResult(BaseModel):
    """Result of PII masking operation.

    NOTE: original_text was intentionally removed (152-FZ compliance).
    The masked_text is sufficient for downstream processing.
    Raw PII must not be retained in memory beyond the masking operation.
    """

    masked_text: str = Field(..., description="Text with PII replaced by placeholders")
    detections: List[PIIDetection] = Field(
        default_factory=list, description="All PII entities detected (internal — use PIIDetectionPublic for API)",
    )
    entity_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of entities by type: {'person': 2, 'phone_number': 1}",
    )
    processing_time_ms: float = Field(
        0.0, ge=0.0, description="Processing time in milliseconds",
    )
    masked: bool = Field(
        False, description="Whether any PII was found and masked",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if masking failed (Presidio unavailable, Variant A)",
    )


class PIIMaskingConfig(BaseModel):
    """Configuration for PII masking operation.

    NOTE: mask_operator and placeholder_template were removed — they were dead
    config fields never used by mask_text(). The service always uses
    _PRESIDIO_ENTITY_PLACEHOLDER_MAP with "replace" operator.
    If alternative operators are needed in the future, they can be re-added
    with actual implementation in mask_text().
    """

    entity_types: List[PIIEntityType] = Field(
        default_factory=list,
        description="Entity types to detect (empty = all types)",
    )
    min_score: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Minimum confidence score threshold",
    )


class PIIMaskRequest(BaseModel):
    """Request body for PII masking endpoint."""

    text: str = Field(
        ..., min_length=1, max_length=50000,
        description="Text to mask PII in",
    )
    entity_types: Optional[List[PIIEntityType]] = Field(
        None,
        description="Entity types to detect (default: all)",
    )
    min_score: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Minimum confidence score",
    )


class PIIMaskResponse(BaseModel):
    """Response for PII masking endpoint.

    Uses PIIDetectionPublic (no raw PII text) instead of PIIDetection
    for 152-FZ compliance.
    """

    masked_text: str
    detections: List[PIIDetectionPublic]
    entity_counts: Dict[str, int]
    processing_time_ms: float


class PIIStatusResponse(BaseModel):
    """PII masking subsystem status."""

    available: bool
    circuit_breaker_state: str  # "closed" | "open" | "half_open"
    total_masked: int
    entity_counts: Dict[str, int]
    avg_latency_ms: float
    language: str
    recognizers: List[str]


class MaskedDialogueResult(BaseModel):
    """Result of masking PII in an entire dialogue.

    Used by PIIMaskingService.mask_dialogue() for upload pipeline integration.
    Variant A (strict blocking): if error is set, the dialogue must NOT be
    passed downstream — unmasked PII is never stored (INV-PII-2).
    """

    masked_dialogue: Optional[Any] = Field(
        None,
        description="ParsedDialog with PII masked in all turn texts (None if error)",
    )
    entity_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Aggregate entity counts across all turns: {'person': 2, 'phone_number': 1}",
    )
    total_detections: int = Field(
        0,
        description="Total number of PII entities detected across all turns",
    )
    processing_time_ms: float = Field(
        0.0,
        ge=0.0,
        description="Total processing time in milliseconds (all turns)",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if masking failed (Presidio unavailable, Variant A)",
    )


# Resolve forward references (LogicNode self-referencing children)
LogicNode.model_rebuild()

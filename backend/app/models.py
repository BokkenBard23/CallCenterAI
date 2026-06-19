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
    """Meta section from <SavedState> in the XML."""

    total_found: int = 0
    last_update_time: str = ""
    execution_time: str = ""
    is_actual: bool = True
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


# Resolve forward references (LogicNode self-referencing children)
LogicNode.model_rebuild()

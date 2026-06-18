"""Pydantic models for request/response schemas.

Models are organised to match the spec-chunk-2 response formats:
  - RTF upload: DialogueTurn, ParsedDialog, UploadRtfResponse
  - Dictionary upload: DictCondition, XmlDictionary, UploadDictionaryResponse
  - Analysis: TextSegment, DictMatch, AnalysisResult, AnalysisResponse
  - LLM: LLMResult
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

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

    success: bool = Field(..., description="Whether parsing succeeded")
    dialog: Optional[ParsedDialog] = Field(None, description="Parsed dialogue data")
    error: Optional[str] = Field(None, description="Error message if parsing failed")
    session_id: str = Field(..., description="Session identifier for subsequent requests")


# ═══════════════════════════════════════════════════════════
# Dictionary Upload Models
# ═══════════════════════════════════════════════════════════

class DictCondition(BaseModel):
    """A single phrase condition from the search dictionary."""

    text: str = Field(..., description="Phrase text to search for")
    word_distance: int = Field(0, description="Allowed word distance for sliding window")
    word_count: int = Field(0, description="Word count in phrase")
    channel_constraint: str = Field("ANY", description="Channel: CLIENT, OPERATOR, or ANY")
    quarter: str = Field("Q1", description="Dictionary quarter: Q1, Q2, Q3")


class XmlDictionary(BaseModel):
    """Parsed XML dictionary with quarterly phrase groups."""

    source_file: str = Field(..., description="Original XML filename")
    quarters: Dict[str, List[DictCondition]] = Field(
        default_factory=dict,
        description="Phrases grouped by quarter key (Q1, Q2, Q3)",
    )
    total_phrases: int = Field(0, description="Total number of phrases across all quarters")
    parsed_at: datetime = Field(default_factory=datetime.now, description="Parse timestamp")


class UploadDictionaryResponse(BaseModel):
    """Response after uploading and parsing an XML dictionary."""

    success: bool = Field(..., description="Whether parsing succeeded")
    dictionary: Optional[XmlDictionary] = Field(None, description="Parsed dictionary data")
    error: Optional[str] = Field(None, description="Error message if parsing failed")
    session_id: str = Field(..., description="Session identifier for subsequent requests")


# ═══════════════════════════════════════════════════════════
# Analysis Models
# ═══════════════════════════════════════════════════════════

class TextSegment(BaseModel):
    """A text segment within a dialogue turn for matching."""

    turn_index: int = Field(..., description="Turn index in the dialogue")
    text: str = Field(..., description="Text content of the segment")
    speaker: str = Field(..., description="Speaker role")


class DictMatch(BaseModel):
    """A match result for a dictionary phrase against the dialogue."""

    phrase_text: str = Field(..., description="Matched phrase text")
    quarter: str = Field(..., description="Quarter (Q1/Q2/Q3)")
    turn_index: int = Field(..., description="Turn where the match was found")
    speaker: str = Field(..., description="Speaker of the matched turn")
    match_type: str = Field("sliding_window", description="Match algorithm used")
    word_distance_used: int = Field(0, description="Actual word distance applied")


class AnalysisResult(BaseModel):
    """Result of dictionary-based analysis for a single session."""

    session_id: str = Field(..., description="Session identifier")
    total_matches: int = Field(0, description="Total phrase matches found")
    matches: List[DictMatch] = Field(default_factory=list, description="All matches")
    matches_by_quarter: Dict[str, int] = Field(
        default_factory=dict,
        description="Match counts per quarter",
    )
    matches_by_speaker: Dict[str, int] = Field(
        default_factory=dict,
        description="Match counts per speaker role",
    )
    analyzed_at: datetime = Field(default_factory=datetime.now, description="Analysis timestamp")


class AnalysisResponse(BaseModel):
    """Full analysis response combining dictionary matches and optional LLM insights."""

    success: bool = Field(..., description="Whether analysis succeeded")
    dictionary_analysis: Optional[AnalysisResult] = Field(
        None, description="Dictionary-based matching results"
    )
    llm_result: Optional[LLMResult] = Field(None, description="LLM analysis results (if requested)")
    error: Optional[str] = Field(None, description="Error message if analysis failed")
    session_id: str = Field(..., description="Session identifier")


# ═══════════════════════════════════════════════════════════
# LLM Models
# ═══════════════════════════════════════════════════════════

class LLMResult(BaseModel):
    """Structured result from LLM analysis of a dialogue."""

    topic: str = Field(..., description="Identified topic of the dialogue")
    result: str = Field(..., description="Overall outcome / resolution status")
    key_points: List[str] = Field(
        default_factory=list,
        description="Key points discussed in the dialogue",
    )
    client_sentiment: str = Field(
        ...,
        description="Assessed client sentiment (positive/neutral/negative/mixed)",
    )
    resolution: str = Field(
        ...,
        description="How the dialogue was resolved (resolved/unresolved/escalated/partial)",
    )
    restructured_dialogue: Optional[str] = Field(
        None,
        description="LLM-restructured summary of the dialogue",
    )
    provider: str = Field("none", description="LLM provider used for this analysis")
    model: str = Field("", description="LLM model identifier")
    raw_response: Optional[Any] = Field(
        None,
        description="Raw LLM response for debugging (optional)",
    )

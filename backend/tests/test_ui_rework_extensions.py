"""Tests for backend model extensions and feedback API (AG-UIREWORK-1/4/5).

Covers:
  - DictMatch extended fields: word_distance, channel_constraint, dict_level
  - DictionaryCondition extended fields: phrase_groups, nested_phrases, is_exception, exception_phrases
  - Feedback API: POST /api/feedback and GET /api/feedback
  - search.py: DictMatch creation with extended fields
  - xml_parser.py: DictionaryCondition with phrase_groups and is_exception
  - Backward compatibility: existing API responses still work with defaults
"""
import json
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure smartlogger is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))
# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models import (
    DictionaryCondition,
    DictionaryNode,
    DictMatch,
    FeedbackRequest,
    FeedbackResponse,
    PhraseGroup,
    ParsedDialog,
    DialogueTurn,
    SearchResult,
    TextSegment,
    TokenModel,
    TokenSection,
)


# ═══════════════════════════════════════════════════════════════════════
# DictMatch extended fields (AG-UIREWORK-1)
# ═══════════════════════════════════════════════════════════════════════

class TestDictMatchExtendedFields:
    """Tests for DictMatch new fields: word_distance, channel_constraint, dict_level."""

    def test_default_values(self):
        """New fields must have safe defaults for backward compatibility."""
        match = DictMatch(
            phrase_text="test phrase",
            quarter="Q1",
            turn_index=0,
            speaker="Client",
        )
        assert match.word_distance == 0
        assert match.channel_constraint == "ANY"
        assert match.dict_level == 1

    def test_explicit_values(self):
        """New fields must accept explicit values."""
        match = DictMatch(
            phrase_text="test",
            quarter="Q1",
            turn_index=0,
            speaker="Client",
            word_distance=3,
            channel_constraint="CLIENT",
            dict_level=2,
        )
        assert match.word_distance == 3
        assert match.channel_constraint == "CLIENT"
        assert match.dict_level == 2

    def test_channel_constraint_values(self):
        """channel_constraint must accept CLIENT, OPERATOR, ANY."""
        for channel in ("CLIENT", "OPERATOR", "ANY"):
            match = DictMatch(
                phrase_text="test",
                quarter="Q1",
                turn_index=0,
                speaker="Client",
                channel_constraint=channel,
            )
            assert match.channel_constraint == channel

    def test_backward_compatible_serialization(self):
        """Serialized DictMatch must include new fields with defaults."""
        match = DictMatch(
            phrase_text="test",
            quarter="Q1",
            turn_index=0,
            speaker="Client",
        )
        data = match.model_dump()
        assert "word_distance" in data
        assert "channel_constraint" in data
        assert "dict_level" in data
        assert data["word_distance"] == 0
        assert data["channel_constraint"] == "ANY"
        assert data["dict_level"] == 1

    def test_dict_level_equals_word_distance_used(self):
        """dict_level should mirror word_distance_used (hierarchy level)."""
        match = DictMatch(
            phrase_text="test",
            quarter="Q2",
            turn_index=1,
            speaker="Client",
            word_distance_used=2,
            dict_level=2,
        )
        assert match.dict_level == match.word_distance_used


# ═══════════════════════════════════════════════════════════════════════
# DictionaryCondition extended fields (AG-UIREWORK-5)
# ═══════════════════════════════════════════════════════════════════════

class TestDictionaryConditionExtendedFields:
    """Tests for DictionaryCondition new fields: phrase_groups, nested_phrases,
    is_exception, exception_phrases."""

    def test_default_values(self):
        """New fields must have safe defaults for backward compatibility."""
        cond = DictionaryCondition(text="test phrase")
        assert cond.phrase_groups == []
        assert cond.nested_phrases == []
        assert cond.is_exception is False
        assert cond.exception_phrases == []

    def test_phrase_groups_or_alternatives(self):
        """phrase_groups must store OR-group word lists."""
        cond = DictionaryCondition(
            text="test1",
            phrase_groups=[["word1", "word2"], ["word3", "word4", "word5"]],
        )
        assert len(cond.phrase_groups) == 2
        assert cond.phrase_groups[0] == ["word1", "word2"]
        assert cond.phrase_groups[1] == ["word3", "word4", "word5"]

    def test_nested_phrases(self):
        """nested_phrases must store phrases from child dictionaries."""
        cond = DictionaryCondition(
            text="parent",
            nested_phrases=["child phrase 1", "child phrase 2"],
        )
        assert cond.nested_phrases == ["child phrase 1", "child phrase 2"]

    def test_is_exception_true(self):
        """is_exception=True for negation-marked phrases."""
        cond = DictionaryCondition(
            text="NE ustraivaet",
            is_exception=True,
            exception_phrases=["ustraivaet"],
        )
        assert cond.is_exception is True
        assert cond.exception_phrases == ["ustraivaet"]

    def test_is_exception_default_false(self):
        """is_exception defaults to False for normal phrases."""
        cond = DictionaryCondition(text="normal")
        assert cond.is_exception is False
        assert cond.exception_phrases == []

    def test_serialization_includes_new_fields(self):
        """Serialized condition must include new fields with defaults."""
        cond = DictionaryCondition(text="test")
        data = cond.model_dump()
        assert "phrase_groups" in data
        assert "nested_phrases" in data
        assert "is_exception" in data
        assert "exception_phrases" in data

    def test_backward_compatible_existing_fields_preserved(self):
        """Existing fields must remain unchanged when new fields are added."""
        cond = DictionaryCondition(
            text="test",
            word_distance=3,
            word_count=1,
            channel_constraint="CLIENT",
            without_list=["cancel"],
            is_exact=True,
            phrase_groups=[["test"]],
            nested_phrases=["child"],
            is_exception=False,
            exception_phrases=[],
        )
        # Existing fields
        assert cond.text == "test"
        assert cond.word_distance == 3
        assert cond.word_count == 1
        assert cond.channel_constraint == "CLIENT"
        assert cond.without_list == ["cancel"]
        assert cond.is_exact is True
        # New fields
        assert cond.phrase_groups == [["test"]]
        assert cond.nested_phrases == ["child"]
        assert cond.is_exception is False
        assert cond.exception_phrases == []


# ═══════════════════════════════════════════════════════════════════════
# search.py: DictMatch creation with extended fields (AG-UIREWORK-1)
# ═══════════════════════════════════════════════════════════════════════

class TestSearchDictMatchExtendedFields:
    """Tests that run_hierarchical_search populates DictMatch extended fields."""

    @pytest.mark.asyncio
    async def test_word_distance_populated_from_condition(self):
        """DictMatch.word_distance must come from DictionaryCondition.word_distance."""
        from app.services.search import run_hierarchical_search

        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[DialogueTurn(turn_index=0, text="hello world test", speaker="Client")],
        )

        condition = DictionaryCondition(
            text="hello",
            word_distance=5,
            word_count=1,
            channel_constraint="ANY",
        )
        root = DictionaryNode(
            id="d1", name="Q1",
            conditions=[condition],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        assert result.total_matches >= 1
        match = result.matches[0]
        assert match.word_distance == 5, f"Expected word_distance=5, got {match.word_distance}"

    @pytest.mark.asyncio
    async def test_channel_constraint_populated_from_condition(self):
        """DictMatch.channel_constraint must come from DictionaryCondition.channel_constraint."""
        from app.services.search import run_hierarchical_search

        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[DialogueTurn(turn_index=0, text="hello world", speaker="\u041a\u043b\u0438\u0435\u043d\u0442")],
        )

        condition = DictionaryCondition(
            text="hello",
            word_distance=2,
            word_count=1,
            channel_constraint="CLIENT",
        )
        root = DictionaryNode(
            id="d1", name="Q1",
            conditions=[condition],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        assert result.total_matches >= 1
        match = result.matches[0]
        assert match.channel_constraint == "CLIENT", f"Expected CLIENT, got {match.channel_constraint}"

    @pytest.mark.asyncio
    async def test_dict_level_equals_hierarchy_level(self):
        """DictMatch.dict_level must match the hierarchy level (word_distance_used)."""
        from app.services.search import run_hierarchical_search

        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[
                DialogueTurn(turn_index=0, text="hello", speaker="Client"),
                DialogueTurn(turn_index=1, text="world", speaker="Client"),
            ],
        )

        q2 = DictionaryNode(
            id="q2", name="Q2",
            conditions=[DictionaryCondition(
                text="world", word_distance=1, word_count=1, channel_constraint="ANY"
            )],
            children=[],
        )
        q1 = DictionaryNode(
            id="q1", name="Q1",
            conditions=[DictionaryCondition(
                text="hello", word_distance=1, word_count=1, channel_constraint="ANY"
            )],
            children=[q2],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[q1],
            cascade=False,
        )

        for match in result.matches:
            assert match.dict_level == match.word_distance_used, (
                f"dict_level ({match.dict_level}) should equal word_distance_used ({match.word_distance_used})"
            )

    @pytest.mark.asyncio
    async def test_default_channel_constraint_any(self):
        """DictMatch.channel_constraint defaults to ANY when condition has ANY."""
        from app.services.search import run_hierarchical_search

        dialog = ParsedDialog(
            filename="test.rtf",
            turns=[DialogueTurn(turn_index=0, text="hello test", speaker="Client")],
        )

        condition = DictionaryCondition(
            text="hello",
            word_distance=2,
            word_count=1,
            channel_constraint="ANY",
        )
        root = DictionaryNode(
            id="d1", name="Q1",
            conditions=[condition],
            children=[],
        )

        result = await run_hierarchical_search(
            dialog=dialog,
            dictionaries=[root],
            cascade=False,
        )

        assert result.total_matches >= 1
        match = result.matches[0]
        assert match.channel_constraint == "ANY"


# ═══════════════════════════════════════════════════════════════════════
# xml_parser.py: DictionaryCondition with phrase_groups and is_exception
# ═══════════════════════════════════════════════════════════════════════

class TestXmlParserExtendedConditions:
    """Tests for xml_parser populating DictionaryCondition extended fields."""

    @pytest.mark.asyncio
    async def test_phrase_groups_populated_from_or_tokens(self):
        """Conditions with OR must produce phrase_groups with alternatives."""
        from app.services.xml_parser import parse_xml_bytes

        xml = (
            '<?xml version="1.0"?>'
            '<SpeechLabRequest type="SpeechLabRequest">'
            '<Id>test-or</Id>'
            '<Name>OR Test</Name>'
            '<Tokens>'
            '<Token><Text>word1</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '<Token><Text>OR</Text><Type>LEXEME</Type><IsError>false</IsError></Token>'
            '<Token><Text>word2</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '</Tokens>'
            '</SpeechLabRequest>'
        ).encode("utf-8")

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 2

        # Both conditions should have phrase_groups reflecting all OR alternatives
        for cond in node.conditions:
            assert len(cond.phrase_groups) == 2, f"Expected 2 OR groups, got {len(cond.phrase_groups)}"
            group_words = [w for g in cond.phrase_groups for w in g]
            assert "word1" in group_words
            assert "word2" in group_words

    @pytest.mark.asyncio
    async def test_is_exception_detected_for_ne_prefix(self):
        """Phrases preceded by NOT (LEXEME) must set is_exception=True.

        Per UI-2.5 new semantics: NE/НЕ/NOT is a LEXEME negation operator,
        NOT a WORD. The recognized Latin negation operator is 'NOT' (not 'NE').
        When it precedes a phrase, is_negated=True is set on the next
        PhraseGroup, which xml_parser maps to is_exception=True.
        """
        from app.services.xml_parser import parse_xml_bytes

        xml = (
            '<?xml version="1.0"?>'
            '<SpeechLabRequest type="SpeechLabRequest">'
            '<Id>test-ne</Id>'
            '<Name>NE Test</Name>'
            '<Tokens>'
            '<Token><Text>NOT</Text><Type>LEXEME</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '<Token><Text>ustraivaet</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '</Tokens>'
            '</SpeechLabRequest>'
        ).encode("utf-8")

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        cond = node.conditions[0]
        assert cond.is_exception is True, f"Expected is_exception=True, got {cond.is_exception}"
        assert cond.exception_phrases == ["ustraivaet"]

    @pytest.mark.asyncio
    async def test_nested_phrases_from_child_requests(self):
        """nested_phrases must include phrases from child SpeechLabRequests."""
        from app.services.xml_parser import parse_xml_bytes

        xml = (
            '<?xml version="1.0"?>'
            '<SpeechLabRequest type="SpeechLabRequest">'
            '<Id>parent-id</Id>'
            '<Name>Parent Dict</Name>'
            '<Tokens>'
            '<Token><Text>sampleword</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '</Tokens>'
            '<Requests>'
            '<SpeechLabRequest type="SpeechLabRequest">'
            '<Id>child-id</Id>'
            '<Name>Child Dict</Name>'
            '<Tokens>'
            '<Token><Text>otkazyvayus</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '</Tokens>'
            '</SpeechLabRequest>'
            '</Requests>'
            '</SpeechLabRequest>'
        ).encode("utf-8")

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        # The parent's condition should have nested_phrases from the child
        cond = node.conditions[0]
        assert "otkazyvayus" in cond.nested_phrases, (
            f"Expected 'otkazyvayus' in nested_phrases, got {cond.nested_phrases}"
        )

    @pytest.mark.asyncio
    async def test_default_fields_backward_compatible(self):
        """Simple XML without OR or NE must have default empty extended fields."""
        from app.services.xml_parser import parse_xml_bytes

        xml = (
            '<?xml version="1.0"?>'
            '<SpeechLabRequest type="SpeechLabRequest">'
            '<Id>simple-id</Id>'
            '<Name>Simple Dict</Name>'
            '<Tokens>'
            '<Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '</Tokens>'
            '</SpeechLabRequest>'
        ).encode("utf-8")

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        cond = node.conditions[0]
        assert cond.is_exception is False
        assert cond.exception_phrases == []
        # phrase_groups should have at least one group (the phrase itself)
        assert len(cond.phrase_groups) >= 1

    @pytest.mark.asyncio
    async def test_is_exception_with_russian_ne(self):
        """Russian 'НЕ' (LEXEME) prefix must also set is_exception=True.

        Per UI-2.5 new semantics: НЕ must be a LEXEME token (not WORD) to act
        as a negation operator. As a WORD it would be part of the phrase.
        """
        from app.services.xml_parser import parse_xml_bytes

        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<SpeechLabRequest type="SpeechLabRequest">'
            '<Id>test-rus-ne</Id>'
            '<Name>Rus NE Test</Name>'
            '<Tokens>'
            '<Token><Text>\u043d\u0435</Text><Type>LEXEME</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '<Token><Text>ustraivaet</Text><Type>WORD</Type><IsError>false</IsError>'
            '<Properties Channel="ANY" WordDistance="2" />'
            '</Token>'
            '</Tokens>'
            '</SpeechLabRequest>'
        ).encode("utf-8")

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        cond = node.conditions[0]
        assert cond.is_exception is True, f"Expected is_exception=True for Russian NE, got {cond.is_exception}"


# ═══════════════════════════════════════════════════════════════════════
# Feedback models (AG-UIREWORK-4)
# ═══════════════════════════════════════════════════════════════════════

class TestFeedbackModels:
    """Tests for FeedbackRequest and FeedbackResponse models."""

    def test_feedback_request_required_fields(self):
        """FeedbackRequest must validate required fields."""
        req = FeedbackRequest(
            phrase_text="test phrase",
            session_id="sess-123",
            feedback_text="False positive",
        )
        assert req.phrase_text == "test phrase"
        assert req.session_id == "sess-123"
        assert req.feedback_text == "False positive"
        assert req.match_text == ""
        assert req.timestamp != ""

    def test_feedback_request_optional_fields(self):
        """FeedbackRequest must accept optional match_text."""
        req = FeedbackRequest(
            phrase_text="test",
            session_id="sess-123",
            match_text="matched text here",
            feedback_text="Not an exact match",
        )
        assert req.match_text == "matched text here"

    def test_feedback_request_validation_missing_fields(self):
        """FeedbackRequest must reject missing required fields."""
        with pytest.raises(Exception):
            FeedbackRequest()  # type: ignore[call-arg]

    def test_feedback_response_defaults(self):
        """FeedbackResponse must have sensible defaults."""
        resp = FeedbackResponse()
        assert resp.status == "ok"
        assert resp.feedback_id == ""
        assert resp.message == ""

    def test_feedback_response_explicit(self):
        """FeedbackResponse must accept explicit values."""
        resp = FeedbackResponse(
            status="ok",
            feedback_id="abc123",
            message="Feedback submitted successfully",
        )
        assert resp.status == "ok"
        assert resp.feedback_id == "abc123"


# ═══════════════════════════════════════════════════════════════════════
# Feedback API endpoint (AG-UIREWORK-4)
# ═══════════════════════════════════════════════════════════════════════

class TestFeedbackAPI:
    """Integration tests for POST /api/feedback and GET /api/feedback."""

    @pytest.fixture
    def temp_feedback_dir(self, tmp_path):
        """Create a temporary feedback directory and patch the module constant."""
        feedback_dir = tmp_path / "feedback"
        feedback_dir.mkdir()
        with patch("app.routers.feedback._FEEDBACK_DIR", feedback_dir):
            yield feedback_dir

    @pytest.fixture
    def client(self, temp_feedback_dir):
        """Create a test client with patched feedback directory."""
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_submit_feedback_success(self, client, temp_feedback_dir):
        """POST /api/feedback must persist feedback to JSONL file."""
        payload = {
            "phrase_text": "test phrase",
            "session_id": "sess-test-001",
            "match_text": "matched text",
            "feedback_text": "False positive",
        }

        response = client.post("/api/feedback", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert data["status"] == "ok"
        assert data["feedback_id"] != ""
        assert "success" in data["message"].lower()

        # Verify the JSONL file was created and contains the entry
        feedback_files = list(temp_feedback_dir.glob("feedback-*.jsonl"))
        assert len(feedback_files) == 1
        with open(feedback_files[0], "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())
        assert entry["phrase_text"] == "test phrase"
        assert entry["session_id"] == "sess-test-001"
        assert entry["feedback_text"] == "False positive"
        assert "feedback_id" in entry
        assert "server_timestamp" in entry

    def test_submit_feedback_missing_required_field(self, client):
        """POST /api/feedback must reject missing required fields."""
        payload = {
            "phrase_text": "test",
            # missing session_id and feedback_text
        }

        response = client.post("/api/feedback", json=payload)
        assert response.status_code == 422

    def test_list_feedback_empty(self, client, temp_feedback_dir):
        """GET /api/feedback must return empty list when no feedback exists."""
        response = client.get("/api/feedback")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_feedback_after_submit(self, client, temp_feedback_dir):
        """GET /api/feedback must return submitted feedback entries."""
        # Submit feedback first
        payload = {
            "phrase_text": "test phrase",
            "session_id": "sess-list-001",
            "feedback_text": "Test feedback",
        }
        client.post("/api/feedback", json=payload)

        # List feedback
        response = client.get("/api/feedback")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["phrase_text"] == "test phrase"

    def test_list_feedback_filter_by_session(self, client, temp_feedback_dir):
        """GET /api/feedback?session_id=X must filter by session."""
        # Submit two feedback entries
        client.post("/api/feedback", json={
            "phrase_text": "phrase1",
            "session_id": "sess-A",
            "feedback_text": "fb1",
        })
        client.post("/api/feedback", json={
            "phrase_text": "phrase2",
            "session_id": "sess-B",
            "feedback_text": "fb2",
        })

        # Filter by session A
        response = client.get("/api/feedback?session_id=sess-A")
        assert response.status_code == 200
        data = response.json()
        assert all(entry["session_id"] == "sess-A" for entry in data)


# ═══════════════════════════════════════════════════════════════════════
# Backward compatibility: existing SearchResult/AnalysisResponse unchanged
# ═══════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Ensure existing API responses work with default values for new fields."""

    def test_search_result_with_old_dict_match(self):
        """SearchResult must work with DictMatch using only original fields."""
        match = DictMatch(
            phrase_text="test",
            quarter="Q1",
            turn_index=0,
            speaker="Client",
        )
        result = SearchResult(
            segments=[TextSegment(turn_index=0, text="test", speaker="Client")],
            total_matches=1,
            matches=[match],
            matches_by_level={"1": 1},
        )
        assert result.total_matches == 1
        assert result.matches[0].word_distance == 0
        assert result.matches[0].channel_constraint == "ANY"
        assert result.matches[0].dict_level == 1

    def test_dict_match_json_roundtrip(self):
        """DictMatch must survive JSON serialization/deserialization roundtrip."""
        match = DictMatch(
            phrase_text="test",
            matched_text="matched text",
            matched_start=10,
            matched_end=30,
            quarter="Q1",
            turn_index=0,
            speaker="Client",
            match_type="morph_bow",
            word_distance_used=1,
            cascade_order=1,
            is_exact_match=False,
            word_distance=2,
            channel_constraint="CLIENT",
            dict_level=1,
        )
        json_str = match.model_dump_json()
        restored = DictMatch.model_validate_json(json_str)
        assert restored.word_distance == 2
        assert restored.channel_constraint == "CLIENT"
        assert restored.dict_level == 1
        assert restored.matched_text == "matched text"

    def test_dictionary_condition_json_roundtrip(self):
        """DictionaryCondition must survive JSON roundtrip with new fields."""
        cond = DictionaryCondition(
            text="NE ustraivaet",
            word_distance=3,
            word_count=2,
            channel_constraint="CLIENT",
            without_list=["cancel"],
            is_exact=False,
            phrase_groups=[["NE", "ustraivaet"], ["ustraivaet"]],
            nested_phrases=["details"],
            is_exception=True,
            exception_phrases=["ustraivaet"],
        )
        json_str = cond.model_dump_json()
        restored = DictionaryCondition.model_validate_json(json_str)
        assert restored.phrase_groups == [["NE", "ustraivaet"], ["ustraivaet"]]
        assert restored.nested_phrases == ["details"]
        assert restored.is_exception is True
        assert restored.exception_phrases == ["ustraivaet"]

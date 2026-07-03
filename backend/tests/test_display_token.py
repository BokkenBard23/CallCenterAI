"""Tests for DisplayToken model, group_into_display_tokens(), and GET /api/dictionary/{session_id}/tokens endpoint.

Covers:
  1. DisplayToken model creation and validation
  2. resolve_phrase_channel() logic
  3. group_into_display_tokens() algorithm:
     - Basic WORD grouping
     - TERMINAL quotes → PHRASE with is_exact=True
     - LEXEME separators (ИЛИ/И/НЕ/OR/AND/NOT)
     - BRACKET tokens (parentheses)
     - WHITESPACE skipping
     - Channel resolution (CLIENT/OPERATOR/ANY/mixed)
     - Word distance (max of group)
     - Edge cases (empty, single word, multi-word, error tokens)
  4. DictionaryNode.token_section field
  5. GET /api/dictionary/{session_id}/tokens endpoint:
     - Happy path
     - Session not found
     - Dictionary not found
     - No token section
  6. UploadDictionaryResponse.display_tokens field
  7. Backward compatibility (existing tests still pass)
"""
import sys
import os
import pytest

# Ensure smartlogger is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))
# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models import (
    DisplayToken,
    DictionaryNode,
    TokenModel,
    TokenSection,
)
from app.services.xml_parser import (
    group_into_display_tokens,
    resolve_phrase_channel,
)


# ═══════════════════════════════════════════════════════════
# 1. DisplayToken model
# ═══════════════════════════════════════════════════════════

class TestDisplayTokenModel:
    """Test DisplayToken Pydantic model."""

    def test_create_word_token(self):
        dt = DisplayToken(text="hello", type="WORD", channel="CLIENT", word_distance=2)
        assert dt.text == "hello"
        assert dt.type == "WORD"
        assert dt.channel == "CLIENT"
        assert dt.word_distance == 2
        assert dt.is_error is False
        assert dt.is_exact is False

    def test_create_phrase_token_with_is_exact(self):
        dt = DisplayToken(text="hello world", type="PHRASE", channel="ANY", word_distance=2, is_exact=True)
        assert dt.type == "PHRASE"
        assert dt.is_exact is True

    def test_create_lexeme_token(self):
        dt = DisplayToken(text="или", type="LEXEME", channel="ANY", word_distance=2)
        assert dt.type == "LEXEME"

    def test_create_bracket_token(self):
        dt = DisplayToken(text="(", type="BRACKET", channel="ANY", word_distance=2)
        assert dt.type == "BRACKET"

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            DisplayToken(text="test", type="INVALID", channel="ANY", word_distance=2)

    def test_invalid_channel_raises(self):
        with pytest.raises(Exception):
            DisplayToken(text="test", type="WORD", channel="INVALID", word_distance=2)

    def test_defaults(self):
        dt = DisplayToken(text="test", type="WORD")
        assert dt.channel == "ANY"
        assert dt.word_distance == 2
        assert dt.is_error is False
        assert dt.is_exact is False


# ═══════════════════════════════════════════════════════════
# 2. resolve_phrase_channel
# ═══════════════════════════════════════════════════════════

class TestResolvePhraseChannel:
    """Test channel resolution logic."""

    def test_empty_set_returns_any(self):
        assert resolve_phrase_channel(set()) == "ANY"

    def test_single_client(self):
        assert resolve_phrase_channel({"CLIENT"}) == "CLIENT"

    def test_single_operator(self):
        assert resolve_phrase_channel({"OPERATOR"}) == "OPERATOR"

    def test_single_any(self):
        assert resolve_phrase_channel({"ANY"}) == "ANY"

    def test_mixed_client_operator_returns_first_non_any(self):
        """NEW semantics (UI-2.5): first non-empty non-ANY value from the set.

        Per SmartLogger spec [4]: all words in a phrase have the SAME channel.
        resolve_phrase_channel takes the first non-empty, non-ANY value —
        it does NOT downgrade CLIENT+OPERATOR mix to ANY.
        Set iteration order is unspecified, so the result is one of CLIENT/OPERATOR.
        """
        result = resolve_phrase_channel({"CLIENT", "OPERATOR"})
        assert result in ("CLIENT", "OPERATOR")

    def test_any_does_not_override_client(self):
        """NEW semantics (UI-2.5): ANY does NOT override — first non-ANY wins.

        resolve_phrase_channel skips ANY and returns the first real channel.
        With {"CLIENT", "ANY"} the result is CLIENT (not ANY).
        """
        result = resolve_phrase_channel({"CLIENT", "ANY"})
        assert result == "CLIENT"

    def test_any_does_not_override_operator(self):
        """NEW semantics (UI-2.5): ANY does NOT override — first non-ANY wins.

        With {"OPERATOR", "ANY"} the result is OPERATOR (not ANY).
        """
        result = resolve_phrase_channel({"OPERATOR", "ANY"})
        assert result == "OPERATOR"

    def test_all_three_returns_first_non_any(self):
        """NEW semantics (UI-2.5): {CLIENT, OPERATOR, ANY} → first non-ANY value.

        Not ANY — takes the first non-empty, non-ANY channel from the set.
        """
        result = resolve_phrase_channel({"CLIENT", "OPERATOR", "ANY"})
        assert result in ("CLIENT", "OPERATOR")


# ═══════════════════════════════════════════════════════════
# 3. group_into_display_tokens
# ═══════════════════════════════════════════════════════════

class TestGroupIntoDisplayTokens:
    """Test the main token grouping algorithm."""

    def test_empty_token_section(self):
        ts = TokenSection(tokens=[])
        result = group_into_display_tokens(ts)
        assert result == []

    def test_single_word(self):
        ts = TokenSection(tokens=[
            TokenModel(text="hello", type="WORD", channel="CLIENT", word_distance="2"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].text == "hello"
        assert result[0].type == "WORD"
        assert result[0].channel == "CLIENT"
        assert result[0].is_exact is False

    def test_multiple_words_without_quotes(self):
        """Multiple consecutive WORDs → single PHRASE (not exact)."""
        ts = TokenSection(tokens=[
            TokenModel(text="переключиться", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="на", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="другого", type="WORD", channel="CLIENT", word_distance="2"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].text == "переключиться на другого"
        assert result[0].type == "PHRASE"
        assert result[0].channel == "CLIENT"
        assert result[0].is_exact is False

    def test_quoted_phrase_is_exact(self):
        """TERMINAL quotes wrap a phrase → type=PHRASE, is_exact=True."""
        ts = TokenSection(tokens=[
            TokenModel(text='"', type="TERMINAL"),
            TokenModel(text="переключиться", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="на", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="другого", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="оператора", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text='"', type="TERMINAL"),
        ])
        result = group_into_display_tokens(ts)
        # The quote opens, words accumulate, quote closes → 1 PHRASE with is_exact
        assert len(result) == 1
        assert result[0].text == "переключиться на другого оператора"
        assert result[0].type == "PHRASE"
        assert result[0].is_exact is True
        assert result[0].channel == "CLIENT"

    def test_lexeme_separator(self):
        """LEXEME ИЛИ separates groups."""
        ts = TokenSection(tokens=[
            TokenModel(text="фраза", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="один", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="ИЛИ", type="LEXEME"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="фраза", type="WORD", channel="OPERATOR", word_distance="3"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="два", type="WORD", channel="OPERATOR", word_distance="3"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 3
        assert result[0].text == "фраза один"
        assert result[0].type == "PHRASE"
        assert result[0].channel == "CLIENT"
        assert result[1].text == "или"
        assert result[1].type == "LEXEME"
        assert result[2].text == "фраза два"
        assert result[2].type == "PHRASE"
        assert result[2].channel == "OPERATOR"

    def test_bracket_tokens(self):
        """TERMINAL ( and ) → BRACKET tokens."""
        ts = TokenSection(tokens=[
            TokenModel(text="(", type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text="слово", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=")", type="TERMINAL"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 3
        assert result[0].text == "("
        assert result[0].type == "BRACKET"
        assert result[1].text == "слово"
        assert result[1].type == "WORD"
        assert result[2].text == ")"
        assert result[2].type == "BRACKET"

    def test_mixed_channels_resolves_to_first_non_any(self):
        """NEW semantics (UI-2.5): WORD tokens with CLIENT + OPERATOR channels → first non-ANY.

        Per SmartLogger spec [4]: all words in a phrase have the SAME channel.
        resolve_phrase_channel takes the first non-empty, non-ANY value —
        does NOT downgrade mixed CLIENT+OPERATOR to ANY.
        """
        ts = TokenSection(tokens=[
            TokenModel(text="клиентское", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="операторское", type="WORD", channel="OPERATOR", word_distance="2"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].channel in ("CLIENT", "OPERATOR")

    def test_word_distance_max(self):
        """word_distance = max of all WORD distances in group."""
        ts = TokenSection(tokens=[
            TokenModel(text="слово1", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="слово2", type="WORD", channel="CLIENT", word_distance="5"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="слово3", type="WORD", channel="CLIENT", word_distance="3"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].word_distance == 5

    def test_no_channel_defaults_to_any(self):
        """WORD without channel property → defaults to ANY."""
        ts = TokenSection(tokens=[
            TokenModel(text="слово", type="WORD", channel="", word_distance="2"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].channel == "ANY"

    def test_complex_real_xml_structure(self):
        """Test with structure matching Риск расторжения.xml."""
        ts = TokenSection(tokens=[
            TokenModel(text="(", type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text='"', type="TERMINAL"),
            TokenModel(text="переключиться", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="на", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="другого", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="оператора", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text='"', type="TERMINAL"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="ИЛИ", type="LEXEME"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="отказаться", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="от", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="услуг", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=")", type="TERMINAL"),
        ])
        result = group_into_display_tokens(ts)
        # Expected: BRACKET(, PHRASE(exact,CLIENT), LEXEME(или), PHRASE(not exact,CLIENT), BRACKET)
        assert len(result) == 5

        assert result[0].text == "("
        assert result[0].type == "BRACKET"

        assert result[1].text == "переключиться на другого оператора"
        assert result[1].type == "PHRASE"
        assert result[1].is_exact is True
        assert result[1].channel == "CLIENT"

        assert result[2].text == "или"
        assert result[2].type == "LEXEME"

        assert result[3].text == "отказаться от услуг"
        assert result[3].type == "PHRASE"
        assert result[3].is_exact is False
        assert result[3].channel == "CLIENT"

        assert result[4].text == ")"
        assert result[4].type == "BRACKET"

    def test_single_quoted_word(self):
        """Single word in quotes → PHRASE with is_exact=True."""
        ts = TokenSection(tokens=[
            TokenModel(text='"', type="TERMINAL"),
            TokenModel(text="привет", type="WORD", channel="OPERATOR", word_distance="2"),
            TokenModel(text='"', type="TERMINAL"),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].text == "привет"
        assert result[0].type == "PHRASE"
        assert result[0].is_exact is True

    def test_all_lexeme_keywords(self):
        """All LEXEME keywords produce LEXEME display tokens."""
        for keyword in ["ИЛИ", "OR", "И", "AND", "НЕ", "NOT"]:
            ts = TokenSection(tokens=[
                TokenModel(text="слово", type="WORD", channel="CLIENT", word_distance="2"),
                TokenModel(text=" ", type="WHITESPACE"),
                TokenModel(text=keyword, type="LEXEME"),
            ])
            result = group_into_display_tokens(ts)
            assert len(result) == 2
            assert result[0].type == "WORD"
            assert result[1].type == "LEXEME"
            assert result[1].text == keyword.lower()

    def test_error_token_preserved(self):
        """is_error flag is preserved in display tokens."""
        ts = TokenSection(tokens=[
            TokenModel(text="ошибка", type="WORD", channel="ANY", word_distance="2", is_error=True),
        ])
        result = group_into_display_tokens(ts)
        assert len(result) == 1
        assert result[0].is_error is True

    def test_whitespace_only(self):
        """Only whitespace tokens → empty result."""
        ts = TokenSection(tokens=[
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text=" ", type="WHITESPACE"),
        ])
        result = group_into_display_tokens(ts)
        assert result == []

    def test_multiple_or_groups(self):
        """Multiple ИЛИ-separated groups each become separate tokens."""
        ts = TokenSection(tokens=[
            TokenModel(text="а", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="ИЛИ", type="LEXEME"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="б", type="WORD", channel="OPERATOR", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="ИЛИ", type="LEXEME"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="в", type="WORD", channel="ANY", word_distance="2"),
        ])
        result = group_into_display_tokens(ts)
        # WORD(а), LEXEME(или), WORD(б), LEXEME(или), WORD(в)
        assert len(result) == 5
        assert result[0].type == "WORD"
        assert result[0].channel == "CLIENT"
        assert result[1].type == "LEXEME"
        assert result[2].type == "WORD"
        assert result[2].channel == "OPERATOR"
        assert result[3].type == "LEXEME"
        assert result[4].type == "WORD"
        assert result[4].channel == "ANY"


# ═══════════════════════════════════════════════════════════
# 4. DictionaryNode.token_section
# ═══════════════════════════════════════════════════════════

class TestDictionaryNodeTokenSection:
    """Test that DictionaryNode stores token_section."""

    def test_token_section_stored(self):
        ts = TokenSection(tokens=[
            TokenModel(text="слово", type="WORD", channel="CLIENT", word_distance="2"),
        ])
        node = DictionaryNode(
            id="test-id",
            name="Test Dict",
            token_section=ts,
        )
        assert node.token_section is not None
        assert len(node.token_section.tokens) == 1

    def test_token_section_defaults_to_none(self):
        node = DictionaryNode(id="test-id", name="Test Dict")
        assert node.token_section is None


# ═══════════════════════════════════════════════════════════
# 5. API Endpoint Tests (using FastAPI TestClient)
# ═══════════════════════════════════════════════════════════

class TestDictionaryTokensEndpoint:
    """Test GET /api/dictionary/{session_id}/tokens endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client with a fresh session store."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.utils.session import SessionStore, Session
        from app.models import DictionaryNode, TokenModel, TokenSection

        # We need to replace the session store for testing
        # but since it's a module-level singleton, we'll use
        # the real one and add test data
        return TestClient(app)

    @pytest.fixture
    def session_with_dict(self):
        """Create a session with a dictionary that has token_section."""
        from app.utils.session import session_store
        from app.models import DictionaryNode, TokenModel, TokenSection

        session = session_store.create()
        ts = TokenSection(tokens=[
            TokenModel(text="(", type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text='"', type="TERMINAL"),
            TokenModel(text="тестовое", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE"),
            TokenModel(text="слово", type="WORD", channel="CLIENT", word_distance="3"),
            TokenModel(text='"', type="TERMINAL"),
            TokenModel(text=")", type="TERMINAL"),
        ])
        dict_node = DictionaryNode(
            id="test-dict-id",
            name="Тестовый словарь",
            token_section=ts,
        )
        session_store.add_dictionary(session.id, dict_node)
        return session.id, "Тестовый словарь"

    def test_get_tokens_happy_path(self, client, session_with_dict):
        session_id, dict_name = session_with_dict
        response = client.get(f"/api/dictionary/{session_id}/tokens", params={"dict_name": dict_name})
        assert response.status_code == 200
        tokens = response.json()
        assert len(tokens) > 0
        # First token should be bracket
        assert tokens[0]["type"] == "BRACKET"
        assert tokens[0]["text"] == "("

    def test_get_tokens_default_dict(self, client, session_with_dict):
        """When dict_name is omitted, first dictionary is used."""
        session_id, _ = session_with_dict
        response = client.get(f"/api/dictionary/{session_id}/tokens")
        assert response.status_code == 200

    def test_session_not_found(self, client):
        response = client.get("/api/dictionary/nonexistent-session/tokens")
        assert response.status_code == 404

    def test_dict_not_found(self, client, session_with_dict):
        session_id, _ = session_with_dict
        response = client.get(
            f"/api/dictionary/{session_id}/tokens",
            params={"dict_name": "Несуществующий словарь"},
        )
        assert response.status_code == 404

    def test_no_token_section(self):
        """Dictionary without token_section returns 422."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.utils.session import session_store
        from app.models import DictionaryNode

        session = session_store.create()
        # DictionaryNode without token_section (defaults to None)
        dict_node = DictionaryNode(
            id="no-tokens-id",
            name="Пустой словарь",
            condition_count=1,
        )
        session_store.add_dictionary(session.id, dict_node)

        client = TestClient(app)
        response = client.get(
            f"/api/dictionary/{session.id}/tokens",
            params={"dict_name": "Пустой словарь"},
        )
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════
# 6. UploadDictionaryResponse.display_tokens
# ═══════════════════════════════════════════════════════════

class TestUploadDictionaryResponseDisplayTokens:
    """Test that UploadDictionaryResponse includes display_tokens field."""

    def test_display_tokens_in_upload_response(self):
        from app.models import UploadDictionaryResponse, DictionaryValidation

        dt = DisplayToken(text="тест", type="WORD", channel="CLIENT", word_distance=2)
        resp = UploadDictionaryResponse(
            session_id="test-session",
            dictionary=None,
            validation=DictionaryValidation(),
            display_tokens=[dt],
        )
        assert resp.display_tokens is not None
        assert len(resp.display_tokens) == 1
        assert resp.display_tokens[0].text == "тест"

    def test_display_tokens_defaults_to_none(self):
        from app.models import UploadDictionaryResponse, DictionaryValidation

        resp = UploadDictionaryResponse(
            session_id="test-session",
            dictionary=None,
            validation=DictionaryValidation(),
        )
        assert resp.display_tokens is None


# ═══════════════════════════════════════════════════════════
# 7. Integration: parse_xml_bytes → DictionaryNode → display_tokens
# ═══════════════════════════════════════════════════════════

class TestXmlToDisplayTokensIntegration:
    """Integration test: XML → parse → DictionaryNode → display_tokens."""

    @pytest.mark.asyncio
    async def test_xml_parsing_stores_token_section(self):
        """Parsed DictionaryNode has token_section populated from real XML."""
        from app.services.xml_parser import parse_xml_bytes

        xml = """<?xml version="1.0" encoding="utf-8"?>
<SpeechLabRequest type="SpeechLabRequest">
  <Id>test-id-001</Id>
  <Name>Тестовый словарь</Name>
  <Tokens>
    <Token><Text>"</Text><Type>TERMINAL</Type></Token>
    <Token><Text>привет</Text><Type>WORD</Type><Properties Channel="CLIENT" WordDistance="2" /></Token>
    <Token><Text> </Text><Type>WHITESPACE</Type></Token>
    <Token><Text>мир</Text><Type>WORD</Type><Properties Channel="CLIENT" WordDistance="2" /></Token>
    <Token><Text>"</Text><Type>TERMINAL</Type></Token>
  </Tokens>
</SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml.encode("utf-8"), "test.xml")

        # token_section should be populated
        assert node.token_section is not None
        assert len(node.token_section.tokens) > 0

        # Convert to display tokens
        display_tokens = group_into_display_tokens(node.token_section)
        assert len(display_tokens) == 1
        assert display_tokens[0].text == "привет мир"
        assert display_tokens[0].type == "PHRASE"
        assert display_tokens[0].is_exact is True
        assert display_tokens[0].channel == "CLIENT"

    @pytest.mark.asyncio
    async def test_xml_without_tokens_has_no_token_section(self):
        """XML with no <Tokens> section → token_section is None."""
        from app.services.xml_parser import parse_xml_bytes

        xml = """<?xml version="1.0" encoding="utf-8"?>
<SpeechLabRequest type="SpeechLabRequest">
  <Id>test-id-002</Id>
  <Name>Пустой словарь</Name>
</SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml.encode("utf-8"), "empty.xml")
        assert node.token_section is None

    @pytest.mark.asyncio
    async def test_nested_xml_preserves_token_section(self):
        """Child dictionaries also get token_section from their <Tokens>."""
        from app.services.xml_parser import parse_xml_bytes

        xml = """<?xml version="1.0" encoding="utf-8"?>
<SpeechLabRequest type="SpeechLabRequest">
  <Id>root-id</Id>
  <Name>Корень</Name>
  <Tokens>
    <Token><Text>корневое</Text><Type>WORD</Type><Properties Channel="CLIENT" WordDistance="2" /></Token>
  </Tokens>
  <Requests>
    <SpeechLabRequest>
      <Id>child-id</Id>
      <Name>Ребёнок</Name>
      <Tokens>
        <Token><Text>дочернее</Text><Type>WORD</Type><Properties Channel="OPERATOR" WordDistance="3" /></Token>
      </Tokens>
    </SpeechLabRequest>
  </Requests>
</SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml.encode("utf-8"), "nested.xml")

        # Root has token_section
        assert node.token_section is not None
        root_tokens = group_into_display_tokens(node.token_section)
        assert len(root_tokens) == 1
        assert root_tokens[0].text == "корневое"
        assert root_tokens[0].channel == "CLIENT"

        # Child has token_section
        assert len(node.children) == 1
        assert node.children[0].token_section is not None
        child_tokens = group_into_display_tokens(node.children[0].token_section)
        assert len(child_tokens) == 1
        assert child_tokens[0].text == "дочернее"
        assert child_tokens[0].channel == "OPERATOR"
        assert child_tokens[0].word_distance == 3

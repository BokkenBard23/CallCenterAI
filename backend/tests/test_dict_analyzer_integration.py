"""Integration tests for dict-analyzer enriched XML parsing and search.

Covers the full pipeline:
  1. XML parsing with SavedState, Attributes, per-token Properties, TERMINAL quotes
  2. logic_builder: PhraseGroup extraction, attribute tree, attribute decoding
  3. morph_matcher: is_exact flag passthrough, exact matching vs morphological
  4. search.py: is_exact propagated through to DictMatch, match_type field
  5. Backward compatibility: existing XML without new fields still works
  6. RemainderRequest parsing
"""
import sys
import os
import pytest

# Ensure smartlogger is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))
# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models import (
    AttributeSection,
    AttributeTokenModel,
    DecodedAttribute,
    DictionaryCondition,
    DictionaryNode,
    DictMatch,
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
    decode_attribute,
    detect_warnings,
)
from app.services.morph_matcher import (
    match_phrase_morphological,
    match_phrase_morphological_detailed,
)
from app.services.xml_parser import parse_xml_bytes


# ═══════════════════════════════════════════════════════════
# 1. SavedState parsing
# ═══════════════════════════════════════════════════════════

class TestSavedStateParsing:
    """Tests for <SavedState> section parsing."""

    @pytest.mark.asyncio
    async def test_saved_state_parsed(self):
        """SavedState fields must be extracted from XML."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-1</Id>
          <Name>Test Dict</Name>
          <SavedState>
            <TotalFound>5</TotalFound>
            <LastUpdateTime>2026-06-12T12:00:00Z</LastUpdateTime>
            <ExecutionTime>00:00:03</ExecutionTime>
            <IsActual>true</IsActual>
            <IsCancelled>false</IsCancelled>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.total_found == 5
        assert node.saved_state.is_actual is True
        assert node.saved_state.is_cancelled is False
        assert "2026-06-12" in node.saved_state.last_update_time

    @pytest.mark.asyncio
    async def test_saved_state_defaults(self):
        """Missing SavedState must produce default values."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-2</Id>
          <Name>Test Dict</Name>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        # saved_state should be None when no SavedState element exists
        # (previously returned SavedState() with misleading is_actual=True)
        assert node.saved_state is None


# ═══════════════════════════════════════════════════════════
# 2. AttributeSection parsing
# ═══════════════════════════════════════════════════════════

class TestAttributeParsing:
    """Tests for <Attributes> section parsing and attribute tree building."""

    @pytest.mark.asyncio
    async def test_attribute_section_parsed(self):
        """Attribute tokens must be extracted from XML."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-3</Id>
          <Name>Test Dict</Name>
          <Attributes>
            <AttributeTokens>
              <AttributeToken>
                <Text>attribute</Text>
                <Type>ATTRIBUTE</Type>
                <SearchAttribute>
                  <Key>CallDirection</Key>
                  <Value>PhoneCallDirectionIngoing</Value>
                </SearchAttribute>
                <IsError>false</IsError>
              </AttributeToken>
              <AttributeToken>
                <Text>AND</Text>
                <Type>LEXEME</Type>
                <SearchAttribute><Key/><Value/></SearchAttribute>
                <IsError>false</IsError>
              </AttributeToken>
              <AttributeToken>
                <Text>attribute</Text>
                <Type>ATTRIBUTE</Type>
                <SearchAttribute>
                  <Key>Duration</Key>
                  <Value>00:00:30;10675199.02:48:05.4775807</Value>
                </SearchAttribute>
                <IsError>false</IsError>
              </AttributeToken>
            </AttributeTokens>
          </Attributes>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert node.attributes is not None
        assert len(node.attributes.attribute_tokens) == 3
        assert node.attributes.attribute_tokens[0].type == "ATTRIBUTE"
        assert node.attributes.attribute_tokens[0].search_attribute.key == "CallDirection"
        assert node.attributes.attribute_tokens[1].type == "LEXEME"
        assert node.attributes.attribute_tokens[1].text == "AND"

    @pytest.mark.asyncio
    async def test_attribute_tree_built(self):
        """Attribute tree (AND/OR/NOT) must be built from attribute tokens."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-4</Id>
          <Name>Test Dict</Name>
          <Attributes>
            <AttributeTokens>
              <AttributeToken>
                <Text>attribute</Text><Type>ATTRIBUTE</Type>
                <SearchAttribute><Key>CallDirection</Key><Value>PhoneCallDirectionIngoing</Value></SearchAttribute>
                <IsError>false</IsError>
              </AttributeToken>
              <AttributeToken>
                <Text>AND</Text><Type>LEXEME</Type>
                <SearchAttribute><Key/><Value/></SearchAttribute>
                <IsError>false</IsError>
              </AttributeToken>
              <AttributeToken>
                <Text>attribute</Text><Type>ATTRIBUTE</Type>
                <SearchAttribute><Key>Duration</Key><Value>00:00:30;10675199.02:48:05.4775807</Value></SearchAttribute>
                <IsError>false</IsError>
              </AttributeToken>
            </AttributeTokens>
          </Attributes>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert node.attribute_tree is not None
        assert node.attribute_tree.node_type == "AND"
        assert len(node.attribute_tree.children) == 2
        # First child: CallDirection
        assert node.attribute_tree.children[0].node_type == "ATTRIBUTE"
        assert node.attribute_tree.children[0].payload["key"] == "CallDirection"
        # Second child: Duration
        assert node.attribute_tree.children[1].node_type == "ATTRIBUTE"
        assert node.attribute_tree.children[1].payload["key"] == "Duration"


# ═══════════════════════════════════════════════════════════
# 3. TERMINAL quotes → is_exact
# ═══════════════════════════════════════════════════════════

class TestTerminalQuotesIsExact:
    """Tests for TERMINAL quote handling → is_exact flag on conditions."""

    @pytest.mark.asyncio
    async def test_quoted_phrase_is_exact(self):
        """Words inside TERMINAL quotes must have is_exact=True."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-5</Id>
          <Name>Test Dict</Name>
          <Tokens>
            <Token><Text>"</Text><Type>TERMINAL</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1087;&#1077;&#1088;&#1077;&#1081;&#1090;&#1080;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1085;&#1072;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1084;&#1090;&#1089;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
            <Token><Text>"</Text><Type>TERMINAL</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        assert node.conditions[0].is_exact is True
        assert node.conditions[0].channel_constraint == "CLIENT"
        assert "перейти" in node.conditions[0].text

    @pytest.mark.asyncio
    async def test_unquoted_phrase_not_exact(self):
        """Words NOT inside quotes must have is_exact=False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-6</Id>
          <Name>Test Dict</Name>
          <Tokens>
            <Token><Text>&#1087;&#1077;&#1088;&#1077;&#1081;&#1090;&#1080;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1084;&#1090;&#1089;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        assert node.conditions[0].is_exact is False

    @pytest.mark.asyncio
    async def test_mixed_quoted_and_unquoted(self):
        """ИЛИ-separated phrases with mixed quoting."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-id-7</Id>
          <Name>Test Dict</Name>
          <Tokens>
            <Token><Text>"</Text><Type>TERMINAL</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1090;&#1086;&#1095;&#1085;&#1086;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
            <Token><Text>"</Text><Type>TERMINAL</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1048;&#1051;&#1048;</Text><Type>LEXEME</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1085;&#1077;&#1090;&#1086;&#1095;&#1085;&#1086;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 2
        # First phrase: quoted → is_exact=True
        assert node.conditions[0].is_exact is True
        # Second phrase: not quoted → is_exact=False
        assert node.conditions[1].is_exact is False


# ═══════════════════════════════════════════════════════════
# 4. Per-token Channel and WordDistance
# ═══════════════════════════════════════════════════════════

class TestPerTokenProperties:
    """Tests for per-token Channel and WordDistance extraction."""

    def test_phrase_group_channel_from_tokens(self):
        """PhraseGroup channel must reflect per-token Channel values."""
        token_section = TokenSection(tokens=[
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="на", type="WORD", channel="CLIENT", word_distance="3"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="мтс", type="WORD", channel="ANY", word_distance="2"),
        ])
        groups = build_phrase_groups(token_section)
        assert len(groups) == 1
        # CLIENT is the most common non-ANY channel
        assert groups[0].channel == "CLIENT"

    def test_phrase_group_word_distance_first_nonzero(self):
        """PhraseGroup word_distance = first non-zero per-token distance (per SmartLogger spec).

        Rationale: all words in a phrase have the SAME WordDistance per spec [4].
        The parser takes the first WORD token's WordDistance value (not min()).
        """
        token_section = TokenSection(tokens=[
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="на", type="WORD", channel="CLIENT", word_distance="5"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="мтс", type="WORD", channel="CLIENT", word_distance="1"),
        ])
        groups = build_phrase_groups(token_section)
        assert len(groups) == 1
        assert groups[0].word_distance == 2  # first non-zero value (not min)

    def test_condition_uses_phrase_group_wd(self):
        """DictionaryCondition.word_distance must come from PhraseGroup."""
        token_section = TokenSection(tokens=[
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="5"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="мтс", type="WORD", channel="CLIENT", word_distance="5"),
        ])
        groups = build_phrase_groups(token_section)
        assert len(groups) == 1
        assert groups[0].word_distance == 5

        # Simulating what xml_parser does:
        condition = DictionaryCondition(
            text=" ".join(groups[0].words),
            word_distance=groups[0].word_distance if groups[0].word_distance > 0 else 2,
            channel_constraint=groups[0].channel.upper() if groups[0].channel else "ANY",
            is_exact=groups[0].is_exact,
        )
        assert condition.word_distance == 5


# ═══════════════════════════════════════════════════════════
# 5. Attribute decoding
# ═══════════════════════════════════════════════════════════

class TestAttributeDecoding:
    """Tests for decode_attribute() human-readable output."""

    def test_decode_duration_min_only(self):
        """Duration with only min (max is TimeSpan.MaxValue)."""
        result = decode_attribute("Duration", "00:00:30;10675199.02:48:05.4775807")
        assert result.key == "Duration"
        assert "30" in result.human_readable
        assert ">=" in result.human_readable

    def test_decode_duration_range(self):
        """Duration with min and max."""
        result = decode_attribute("Duration", "00:00:10;00:00:60")
        assert "10" in result.human_readable
        assert "60" in result.human_readable or "1 мин" in result.human_readable

    def test_decode_call_direction_ingoing(self):
        """CallDirection ingoing → Входящий."""
        result = decode_attribute("CallDirection", "PhoneCallDirectionIngoing")
        assert "Входящий" in result.human_readable

    def test_decode_call_direction_outgoing(self):
        """CallDirection outgoing → Исходящий."""
        result = decode_attribute("CallDirection", "PhoneCallDirectionOutgoing")
        assert "Исходящий" in result.human_readable

    def test_decode_remote_phone_not_starts_with(self):
        """RemotePhoneNumber with NotStartsWith."""
        result = decode_attribute("RemotePhoneNumber", "NotStartsWith|07")
        assert "07" in result.human_readable
        assert "не начинается" in result.human_readable

    def test_decode_userdef5(self):
        """UserDef5 with comma-separated SIP servers."""
        result = decode_attribute("UserDef5", "Equals|, val1 , val2 , val3")
        assert "3 шт" in result.human_readable

    def test_decode_external_dictionary(self):
        """ExternalDictionary with UUIDs."""
        result = decode_attribute("ExternalDictionary", "uuid1,uuid2|OR")
        assert "2 шт" in result.human_readable
        assert "OR" in result.human_readable

    def test_decode_channel(self):
        """Channel CLIENT → Клиент."""
        result = decode_attribute("Channel", "CLIENT")
        assert "Клиент" in result.human_readable

    def test_decode_word_distance(self):
        """WordDistance → human readable."""
        result = decode_attribute("WordDistance", "5")
        assert "5" in result.human_readable

    def test_decode_unknown_key(self):
        """Unknown key falls through to 'key = value'."""
        result = decode_attribute("SomeUnknownKey", "SomeValue")
        assert result.human_readable == "SomeUnknownKey = SomeValue"


# ═══════════════════════════════════════════════════════════
# 6. Attribute tree building
# ═══════════════════════════════════════════════════════════

class TestAttributeTreeBuilding:
    """Tests for build_attribute_tree() AND/OR/NOT precedence."""

    def test_simple_and(self):
        """Two attributes connected by AND."""
        section = AttributeSection(attribute_tokens=[
            AttributeTokenModel(text="attr1", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="CallDirection", value="PhoneCallDirectionIngoing")),
            AttributeTokenModel(text="AND", type="LEXEME",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="attr2", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="Duration", value="00:00:30;10675199.02:48:05")),
        ])
        tree = build_attribute_tree(section)
        assert tree.node_type == "AND"
        assert len(tree.children) == 2

    def test_or_precedence_lower_than_and(self):
        """OR has lower precedence than AND: A AND B OR C → (A AND B) OR C."""
        section = AttributeSection(attribute_tokens=[
            AttributeTokenModel(text="A", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="A", value="1")),
            AttributeTokenModel(text="AND", type="LEXEME",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="B", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="B", value="2")),
            AttributeTokenModel(text="OR", type="LEXEME",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="C", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="C", value="3")),
        ])
        tree = build_attribute_tree(section)
        # Root should be OR
        assert tree.node_type == "OR"
        assert len(tree.children) == 2
        # Left child should be AND
        assert tree.children[0].node_type == "AND"
        # Right child should be ATTRIBUTE C
        assert tree.children[1].node_type == "ATTRIBUTE"

    def test_not_prefix(self):
        """NOT prefix on an attribute."""
        section = AttributeSection(attribute_tokens=[
            AttributeTokenModel(text="NOT", type="LEXEME",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="attr", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="CallDirection", value="PhoneCallDirectionOutgoing")),
        ])
        tree = build_attribute_tree(section)
        assert tree.node_type == "NOT"
        assert len(tree.children) == 1
        assert tree.children[0].node_type == "ATTRIBUTE"

    def test_parentheses_override_precedence(self):
        """Parentheses group subexpressions: A OR (B AND C) → A OR (B AND C)."""
        section = AttributeSection(attribute_tokens=[
            AttributeTokenModel(text="A", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="A", value="1")),
            AttributeTokenModel(text="OR", type="LEXEME",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="(", type="TERMINAL",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="B", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="B", value="2")),
            AttributeTokenModel(text="AND", type="LEXEME",
                                search_attribute=SearchAttribute()),
            AttributeTokenModel(text="C", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="C", value="3")),
            AttributeTokenModel(text=")", type="TERMINAL",
                                search_attribute=SearchAttribute()),
        ])
        tree = build_attribute_tree(section)
        assert tree.node_type == "OR"
        assert len(tree.children) == 2
        # Right child should be AND (because of parentheses)
        assert tree.children[1].node_type == "AND"

    def test_empty_attribute_section(self):
        """Empty attribute section → empty AND node."""
        section = AttributeSection()
        tree = build_attribute_tree(section)
        assert tree.node_type == "AND"
        assert len(tree.children) == 0


# ═══════════════════════════════════════════════════════════
# 7. Exact matching in morph_matcher
# ═══════════════════════════════════════════════════════════

class TestExactMatching:
    """Tests for is_exact=True matching (no morphology, ordered subsequence)."""

    EXACT_TURNS = [
        {"speaker": "Клиент", "text": "перейти на мтс"},
        {"speaker": "Клиент", "text": "буду переходить на мтс"},
        {"speaker": "Клиент", "text": "мтс перейти на"},
        {"speaker": "Клиент", "text": "перейти мтс"},
    ]
    EXACT_CHANNEL = {i: "Клиент" for i in range(len(EXACT_TURNS))}

    def test_exact_match_contiguous(self):
        """Exact phrase 'перейти на мтс' must match turn 0 exactly."""
        matches = match_phrase_morphological_detailed(
            phrase_text="перейти на мтс",
            word_distance=0,
            channel_constraint="CLIENT",
            turns=self.EXACT_TURNS,
            channel_map=self.EXACT_CHANNEL,
            is_exact=True,
        )
        turn_indices = [idx for idx, _, _ in matches]
        assert 0 in turn_indices

    def test_exact_no_morphological_match(self):
        """Exact mode must NOT match morphological variants.

        'перейти' ≠ 'переходить' in exact mode (no lemmatization).
        """
        matches = match_phrase_morphological_detailed(
            phrase_text="перейти на мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.EXACT_TURNS,
            channel_map=self.EXACT_CHANNEL,
            is_exact=True,
        )
        turn_indices = [idx for idx, _, _ in matches]
        # Turn 1 has "переходить" not "перейти" — should NOT match in exact mode
        assert 1 not in turn_indices

    def test_exact_bow_allows_reordering(self):
        """exact_bow mode (is_exact=True) allows free word order (BOW).

        NEW semantics (UI-2.5): exact_bow = exact form (no morphology) + free order.
        Turn 2 'мтс перейти на' has the exact words 'перейти', 'на', 'мтс' —
        reordered but still matches via BOW (no morphology, free order).
        """
        matches = match_phrase_morphological_detailed(
            phrase_text="перейти на мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.EXACT_TURNS,
            channel_map=self.EXACT_CHANNEL,
            is_exact=True,
        )
        turn_indices = [idx for idx, _, _ in matches]
        # Turn 2: "мтс перейти на" — reordered, exact words → matches via BOW
        assert 2 in turn_indices

    def test_morphological_mode_matches_variants(self):
        """Non-exact (morphological) mode must match variants."""
        matches = match_phrase_morphological_detailed(
            phrase_text="перейти на мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.EXACT_TURNS,
            channel_map=self.EXACT_CHANNEL,
            is_exact=False,
        )
        turn_indices = [idx for idx, _, _ in matches]
        # Turn 1: "переходить" ≈ "перейти" via aspectual pair
        assert 1 in turn_indices

    def test_exact_match_with_word_distance(self):
        """Exact mode must allow extra words within word_distance."""
        matches = match_phrase_morphological_detailed(
            phrase_text="перейти мтс",
            word_distance=1,
            channel_constraint="CLIENT",
            turns=self.EXACT_TURNS,
            channel_map=self.EXACT_CHANNEL,
            is_exact=True,
        )
        turn_indices = [idx for idx, _, _ in matches]
        # Turn 0: "перейти на мтс" — "на" is 1 extra word, WD=1 allows it
        assert 0 in turn_indices

    def test_match_phrase_morphological_detailed_exact_passthrough(self):
        """match_phrase_morphological_detailed with is_exact=True must enforce ordered subsequence.

        This replaces the old match_phrase_exact test — match_phrase_exact was removed
        in UI-2.5 (merged into match_phrase_morphological_detailed via is_exact flag).
        """
        matches = match_phrase_morphological_detailed(
            phrase_text="перейти на мтс",
            word_distance=0,
            channel_constraint="CLIENT",
            turns=self.EXACT_TURNS,
            channel_map=self.EXACT_CHANNEL,
            is_exact=True,
        )
        turn_indices = [idx for idx, _, _ in matches]
        assert 0 in turn_indices
        assert 1 not in turn_indices  # Morphological variant


# ═══════════════════════════════════════════════════════════
# 8. RemainderRequest parsing
# ═══════════════════════════════════════════════════════════

class TestRemainderRequestParsing:
    """Tests for <SpeechLabRemainderRequest> parsing."""

    @pytest.mark.asyncio
    async def test_remainder_request_flag(self):
        """SpeechLabRemainderRequest must set is_remainder=True."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>root-id</Id>
          <Name>Root Dict</Name>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
          <Requests>
            <SpeechLabRemainderRequest type="SpeechLabRemainderRequest">
              <Id>remainder-id</Id>
              <Name>Remainder Dict</Name>
              <Tokens>
                <Token><Text>remainder</Text><Type>WORD</Type><IsError>false</IsError>
                  <Properties Channel="ANY" WordDistance="2" />
                </Token>
              </Tokens>
            </SpeechLabRemainderRequest>
          </Requests>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.children) == 1
        assert node.children[0].is_remainder is True
        assert node.children[0].name == "Remainder Dict"

    @pytest.mark.asyncio
    async def test_normal_child_not_remainder(self):
        """Normal SpeechLabRequest child must have is_remainder=False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>root-id</Id>
          <Name>Root Dict</Name>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
          <Requests>
            <SpeechLabRequest type="SpeechLabRequest">
              <Id>child-id</Id>
              <Name>Child Dict</Name>
              <Tokens>
                <Token><Text>child</Text><Type>WORD</Type><IsError>false</IsError>
                  <Properties Channel="ANY" WordDistance="2" />
                </Token>
              </Tokens>
            </SpeechLabRequest>
          </Requests>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.children) == 1
        assert node.children[0].is_remainder is False


# ═══════════════════════════════════════════════════════════
# 9. PhraseGroup building
# ═══════════════════════════════════════════════════════════

class TestPhraseGroupBuilding:
    """Tests for build_phrase_groups() from TokenSection."""

    def test_single_phrase(self):
        """Single phrase from WORD tokens."""
        ts = TokenSection(tokens=[
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="на", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="мтс", type="WORD", channel="CLIENT", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        assert len(groups) == 1
        assert groups[0].words == ["перейти", "на", "мтс"]
        assert groups[0].channel == "CLIENT"
        assert groups[0].is_exact is False

    def test_two_phrases_separated_by_ili(self):
        """Two phrase groups separated by ИЛИ."""
        ts = TokenSection(tokens=[
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="ИЛИ", type="LEXEME", channel="ANY", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="отказаться", type="WORD", channel="CLIENT", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        assert len(groups) == 2
        assert groups[0].words == ["перейти"]
        assert groups[1].words == ["отказаться"]

    def test_quoted_phrase_is_exact(self):
        """TERMINAL quotes make is_exact=True."""
        ts = TokenSection(tokens=[
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="мтс", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        assert len(groups) == 1
        assert groups[0].is_exact is True
        assert groups[0].words == ["перейти", "мтс"]

    def test_mixed_quotes_and_plain(self):
        """Quoted phrase ИЛИ unquoted phrase."""
        ts = TokenSection(tokens=[
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text="перейти", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="OR", type="LEXEME", channel="ANY", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="отказаться", type="WORD", channel="CLIENT", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        assert len(groups) == 2
        assert groups[0].is_exact is True
        assert groups[1].is_exact is False

    def test_empty_token_section(self):
        """Empty TokenSection → no phrase groups."""
        ts = TokenSection(tokens=[])
        groups = build_phrase_groups(ts)
        assert len(groups) == 0

    def test_only_whitespace_tokens(self):
        """TokenSection with only WHITESPACE → no phrase groups."""
        ts = TokenSection(tokens=[
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        assert len(groups) == 0


# ═══════════════════════════════════════════════════════════
# 10. detect_warnings
# ═══════════════════════════════════════════════════════════

class TestDetectWarnings:
    """Tests for detect_warnings() from logic_builder."""

    def test_no_attributes_warning(self):
        """Dictionary without attributes → warning about matching all calls."""
        attrs = AttributeSection()
        ts = TokenSection(tokens=[
            TokenModel(text="hello", type="WORD", channel="ANY", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        warnings = detect_warnings(attrs, ts, groups)
        assert any("без атрибутных фильтров" in w for w in warnings)

    def test_all_quoted_warning(self):
        """All phrases in quotes → warning about possible over-restriction."""
        attrs = AttributeSection(attribute_tokens=[
            AttributeTokenModel(text="attr", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="CallDirection", value="PhoneCallDirectionIngoing")),
        ])
        ts = TokenSection(tokens=[
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text="hello", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        warnings = detect_warnings(attrs, ts, groups)
        assert any("кавычках" in w for w in warnings)

    def test_no_warnings_normal_case(self):
        """Normal dictionary with attributes and mixed quoting → no critical warnings."""
        attrs = AttributeSection(attribute_tokens=[
            AttributeTokenModel(text="attr", type="ATTRIBUTE",
                                search_attribute=SearchAttribute(key="CallDirection", value="PhoneCallDirectionIngoing")),
        ])
        ts = TokenSection(tokens=[
            TokenModel(text="hello", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text="ИЛИ", type="LEXEME", channel="ANY", word_distance="2"),
            TokenModel(text=" ", type="WHITESPACE", channel="ANY", word_distance="2"),
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
            TokenModel(text="world", type="WORD", channel="CLIENT", word_distance="2"),
            TokenModel(text='"', type="TERMINAL", channel="ANY", word_distance="2"),
        ])
        groups = build_phrase_groups(ts)
        warnings = detect_warnings(attrs, ts, groups)
        # Should not have "all quoted" or "no attributes" warnings
        assert not any("без атрибутных фильтров" in w for w in warnings)
        assert not any("Все фразы в кавычках" in w for w in warnings)


# ═══════════════════════════════════════════════════════════
# 11. Backward compatibility
# ═══════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Tests ensuring existing XML and API contracts are not broken."""

    @pytest.mark.asyncio
    async def test_simple_xml_no_enriched_fields(self):
        """Old-style XML without SavedState/Attributes must parse correctly."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>simple-id</Id>
          <Name>Simple Dict</Name>
          <Tokens>
            <Token><Text>&#1087;&#1077;&#1088;&#1077;&#1081;&#1090;&#1080;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
            <Token><Text>&#1084;&#1090;&#1089;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert node.name == "Simple Dict"
        assert len(node.conditions) == 1
        assert node.conditions[0].text == "перейти мтс"
        assert node.conditions[0].is_exact is False
        assert node.conditions[0].channel_constraint == "CLIENT"
        # Enriched fields have defaults
        assert node.is_remainder is False
        assert node.attribute_tree is None

    @pytest.mark.asyncio
    async def test_dict_match_is_exact_match_default(self):
        """DictMatch.is_exact_match must default to False."""
        match = DictMatch(
            phrase_text="test",
            matched_text="test",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
        )
        assert match.is_exact_match is False

    @pytest.mark.asyncio
    async def test_dict_match_is_exact_match_set(self):
        """DictMatch.is_exact_match must be settable."""
        match = DictMatch(
            phrase_text="test",
            matched_text="test",
            quarter="Test Dict",
            turn_index=0,
            speaker="Клиент",
            is_exact_match=True,
            match_type="exact_bow",
        )
        assert match.is_exact_match is True
        assert match.match_type == "exact_bow"

    @pytest.mark.asyncio
    async def test_dictionary_condition_is_exact_default(self):
        """DictionaryCondition.is_exact must default to False."""
        cond = DictionaryCondition(text="test phrase")
        assert cond.is_exact is False

    @pytest.mark.asyncio
    async def test_dictionary_node_enriched_defaults(self):
        """DictionaryNode enriched fields must have safe defaults."""
        node = DictionaryNode(
            id="test-id",
            name="Test",
            conditions=[],
        )
        assert node.saved_state is None
        assert node.attributes is None
        assert node.is_remainder is False
        assert node.phrase_groups == []
        assert node.attribute_tree is None


# ═══════════════════════════════════════════════════════════
# 12. Full pipeline: XML → parse → conditions → match
# ═══════════════════════════════════════════════════════════

class TestFullPipeline:
    """End-to-end tests: XML parsing + condition extraction + matching."""

    @pytest.mark.asyncio
    async def test_exact_phrase_from_xml_to_match(self):
        """Full pipeline: quoted phrase in XML → is_exact condition → exact match."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>pipe-id-1</Id>
          <Name>Pipeline Test</Name>
          <Tokens>
            <Token><Text>"</Text><Type>TERMINAL</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="1" />
            </Token>
            <Token><Text>&#1087;&#1077;&#1088;&#1077;&#1081;&#1090;&#1080;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="1" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="1" />
            </Token>
            <Token><Text>&#1084;&#1090;&#1089;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="1" />
            </Token>
            <Token><Text>"</Text><Type>TERMINAL</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="1" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        assert len(node.conditions) == 1
        condition = node.conditions[0]
        assert condition.is_exact is True

        # Search with exact matching
        turns = [
            {"speaker": "Клиент", "text": "перейти на мтс"},
            {"speaker": "Клиент", "text": "буду переходить на мтс"},
        ]
        channel_map = {0: "Клиент", 1: "Клиент"}

        matches = match_phrase_morphological_detailed(
            phrase_text=condition.text,
            word_distance=condition.word_distance,
            channel_constraint=condition.channel_constraint,
            turns=turns,
            channel_map=channel_map,
            is_exact=condition.is_exact,
        )
        turn_indices = [idx for idx, _, _ in matches]
        # Turn 0: exact words "перейти" + "мтс" → match
        assert 0 in turn_indices
        # Turn 1: "переходить" ≠ "перейти" in exact mode → no match
        assert 1 not in turn_indices

    @pytest.mark.asyncio
    async def test_morphological_phrase_from_xml_to_match(self):
        """Full pipeline: unquoted phrase → morphological match with aspectual pairs."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>pipe-id-2</Id>
          <Name>Pipeline Test Morph</Name>
          <Tokens>
            <Token><Text>&#1087;&#1077;&#1088;&#1077;&#1081;&#1090;&#1080;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="1" />
            </Token>
            <Token><Text> </Text><Type>WHITESPACE</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="1" />
            </Token>
            <Token><Text>&#1084;&#1090;&#1089;</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="CLIENT" WordDistance="1" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, validation = await parse_xml_bytes(xml, "test.xml")
        condition = node.conditions[0]
        assert condition.is_exact is False

        turns = [
            {"speaker": "Клиент", "text": "перейти на мтс"},
            {"speaker": "Клиент", "text": "буду переходить на мтс"},
        ]
        channel_map = {0: "Клиент", 1: "Клиент"}

        matches = match_phrase_morphological_detailed(
            phrase_text=condition.text,
            word_distance=condition.word_distance,
            channel_constraint=condition.channel_constraint,
            turns=turns,
            channel_map=channel_map,
            is_exact=condition.is_exact,
        )
        turn_indices = [idx for idx, _, _ in matches]
        # Morphological mode: both should match
        assert 0 in turn_indices
        assert 1 in turn_indices  # "переходить" ≈ "перейти" via aspectual pair


# ═══════════════════════════════════════════════════════════
# 13. TimeSpan parsing
# ═══════════════════════════════════════════════════════════

class TestTimeSpanParsing:
    """Tests for _parse_timespan and _is_timespan_max_value."""

    def test_parse_hhmmss(self):
        """HH:MM:SS format."""
        from app.services.logic_builder import _parse_timespan
        assert _parse_timespan("00:00:30") == 30
        assert _parse_timespan("01:30:00") == 5400

    def test_parse_dd_hhmmss(self):
        """DD.HH:MM:SS format."""
        from app.services.logic_builder import _parse_timespan
        assert _parse_timespan("1.00:00:00") == 86400

    def test_parse_with_fractional(self):
        """HH:MM:SS.fffffff format (fractional seconds stripped)."""
        from app.services.logic_builder import _parse_timespan
        assert _parse_timespan("00:00:30.4775807") == 30

    def test_is_timespan_max_value(self):
        """Large day count → TimeSpan.MaxValue."""
        from app.services.logic_builder import _is_timespan_max_value
        assert _is_timespan_max_value("10675199.02:48:05.4775807") is True
        assert _is_timespan_max_value("00:00:30") is False

    def test_format_duration_seconds(self):
        """Human-readable duration formatting."""
        from app.services.logic_builder import _format_duration_seconds
        assert _format_duration_seconds(30) == "30 сек"
        assert _format_duration_seconds(60) == "1 мин"
        assert _format_duration_seconds(3600) == "1 ч"

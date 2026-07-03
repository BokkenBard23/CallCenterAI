"""Tests for SavedState false-default fix (IP-1.4).

Verifies that:
1. SavedState model defaults to is_actual=False (not True)
2. _parse_saved_state returns None when <SavedState> is absent
3. _parse_saved_state returns is_actual=False when <IsActual> sub-element is missing
4. _parse_saved_state returns is_actual=True only when XML explicitly says so
5. SavedState() construction without arguments produces safe defaults
6. Downstream DictionaryNode.saved_state is None when element absent
7. Edge cases: empty <SavedState/>, <IsActual> with unexpected values
"""

from __future__ import annotations

import pytest

from app.models import DictionaryNode, SavedState
from app.services.xml_parser import _parse_saved_state, parse_xml_bytes


class TestSavedStateModelDefaults:
    """SavedState Pydantic model must have safe defaults."""

    def test_default_is_actual_is_false(self) -> None:
        """SavedState() must default is_actual to False, not True."""
        ss = SavedState()
        assert ss.is_actual is False, (
            "SavedState() defaults is_actual=True which is a false-positive "
            "'data exists' signal when no data was actually found"
        )

    def test_default_total_found_is_zero(self) -> None:
        """SavedState() must default total_found to 0."""
        ss = SavedState()
        assert ss.total_found == 0

    def test_default_is_cancelled_is_false(self) -> None:
        """SavedState() must default is_cancelled to False."""
        ss = SavedState()
        assert ss.is_cancelled is False

    def test_default_strings_are_empty(self) -> None:
        """SavedState() must default time strings to empty."""
        ss = SavedState()
        assert ss.last_update_time == ""
        assert ss.execution_time == ""

    def test_explicit_is_actual_true(self) -> None:
        """SavedState(is_actual=True) must work when explicitly set."""
        ss = SavedState(is_actual=True)
        assert ss.is_actual is True

    def test_explicit_fields_override_defaults(self) -> None:
        """Explicitly set fields must override defaults."""
        ss = SavedState(
            total_found=10,
            last_update_time="2026-01-01T00:00:00Z",
            execution_time="00:00:05",
            is_actual=True,
            is_cancelled=True,
        )
        assert ss.total_found == 10
        assert ss.is_actual is True
        assert ss.is_cancelled is True


class TestParseSavedStateAbsent:
    """_parse_saved_state must return None when <SavedState> is absent."""

    @pytest.mark.asyncio
    async def test_no_saved_state_element(self) -> None:
        """When <SavedState> is absent, node.saved_state must be None."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-absent</Id>
          <Name>No SavedState Dict</Name>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is None

    @pytest.mark.asyncio
    async def test_dictionary_node_default_saved_state_none(self) -> None:
        """DictionaryNode() must default saved_state to None."""
        node = DictionaryNode(id="test-id", name="Test")
        assert node.saved_state is None


class TestParseSavedStateExplicitTrue:
    """_parse_saved_state must return is_actual=True when XML explicitly says so."""

    @pytest.mark.asyncio
    async def test_is_actual_true_explicit(self) -> None:
        """When <IsActual>true</IsActual> is in XML, is_actual must be True."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-actual-true</Id>
          <Name>Actual Dict</Name>
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

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is True
        assert node.saved_state.total_found == 5

    @pytest.mark.asyncio
    async def test_is_actual_true_case_insensitive(self) -> None:
        """<IsActual>True</IsActual> (capitalized) must also work."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-actual-true-cap</Id>
          <Name>Actual Dict</Name>
          <SavedState>
            <TotalFound>3</TotalFound>
            <IsActual>True</IsActual>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is True
        assert node.saved_state.total_found == 3


class TestParseSavedStateMissingIsActual:
    """_parse_saved_state must return is_actual=False when <IsActual> is missing."""

    @pytest.mark.asyncio
    async def test_saved_state_without_is_actual(self) -> None:
        """When <SavedState> exists but <IsActual> is missing, is_actual must be False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-no-is-actual</Id>
          <Name>Dict Without IsActual</Name>
          <SavedState>
            <TotalFound>5</TotalFound>
            <LastUpdateTime>2026-06-12T12:00:00Z</LastUpdateTime>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is False, (
            "When <IsActual> is missing, defaulting to True is a false-positive. "
            "Must default to False (conservative: don't claim data exists)."
        )
        assert node.saved_state.total_found == 5

    @pytest.mark.asyncio
    async def test_empty_saved_state_element(self) -> None:
        """Empty <SavedState/> must not produce is_actual=True."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-empty-ss</Id>
          <Name>Empty SavedState</Name>
          <SavedState/>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is False, (
            "Empty <SavedState/> must not default is_actual to True"
        )
        assert node.saved_state.total_found == 0

    @pytest.mark.asyncio
    async def test_saved_state_with_only_total_found(self) -> None:
        """SavedState with only TotalFound must have is_actual=False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-only-total</Id>
          <Name>Only TotalFound</Name>
          <SavedState>
            <TotalFound>10</TotalFound>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.total_found == 10
        assert node.saved_state.is_actual is False


class TestParseSavedStateIsActualFalse:
    """_parse_saved_state must return is_actual=False when XML says false."""

    @pytest.mark.asyncio
    async def test_is_actual_false_explicit(self) -> None:
        """When <IsActual>false</IsActual>, is_actual must be False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-actual-false</Id>
          <Name>Not Actual Dict</Name>
          <SavedState>
            <TotalFound>0</TotalFound>
            <IsActual>false</IsActual>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is False

    @pytest.mark.asyncio
    async def test_is_actual_False_capitalized(self) -> None:
        """When <IsActual>False</IsActual> (capitalized), is_actual must be False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-actual-False</Id>
          <Name>Not Actual Dict</Name>
          <SavedState>
            <TotalFound>2</TotalFound>
            <IsActual>False</IsActual>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is False


class TestParseSavedStateEdgeCases:
    """Edge cases for SavedState parsing."""

    @pytest.mark.asyncio
    async def test_is_actual_unexpected_value(self) -> None:
        """Unexpected <IsActual> value (e.g. 'yes') must default to False."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-unexpected</Id>
          <Name>Unexpected IsActual</Name>
          <SavedState>
            <TotalFound>1</TotalFound>
            <IsActual>yes</IsActual>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        # "yes" is not "true" → _parse_bool returns False
        assert node.saved_state.is_actual is False

    @pytest.mark.asyncio
    async def test_is_cancelled_true_explicit(self) -> None:
        """<IsCancelled>true</IsCancelled> must parse correctly."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-cancelled</Id>
          <Name>Cancelled Dict</Name>
          <SavedState>
            <TotalFound>0</TotalFound>
            <IsActual>true</IsActual>
            <IsCancelled>true</IsCancelled>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_cancelled is True
        assert node.saved_state.is_actual is True

    @pytest.mark.asyncio
    async def test_child_dict_saved_state_independent(self) -> None:
        """Parent and child dictionaries must have independent saved_state."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>parent-id</Id>
          <Name>Parent Dict</Name>
          <SavedState>
            <TotalFound>10</TotalFound>
            <IsActual>true</IsActual>
          </SavedState>
          <Tokens>
            <Token><Text>parent_word</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
          <Requests>
            <SpeechLabRequest type="SpeechLabRequest">
              <Id>child-id</Id>
              <Name>Child Dict</Name>
              <Tokens>
                <Token><Text>child_word</Text><Type>WORD</Type><IsError>false</IsError>
                  <Properties Channel="ANY" WordDistance="2" />
                </Token>
              </Tokens>
            </SpeechLabRequest>
          </Requests>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.is_actual is True
        assert node.saved_state.total_found == 10

        # Child has no <SavedState> → saved_state is None
        assert len(node.children) == 1
        child = node.children[0]
        assert child.saved_state is None


class TestSavedStateNoRegressions:
    """Verify that the fix doesn't break existing test expectations."""

    @pytest.mark.asyncio
    async def test_full_saved_state_roundtrip(self) -> None:
        """Full SavedState with all fields must parse correctly."""
        xml = b"""<?xml version="1.0"?>
        <SpeechLabRequest type="SpeechLabRequest">
          <Id>test-full-ss</Id>
          <Name>Full SavedState Dict</Name>
          <SavedState>
            <TotalFound>42</TotalFound>
            <LastUpdateTime>2026-06-15T10:30:00Z</LastUpdateTime>
            <ExecutionTime>00:00:07</ExecutionTime>
            <IsActual>true</IsActual>
            <IsCancelled>false</IsCancelled>
          </SavedState>
          <Tokens>
            <Token><Text>hello</Text><Type>WORD</Type><IsError>false</IsError>
              <Properties Channel="ANY" WordDistance="2" />
            </Token>
          </Tokens>
        </SpeechLabRequest>"""

        node, _ = await parse_xml_bytes(xml, "test.xml")
        assert node.saved_state is not None
        assert node.saved_state.total_found == 42
        assert node.saved_state.is_actual is True
        assert node.saved_state.is_cancelled is False
        assert "2026-06-15" in node.saved_state.last_update_time
        assert node.saved_state.execution_time == "00:00:07"

"""Tests for _parse_extra_limitations (V2/V3 — real <ExtraLimitations> format).

Covers:
  - Empty <ExtraLimitations /> → []
  - <ExtraLimitation> StartEnd with <Limit>s
  - <ExtraLimitation> Parent with EventSelector / SearchDirection
  - Multiple <ExtraLimitation> elements in one <ExtraLimitations>
  - Legacy <Tokens> inside <ExtraLimitation> → no crash (V2 backward compat)
  - Missing optional sub-elements → defaults

Per smartlogger-xml-verification.md V1/V2: real dictionaries NEVER contain
<Tokens> inside <ExtraLimitation>. The parser must look for
EventType/SearchSpecifier/Settings/Limits/Limit instead.
"""

from __future__ import annotations

import os
import sys

import pytest
from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.xml_parser import _parse_extra_limitations
from app.models import ExtraLimitation, ExtraLimitationLimit


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _parse(xml_str: str):
    root = etree.fromstring(xml_str)
    return _parse_extra_limitations(root)


# ═══════════════════════════════════════════════════════════════════════
# 1. Empty / missing
# ═══════════════════════════════════════════════════════════════════════


class TestEmpty:
    def test_no_extra_limitations_element(self) -> None:
        """No <ExtraLimitations> child → []."""
        xml = b"<SpeechLabRequest><Name>x</Name></SpeechLabRequest>"
        assert _parse(xml) == []

    def test_self_closing_extra_limitations(self) -> None:
        """<ExtraLimitations /> self-closing → []."""
        xml = b"<SpeechLabRequest><ExtraLimitations /></SpeechLabRequest>"
        assert _parse(xml) == []

    def test_empty_extra_limitations_element(self) -> None:
        """<ExtraLimitations></ExtraLimitations> → []."""
        xml = b"<SpeechLabRequest><ExtraLimitations></ExtraLimitations></SpeechLabRequest>"
        assert _parse(xml) == []


# ═══════════════════════════════════════════════════════════════════════
# 2. StartEnd EventType with limits
# ═══════════════════════════════════════════════════════════════════════


class TestStartEndEventType:
    def test_start_end_with_limit_first(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
              <Settings />
              <Limits>
                <Limit>
                  <Value>15</Value>
                  <ValueType>Seconds</ValueType>
                  <Channel>CLIENT</Channel>
                  <Enabled>true</Enabled>
                  <LimitType>First</LimitType>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result) == 1
        el = result[0]
        assert el.event_type == "StartEnd"
        assert el.search_specifier == "OnlyInGaps"
        assert el.settings == {}
        assert len(el.limits) == 1
        limit = el.limits[0]
        assert limit.value == 15
        assert limit.value_type == "Seconds"
        assert limit.channel == "CLIENT"
        assert limit.enabled is True
        assert limit.limit_type == "First"
        assert limit.event_selector is None
        assert limit.search_direction is None

    def test_start_end_with_limit_last(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>ExcludeGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>30</Value>
                  <ValueType>Words</ValueType>
                  <Channel>OPERATOR</Channel>
                  <Enabled>false</Enabled>
                  <LimitType>Last</LimitType>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result) == 1
        el = result[0]
        assert el.event_type == "StartEnd"
        assert el.search_specifier == "ExcludeGaps"
        assert len(el.limits) == 1
        limit = el.limits[0]
        assert limit.value == 30
        assert limit.value_type == "Words"
        assert limit.channel == "OPERATOR"
        assert limit.enabled is False
        assert limit.limit_type == "Last"

    def test_two_limits_per_extra_limitation(self) -> None:
        """A single ExtraLimitation can have 2 Limits (Before+After etc)."""
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>10</Value>
                  <LimitType>First</LimitType>
                </Limit>
                <Limit>
                  <Value>20</Value>
                  <LimitType>Last</LimitType>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result[0].limits) == 2
        assert result[0].limits[0].value == 10
        assert result[0].limits[0].limit_type == "First"
        assert result[0].limits[1].value == 20
        assert result[0].limits[1].limit_type == "Last"


# ═══════════════════════════════════════════════════════════════════════
# 3. Parent EventType with EventSelector / SearchDirection
# ═══════════════════════════════════════════════════════════════════════


class TestParentEventType:
    def test_parent_with_event_selector_each(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>Parent</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>5</Value>
                  <EventSelector>Each</EventSelector>
                  <SearchDirection>Before</SearchDirection>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result) == 1
        el = result[0]
        assert el.event_type == "Parent"
        assert el.search_specifier == "OnlyInGaps"
        assert len(el.limits) == 1
        limit = el.limits[0]
        assert limit.event_selector == "Each"
        assert limit.search_direction == "Before"
        assert limit.limit_type is None  # not StartEnd

    def test_parent_with_event_selector_first_after(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>Parent</EventType>
              <SearchSpecifier>ExcludeGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>120</Value>
                  <EventSelector>First</EventSelector>
                  <SearchDirection>After</SearchDirection>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        limit = result[0].limits[0]
        assert limit.event_selector == "First"
        assert limit.search_direction == "After"


# ═══════════════════════════════════════════════════════════════════════
# 4. Multiple ExtraLimitation elements
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleExtraLimitations:
    def test_two_extra_limitations_one_block(self) -> None:
        """Real dictionaries group 2 ExtraLimitations in 1 ExtraLimitations block."""
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>15</Value>
                  <LimitType>First</LimitType>
                </Limit>
              </Limits>
            </ExtraLimitation>
            <ExtraLimitation>
              <EventType>Parent</EventType>
              <SearchSpecifier>ExcludeGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>30</Value>
                  <EventSelector>Each</EventSelector>
                  <SearchDirection>Before</SearchDirection>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result) == 2
        assert result[0].event_type == "StartEnd"
        assert result[0].search_specifier == "OnlyInGaps"
        assert result[1].event_type == "Parent"
        assert result[1].search_specifier == "ExcludeGaps"


# ═══════════════════════════════════════════════════════════════════════
# 5. Defaults & missing optional elements
# ═══════════════════════════════════════════════════════════════════════


class TestDefaults:
    def test_missing_value_defaults_to_zero(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <Limits>
                <Limit>
                  <LimitType>First</LimitType>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        limit = result[0].limits[0]
        assert limit.value == 0
        assert limit.value_type == "Seconds"
        assert limit.channel == "ANY"
        assert limit.enabled is False

    def test_invalid_value_falls_back_to_zero(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <Limits>
                <Limit>
                  <Value>not-a-number</Value>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert result[0].limits[0].value == 0

    def test_invalid_channel_falls_back_to_any(self) -> None:
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <Limits>
                <Limit>
                  <Channel>WEIRD_CHANNEL</Channel>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert result[0].limits[0].channel == "ANY"

    def test_extra_limitation_without_limits(self) -> None:
        """<ExtraLimitation> with no <Limits> → empty limits list."""
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result) == 1
        assert result[0].limits == []

    def test_settings_with_subkeys(self) -> None:
        """Settings sub-keys are captured defensively (real dicts have none)."""
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <Settings>
                <Foo>bar</Foo>
                <Baz>qux</Baz>
              </Settings>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert result[0].settings == {"Foo": "bar", "Baz": "qux"}


# ═══════════════════════════════════════════════════════════════════════
# 6. Legacy backward compat — <Tokens> inside <ExtraLimitation>
# ═══════════════════════════════════════════════════════════════════════


class TestLegacyTokensCompat:
    def test_legacy_tokens_inside_extra_limitation_does_not_crash(self) -> None:
        """V2: real dictionaries never have <Tokens> inside <ExtraLimitation>,
        but legacy/synthetic test fixtures might. The new parser ignores them
        and returns ExtraLimitation with empty event_type (no EventType tag).
        """
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <Tokens>
                <Token>
                  <Type>WORD</Type>
                  <Text>cancel</Text>
                </Token>
              </Tokens>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        # Must NOT raise — V2 backward compat
        result = _parse(xml)
        assert isinstance(result, list)
        assert len(result) == 1
        # No EventType/SearchSpecifier → empty strings; no Limits → empty list
        assert result[0].event_type == ""
        assert result[0].search_specifier == ""
        assert result[0].limits == []

    def test_legacy_mixed_tokens_and_event_type(self) -> None:
        """If both <Tokens> and <EventType> are present, parser uses EventType
        (structured path) and ignores legacy <Tokens> entirely.
        """
        xml = b"""<SpeechLabRequest>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
              <Tokens>
                <Token>
                  <Type>WORD</Type>
                  <Text>legacy_phrase</Text>
                </Token>
              </Tokens>
              <Limits>
                <Limit>
                  <Value>10</Value>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        result = _parse(xml)
        assert len(result) == 1
        assert result[0].event_type == "StartEnd"
        assert result[0].limits[0].value == 10
        # No legacy phrase leak into structured fields
        assert result[0].search_specifier == "OnlyInGaps"


# ═══════════════════════════════════════════════════════════════════════
# 7. Integration with DictionaryCondition parsing
# ═══════════════════════════════════════════════════════════════════════


class TestConditionIntegration:
    """Verify that parsed conditions carry the new extra_limitations field."""

    def test_condition_has_extra_limitations_after_parse(self) -> None:
        from app.services.xml_parser import _parse_tokens_enriched
        from app.models import PhraseGroup

        xml = b"""<SpeechLabRequest>
          <Tokens>
            <Token>
              <Type>WORD</Type>
              <Text>hello</Text>
            </Token>
          </Tokens>
          <ExtraLimitations>
            <ExtraLimitation>
              <EventType>StartEnd</EventType>
              <SearchSpecifier>OnlyInGaps</SearchSpecifier>
              <Limits>
                <Limit>
                  <Value>10</Value>
                  <LimitType>First</LimitType>
                </Limit>
              </Limits>
            </ExtraLimitation>
          </ExtraLimitations>
        </SpeechLabRequest>"""
        root = etree.fromstring(xml)
        from app.services.xml_parser import _parse_token_section
        token_section = _parse_token_section(root)
        from app.services.logic_builder import build_phrase_groups
        phrase_groups = build_phrase_groups(token_section)

        conditions, _warnings = _parse_tokens_enriched(root, phrase_groups)
        assert len(conditions) == 1
        cond = conditions[0]
        assert cond.text == "hello"
        # without_list stays [] for backward compat (V2/V3)
        assert cond.without_list == []
        # extra_limitations is populated with the structured ExtraLimitation
        assert len(cond.extra_limitations) == 1
        el = cond.extra_limitations[0]
        assert el.event_type == "StartEnd"
        assert el.search_specifier == "OnlyInGaps"
        assert el.limits[0].value == 10
        assert el.limits[0].limit_type == "First"

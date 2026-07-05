"""Tests for app.services.llm_utils — generic LLM output parsing utilities."""

from __future__ import annotations

import os
import sys

import pytest
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.llm_utils import (
    extract_json,
    extract_json_array,
    safe_parse_model,
)


# ═══════════════════════════════════════════════════════════════════════
# extract_json
# ═══════════════════════════════════════════════════════════════════════


class TestExtractJsonObject:
    def test_pure_json_object(self) -> None:
        text = '{"a": 1, "b": "x"}'
        result = extract_json(text)
        assert result == {"a": 1, "b": "x"}

    def test_fenced_json(self) -> None:
        text = '```json\n{"a": 1}\n```'
        result = extract_json(text)
        assert result == {"a": 1}

    def test_fenced_without_lang_tag(self) -> None:
        text = '```\n{"a": 1}\n```'
        result = extract_json(text)
        assert result == {"a": 1}

    def test_json_with_surrounding_prose(self) -> None:
        text = 'Here is the answer:\n{"a": 1, "b": 2}\nThat is all.'
        result = extract_json(text)
        assert result == {"a": 1, "b": 2}

    def test_multiple_objects_last_wins(self) -> None:
        text = '{"a": 1} intermediate text {"b": 2}'
        result = extract_json(text)
        assert result == {"b": 2}

    def test_nested_object(self) -> None:
        text = '{"outer": {"inner": "value"}}'
        result = extract_json(text)
        assert result == {"outer": {"inner": "value"}}

    def test_invalid_input_returns_none(self) -> None:
        assert extract_json("not json at all") is None

    def test_empty_input_returns_none(self) -> None:
        assert extract_json("") is None


class TestExtractJsonArray:
    def test_pure_array(self) -> None:
        text = '[1, 2, 3]'
        result = extract_json_array(text)
        assert result == [1, 2, 3]

    def test_array_of_objects(self) -> None:
        text = '[{"a": 1}, {"b": 2}]'
        result = extract_json_array(text)
        assert result == [{"a": 1}, {"b": 2}]

    def test_fenced_array(self) -> None:
        text = '```json\n[1, 2]\n```'
        result = extract_json_array(text)
        assert result == [1, 2]

    def test_array_with_prose(self) -> None:
        text = 'Result:\n[1, 2, 3]\nDone.'
        result = extract_json_array(text)
        assert result == [1, 2, 3]

    def test_invalid_returns_empty_list(self) -> None:
        assert extract_json_array("nothing here") == []


# ═══════════════════════════════════════════════════════════════════════
# safe_parse_model
# ═══════════════════════════════════════════════════════════════════════


class _Model(BaseModel):
    name: str = ""
    count: int = 0


class _RequiredModel(BaseModel):
    name: str  # required


class TestSafeParseModel:
    def test_success(self) -> None:
        text = '{"name": "abc", "count": 7}'
        result = safe_parse_model(text, _Model)
        assert isinstance(result, _Model)
        assert result.name == "abc"
        assert result.count == 7

    def test_fenced_success(self) -> None:
        text = '```json\n{"name": "x"}\n```'
        result = safe_parse_model(text, _Model)
        assert result.name == "x"

    def test_no_json_returns_default(self) -> None:
        default = _Model(name="fallback", count=-1)
        result = safe_parse_model("not json", _Model, default=default)
        assert result.name == "fallback"
        assert result.count == -1

    def test_no_json_default_instantiation(self) -> None:
        """When no default provided and model has all-defaults, instantiate."""
        result = safe_parse_model("not json", _Model)
        assert result.name == ""
        assert result.count == 0

    def test_validation_failure_returns_default(self) -> None:
        text = '{"name": "x", "count": "not-a-number"}'
        default = _Model(name="fallback")
        result = safe_parse_model(text, _Model, default=default)
        assert result.name == "fallback"

    def test_required_model_without_default_raises(self) -> None:
        text = "not json"
        with pytest.raises(ValueError, match="required fields"):
            safe_parse_model(text, _RequiredModel)

    def test_required_model_with_explicit_default(self) -> None:
        text = "not json"
        default = _RequiredModel(name="fallback")
        result = safe_parse_model(text, _RequiredModel, default=default)
        assert result.name == "fallback"

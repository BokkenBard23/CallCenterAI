"""Tests for app.services.dictionary_ai — LLM-powered dictionary analysis."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import List, Optional
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import DictionaryCondition, DictionaryNode
from app.services.dictionary_ai import (
    DictionaryAnalysisResult,
    DictionarySuggestion,
    analyze_dictionary,
    suggest_phrases,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _node_with_phrases(phrases: List[str]) -> DictionaryNode:
    conds = [
        DictionaryCondition(
            text=p, word_distance=2, word_count=len(p.split()),
            channel_constraint="ANY",
        )
        for p in phrases
    ]
    return DictionaryNode(id="root", name="root", conditions=conds)


class _FakeProvider:
    """Fake LLMProvider for tests."""

    def __init__(self, response: str = "") -> None:
        self._response = response
        self.generate = AsyncMock(return_value=response)

    async def generate(self, prompt: str, model: Optional[str] = None,
                       system_prompt: Optional[str] = None) -> str:
        return self._response

    async def is_available(self) -> bool:
        return True

    def get_name(self) -> str:
        return "fake"

    def get_default_model(self) -> str:
        return "fake-model"

    def get_models(self) -> List[str]:
        return ["fake-model"]


# ═══════════════════════════════════════════════════════════════════════
# analyze_dictionary
# ═══════════════════════════════════════════════════════════════════════


class TestAnalyzeDictionary:
    @pytest.mark.asyncio
    async def test_parses_llm_json(self) -> None:
        """LLM returns valid JSON → parsed into DictionaryAnalysisResult."""
        fake_response = (
            '{"summary": "Словарь ищет запросы на смену тарифа.", '
            '"examples": ["поменять тариф", "сменить тариф"], '
            '"recommendations": ["Добавьте фразы про переход"]}'
        )
        fake = _FakeProvider(fake_response)
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake):
            node = _node_with_phrases(["поменять тариф", "сменить тариф"])
            result = await analyze_dictionary(node, provider_id="beeline")
        assert isinstance(result, DictionaryAnalysisResult)
        assert "тариф" in result.summary.lower()
        assert len(result.examples) == 2
        assert len(result.recommendations) == 1
        assert result.raw_response == fake_response

    @pytest.mark.asyncio
    async def test_empty_dictionary_returns_default(self) -> None:
        node = DictionaryNode(id="root", name="root", conditions=[])
        result = await analyze_dictionary(node, provider_id="beeline")
        assert "не содержит" in result.summary.lower()
        assert result.examples == []
        assert result.recommendations == []

    @pytest.mark.asyncio
    async def test_llm_failure_returns_degraded(self) -> None:
        """When all providers fail, return degraded result with raw_response=''.
        """
        with patch("app.services.dictionary_ai.get_provider", return_value=None):
            node = _node_with_phrases(["фраза один"])
            result = await analyze_dictionary(node, provider_id="beeline")
        assert result.raw_response == ""
        assert "LLM" in result.summary or "недоступен" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_default_instance(self) -> None:
        """LLM returns garbage → safe_parse_model returns default instance."""
        fake = _FakeProvider("not json at all")
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake):
            node = _node_with_phrases(["фраза"])
            result = await analyze_dictionary(node, provider_id="beeline")
        assert isinstance(result, DictionaryAnalysisResult)
        # Default instance: empty fields, but raw_response preserved
        assert result.raw_response == "not json at all"

    @pytest.mark.asyncio
    async def test_stratified_sampling_invoked(self) -> None:
        """When phrases > 200, stratified sampling kicks in (hard cap thresholds)."""
        # 250 phrases triggers sampling down to 200
        phrases = [f"фраза {i}" for i in range(250)]
        node = _node_with_phrases(phrases)
        fake = _FakeProvider('{"summary":"ok","examples":[],"recommendations":[]}')
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake), \
             patch(
                 "app.services.dictionary_ai.stratified_sample",
                 wraps=__import__("app.services.dict_utils",
                                  fromlist=["stratified_sample"]).stratified_sample
             ) as sample_spy:
            await analyze_dictionary(node, provider_id="beeline")
            assert sample_spy.called
            sampled, was_sampled = sample_spy.call_args[0][0], \
                sample_spy.call_args[0][1] if len(sample_spy.call_args[0]) > 1 else None
            # The first positional arg is the phrases list — verify it was
            # longer than 200 (triggers sampling)
            assert len(sample_spy.call_args[0][0]) == 250


# ═══════════════════════════════════════════════════════════════════════
# suggest_phrases
# ═══════════════════════════════════════════════════════════════════════


class TestSuggestPhrases:
    @pytest.mark.asyncio
    async def test_parses_suggestions_array(self) -> None:
        fake_response = (
            '[{"phrase": "новая фраза", "channel": "CLIENT", "distance": 2},'
            ' {"phrase": "ещё фраза", "channel": "ANY", "distance": 0}]'
        )
        fake = _FakeProvider(fake_response)
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake):
            node = _node_with_phrases(["старая фраза"])
            result = await suggest_phrases(node, provider_id="beeline", count=2)
        assert len(result) == 2
        assert all(isinstance(s, DictionarySuggestion) for s in result)
        assert result[0].phrase == "новая фраза"
        assert result[0].channel == "CLIENT"
        assert result[1].distance == 0

    @pytest.mark.asyncio
    async def test_filters_existing_phrases(self) -> None:
        """Phrases already in the dictionary are filtered out."""
        fake_response = (
            '[{"phrase": "старая фраза", "channel": "ANY", "distance": 2},'
            ' {"phrase": "новая фраза", "channel": "ANY", "distance": 2}]'
        )
        fake = _FakeProvider(fake_response)
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake):
            node = _node_with_phrases(["старая фраза"])
            result = await suggest_phrases(node, provider_id="beeline", count=5)
        assert len(result) == 1
        assert result[0].phrase == "новая фраза"

    @pytest.mark.asyncio
    async def test_empty_dictionary_returns_empty(self) -> None:
        node = DictionaryNode(id="root", name="root", conditions=[])
        result = await suggest_phrases(node, provider_id="beeline")
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty_list(self) -> None:
        with patch("app.services.dictionary_ai.get_provider", return_value=None):
            node = _node_with_phrases(["фраза"])
            result = await suggest_phrases(node, provider_id="beeline")
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self) -> None:
        fake = _FakeProvider("not json")
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake):
            node = _node_with_phrases(["фраза"])
            result = await suggest_phrases(node, provider_id="beeline")
        assert result == []

    @pytest.mark.asyncio
    async def test_stratified_sample_hard_cap_150(self) -> None:
        """suggest_phrases uses hard_cap=150 per spec."""
        phrases = [f"phrase {i}" for i in range(500)]
        node = _node_with_phrases(phrases)
        fake = _FakeProvider("[]")
        import app.services.dict_utils as du
        with patch("app.services.dictionary_ai.get_provider",
                   return_value=fake), \
             patch(
                 "app.services.dictionary_ai.stratified_sample",
                 wraps=du.stratified_sample
             ) as spy:
            await suggest_phrases(node, provider_id="beeline", count=10)
            assert spy.called
            # Inspect the hard_cap kwarg passed in
            call_kwargs = spy.call_args.kwargs
            assert call_kwargs.get("hard_cap") == 150

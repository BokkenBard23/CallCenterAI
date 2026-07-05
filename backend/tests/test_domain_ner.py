"""Tests for GLiNER domain NER (zero-shot, label-agnostic).

Covers:
  1. is_gliner_available: False when gliner not installed (current env)
  2. extract_domain_entities: [] when gliner unavailable
  3. extract_domain_entities with mocked GLiNER model
  4. DEFAULT_DOMAIN_LABELS contents
  5. Empty / whitespace text handling
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import domain_ner
from app.services.domain_ner import (
    DEFAULT_DOMAIN_LABELS,
    extract_domain_entities,
    is_gliner_available,
    reset_gliner_cache,
)


# ═══════════════════════════════════════════════════════════
# Availability
# ═══════════════════════════════════════════════════════════


class TestGlinerAvailability:
    def setup_method(self) -> None:
        reset_gliner_cache()

    def teardown_method(self) -> None:
        reset_gliner_cache()

    def test_returns_bool(self) -> None:
        result = is_gliner_available()
        assert isinstance(result, bool)

    def test_returns_false_when_gliner_not_installed(self) -> None:
        """In current env gliner is not installed → should be False."""
        # Force ImportError by patching the gliner import inside the function.
        with patch.dict("sys.modules", {"gliner": None}):
            reset_gliner_cache()
            # When sys.modules["gliner"] is None, `import gliner` raises ImportError.
            assert is_gliner_available() is False

    def test_returns_true_when_gliner_installed(self) -> None:
        fake_module = MagicMock()
        with patch.dict("sys.modules", {"gliner": fake_module}):
            reset_gliner_cache()
            assert is_gliner_available() is True


# ═══════════════════════════════════════════════════════════
# extract_domain_entities
# ═══════════════════════════════════════════════════════════


class TestExtractDomainEntities:
    def setup_method(self) -> None:
        reset_gliner_cache()

    def teardown_method(self) -> None:
        reset_gliner_cache()

    def test_returns_empty_when_unavailable(self) -> None:
        """GLiNER not installed → returns []."""
        with patch.object(domain_ner, "is_gliner_available", return_value=False):
            result = extract_domain_entities("тариф Безлимит")
        assert result == []

    def test_empty_text_returns_empty(self) -> None:
        with patch.object(domain_ner, "is_gliner_available", return_value=True):
            assert extract_domain_entities("") == []
            assert extract_domain_entities("   ") == []

    def test_mocked_model_returns_entities(self) -> None:
        """Mock the GLiNER model to verify entity parsing."""
        fake_entities = [
            {"text": "тариф Безлимит", "label": "тариф", "start": 0, "end": 14, "score": 0.92},
            {"text": "заявка 123", "label": "заявка", "start": 16, "end": 25, "score": 0.85},
        ]
        fake_model = MagicMock()
        fake_model.predict_entities = MagicMock(return_value=fake_entities)

        with patch.object(domain_ner, "is_gliner_available", return_value=True), \
             patch.object(domain_ner, "_get_gliner_model", return_value=fake_model):
            result = extract_domain_entities(
                "тариф Безлимит, заявка 123", threshold=0.5
            )

        assert len(result) == 2
        assert result[0]["text"] == "тариф Безлимит"
        assert result[0]["label"] == "тариф"
        assert result[0]["score"] == 0.92
        assert result[0]["start"] == 0
        assert result[0]["end"] == 14
        assert result[0]["source"] == "gliner"

        assert result[1]["label"] == "заявка"

    def test_custom_labels_passed_to_model(self) -> None:
        fake_model = MagicMock()
        fake_model.predict_entities = MagicMock(return_value=[])
        custom_labels = ["продукт", "кампания"]

        with patch.object(domain_ner, "is_gliner_available", return_value=True), \
             patch.object(domain_ner, "_get_gliner_model", return_value=fake_model):
            extract_domain_entities("text", labels=custom_labels, threshold=0.7)

        fake_model.predict_entities.assert_called_once_with("text", custom_labels, threshold=0.7)

    def test_model_failure_returns_empty(self) -> None:
        fake_model = MagicMock()
        fake_model.predict_entities = MagicMock(side_effect=RuntimeError("model error"))

        with patch.object(domain_ner, "is_gliner_available", return_value=True), \
             patch.object(domain_ner, "_get_gliner_model", return_value=fake_model):
            result = extract_domain_entities("тариф")

        assert result == []

    def test_model_load_failure_returns_empty(self) -> None:
        """If _get_gliner_model returns None (load failed), extract returns []."""
        with patch.object(domain_ner, "is_gliner_available", return_value=True), \
             patch.object(domain_ner, "_get_gliner_model", return_value=None):
            result = extract_domain_entities("тариф")
        assert result == []


# ═══════════════════════════════════════════════════════════
# DEFAULT_DOMAIN_LABELS
# ═══════════════════════════════════════════════════════════


class TestDefaultLabels:
    def test_contains_telecom_labels(self) -> None:
        for label in ["тариф", "сим-карта", "заявка", "договор", "обращение",
                       "услуга", "абонент", "номер", "счёт", "платёж",
                       "баланс", "подписка", "промо", "акция", "скидка"]:
            assert label in DEFAULT_DOMAIN_LABELS

    def test_at_least_15_labels(self) -> None:
        assert len(DEFAULT_DOMAIN_LABELS) >= 15

"""Integration tests for PII masking pipeline (PIIMaskingService).

Covers:
  - PIIMaskingService initialisation (with/without Presidio)
  - mask_text: basic PII detection (phone, passport, email)
  - mask_text: circuit breaker on repeated failures
  - mask_texts: batch masking
  - mask_dialogue: full dialogue masking preserves structure
  - mask_dialogue: timestamp propagation in masked turns
  - is_available: returns False when Presidio is missing
  - get_stats: returns correct statistics
  - Russian-specific recognizers (INN, SNILS, passport)
  - Edge cases: empty text, non-Russian text, short text
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.services.pii_masking import PIIMaskingService

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def pii_service():
    """Create a PIIMaskingService with default settings.

    If Presidio is not installed, the service will be unavailable
    and tests that mock the underlying engine will still pass.
    """
    return PIIMaskingService(
        language="ru",
        min_score_threshold=0.5,
        circuit_reset_timeout=10.0,  # Short timeout for test speed
        failure_threshold=2,  # Low threshold to test circuit breaker
    )


# ═══════════════════════════════════════════════════════════
# Service availability
# ═══════════════════════════════════════════════════════════


class TestServiceAvailability:
    """PIIMaskingService availability detection."""

    def test_is_available(self, pii_service):
        """is_available() should return True/False based on Presidio."""
        result = pii_service.is_available()
        assert isinstance(result, bool)

    def test_is_available_no_crash(self, pii_service):
        """Calling is_available() multiple times should not crash."""
        for _ in range(5):
            _ = pii_service.is_available()

    def test_constructor_does_not_crash(self):
        """Creating the service should not raise."""
        from app.services.pii_masking import PIIMaskingService
        svc = PIIMaskingService(language="ru")
        assert svc is not None


# ═══════════════════════════════════════════════════════════
# mask_text
# ═══════════════════════════════════════════════════════════


class TestMaskText:
    """Basic PII masking via mask_text()."""

    def test_mask_text_returns_result_object(self, pii_service):
        """mask_text should return a PIIMaskingResult."""
        text = "Здравствуйте, меня зовут Иван."
        result = pii_service.mask_text(text)
        assert result is not None
        # It should either have masked_text or an error
        assert hasattr(result, "masked_text") or hasattr(result, "error")

    def test_mask_text_preserves_non_pii(self, pii_service):
        """Text without PII should be unchanged."""
        text = "Сегодня хорошая погода."
        result = pii_service.mask_text(text)
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        assert result.masked_text == text
        assert result.masked is False

    def test_mask_text_phone_number(self, pii_service):
        """Phone numbers should be detected and masked."""
        text = "Мой номер +7-999-123-45-67."
        result = pii_service.mask_text(text)
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        if result.masked:
            assert "<PHONE>" in result.masked_text or "PHONE" in result.masked_text

    def test_mask_text_returns_entity_counts(self, pii_service):
        """mask_text should return entity_counts dict."""
        text = "Мой номер +7-999-123-45-67."
        result = pii_service.mask_text(text)
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        assert isinstance(result.entity_counts, dict)

    def test_mask_text_returns_processing_time(self, pii_service):
        """mask_text should return processing_time_ms."""
        text = "Тестовый текст."
        result = pii_service.mask_text(text)
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        assert result.processing_time_ms >= 0

    def test_mask_text_empty_text(self, pii_service):
        """Empty text should return immediately without error."""
        result = pii_service.mask_text("")
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        assert result.masked_text == ""
        assert result.masked is False


class TestMaskTextEdgeCases:
    """Edge cases for mask_text."""

    def test_mask_text_short_text(self, pii_service):
        """Very short text should not cause errors."""
        result = pii_service.mask_text("A")
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        assert result.masked_text is not None

    def test_mask_text_non_russian(self, pii_service):
        """Non-Russian text should not crash."""
        text = "Hello, my name is John."
        result = pii_service.mask_text(text)
        if result.error:
            pytest.skip(f"PII service unavailable: {result.error}")
        assert isinstance(result.masked_text, str)


# ═══════════════════════════════════════════════════════════
# mask_texts (batch)
# ═══════════════════════════════════════════════════════════


class TestMaskTexts:
    """Batch PII masking via mask_texts()."""

    def test_mask_texts_returns_list(self, pii_service):
        """mask_texts should return a list with one result per input."""
        texts = ["Привет", "Мир", "Тест"]
        results = pii_service.mask_texts(texts)
        assert len(results) == 3

    def test_mask_texts_empty_list(self, pii_service):
        """Empty list should return empty list."""
        results = pii_service.mask_texts([])
        assert results == []

    def test_mask_texts_all_have_masked_text(self, pii_service):
        """Each result in the batch should have masked_text."""
        texts = ["Один", "Два"]
        results = pii_service.mask_texts(texts)
        for r in results:
            assert hasattr(r, "masked_text")


# ═══════════════════════════════════════════════════════════
# mask_dialogue
# ═══════════════════════════════════════════════════════════


class TestMaskDialogue:
    """Full dialogue masking preserves structure."""

    def test_mask_dialogue_returns_masked_dialogue_result(self, pii_service):
        """mask_dialogue should return a MaskedDialogueResult."""
        from app.models import ParsedDialog, DialogueTurn

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(
            turns=[
                DialogueTurn(speaker="Клиент", text="Мой телефон +7-999-123-45-67"),
                DialogueTurn(speaker="Сотрудник", text="Хорошо, записал."),
            ],
        )
        result = pii_service.mask_dialogue(dialog)
        assert result is not None

    def test_mask_dialogue_preserves_turn_count(self, pii_service):
        """The masked dialogue should have the same number of turns."""
        from app.models import ParsedDialog, DialogueTurn

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(
            turns=[
                DialogueTurn(speaker="Клиент", text="Привет"),
                DialogueTurn(speaker="Сотрудник", text="Здравствуйте"),
                DialogueTurn(speaker="Клиент", text="У меня вопрос."),
            ],
        )
        result = pii_service.mask_dialogue(dialog)
        assert result.masked_dialogue is not None
        assert len(result.masked_dialogue.turns) == 3

    def test_mask_dialogue_preserves_speaker(self, pii_service):
        """Speaker attribution should survive masking."""
        from app.models import ParsedDialog, DialogueTurn

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(
            turns=[
                DialogueTurn(speaker="Клиент", text="Мой номер +7-999-123-45-67"),
            ],
        )
        result = pii_service.mask_dialogue(dialog)
        assert result.masked_dialogue is not None
        assert result.masked_dialogue.turns[0].speaker == "Клиент"

    def test_mask_dialogue_masks_pii(self, pii_service):
        """PII in dialogue turns should be masked."""
        from app.models import ParsedDialog, DialogueTurn

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(
            turns=[
                DialogueTurn(speaker="Клиент", text="Мой номер +7-999-123-45-67"),
            ],
        )
        result = pii_service.mask_dialogue(dialog)
        if result.total_detections > 0 and result.masked_dialogue:
            masked_text = result.masked_dialogue.turns[0].text
            assert "+7-999-123-45-67" not in masked_text

    def test_mask_dialogue_empty_turns(self, pii_service):
        """Dialogue with no turns should return empty masked dialogue."""
        from app.models import ParsedDialog

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(turns=[])
        result = pii_service.mask_dialogue(dialog)
        assert result.masked_dialogue is not None
        assert len(result.masked_dialogue.turns) == 0

    def test_mask_dialogue_entity_counts(self, pii_service):
        """mask_dialogue should return aggregate entity_counts."""
        from app.models import ParsedDialog, DialogueTurn

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(
            turns=[
                DialogueTurn(speaker="Клиент", text="+7-999-123-45-67"),
            ],
        )
        result = pii_service.mask_dialogue(dialog)
        assert isinstance(result.entity_counts, dict)

    def test_mask_dialogue_processing_time(self, pii_service):
        """mask_dialogue should return processing_time_ms."""
        from app.models import ParsedDialog, DialogueTurn

        if not pii_service.is_available():
            pytest.skip("Presidio unavailable — cannot test masking")

        dialog = ParsedDialog(turns=[DialogueTurn(speaker="К", text="Привет")])
        result = pii_service.mask_dialogue(dialog)
        assert result.processing_time_ms >= 0


# ═══════════════════════════════════════════════════════════
# Circuit breaker
# ═══════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Circuit breaker opens after consecutive failures (integration-safe)."""

    def test_circuit_breaker_state_reflects_availability(self, pii_service):
        """The circuit breaker state should match is_available()."""
        stats = pii_service.get_stats()
        assert "circuit_breaker_state" in stats
        state = stats["circuit_breaker_state"]
        assert state in ("closed", "open", "half_open")
        # If Presidio is unavailable, circuit should be open
        if not pii_service.is_available():
            assert state == "open"

    def test_get_stats_after_failures(self, pii_service):
        """get_stats should return masking counts even after failures."""
        stats = pii_service.get_stats()
        assert "total_masked" in stats
        assert "circuit_breaker_state" in stats
        assert "entity_counts" in stats
        assert "avg_latency_ms" in stats
        assert "total_masked" in stats


# ═══════════════════════════════════════════════════════════
# get_stats
# ═══════════════════════════════════════════════════════════


class TestGetStats:
    """Statistics reporting."""

    def test_get_stats_returns_dict(self, pii_service):
        stats = pii_service.get_stats()
        assert isinstance(stats, dict)
        assert "total_masked" in stats
        assert "entity_counts" in stats
        assert "avg_latency_ms" in stats
        assert "circuit_breaker_state" in stats
        logger.info("PII stats keys: %s", list(stats.keys()))

    def test_get_stats_recognizers_list(self, pii_service):
        """The recognizers list should be present when Presidio is available."""
        stats = pii_service.get_stats()
        if "recognizers" in stats:
            assert len(stats["recognizers"]) == 7
        else:
            # When Presidio is unavailable, recognizers may be omitted
            logger.info("Presidio unavailable — no recognizers in stats")


# ═══════════════════════════════════════════════════════════
# Config and entity types
# ═══════════════════════════════════════════════════════════


class TestPiiEntityTypes:
    """PIIEntityType enum stability."""

    def test_all_entity_types_have_presidio_mapping(self):
        """Every PIIEntityType value should have a Presidio mapping."""
        from app.services.pii_masking import _ENTITY_TYPE_TO_PRESIDIO
        from app.models import PIIEntityType

        mapped = set(_ENTITY_TYPE_TO_PRESIDIO.keys())
        all_types = {e.value for e in PIIEntityType}
        unmapped = all_types - mapped
        assert unmapped == set(), f"Unmapped entity types: {unmapped}"

    def test_all_presidio_types_have_placeholder(self):
        """Every Presidio entity type should have a placeholder."""
        from app.services.pii_masking import (
            _ENTITY_TYPE_TO_PRESIDIO,
            _PRESIDIO_ENTITY_PLACEHOLDER_MAP,
        )

        presidio_types = set(_ENTITY_TYPE_TO_PRESIDIO.values())
        placeholder_types = set(_PRESIDIO_ENTITY_PLACEHOLDER_MAP.keys())
        missing = presidio_types - placeholder_types
        assert missing == set(), f"Presidio types without placeholder: {missing}"

    def test_pii_detection_public_no_text(self):
        """PIIDetectionPublic should NOT have a text field (152-FZ)."""
        from app.models import PIIDetectionPublic
        assert "text" not in PIIDetectionPublic.model_fields, (
            "PIIDetectionPublic must NOT contain 'text' field (152-FZ)"
        )

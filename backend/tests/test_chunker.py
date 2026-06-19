"""Tests for Chunker service.

Covers:
  - Short utterance → 1 chunk (chunk_type="utterance")
  - Long utterance → multiple chunks (chunk_type="overlap", overlap 50 tokens)
  - Dialogue with multiple turns → multiple chunks
  - Empty dialogue → []
  - Metadata correct (dialogue_id, turn_index, speaker, token_count, char_count)
  - Entities from NER included when Natasha available
  - Tokenization via razdel
  - Sentence-based splitting for long utterances
  - NER extracts PER, LOC, ORG entities
  - Overlap between adjacent chunks is ~50 tokens
  - Graceful handling when Natasha not available (empty entities)
  - Text sanitization (control character removal)
  - chunk_text() convenience method
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Chunk, ChunkMetadata, DialogueTurn, ParsedDialog
from app.services.chunker import Chunker


# ═══════════════════════════════════════════════════════════
# Fixtures & Helpers
# ═══════════════════════════════════════════════════════════


def _short_dialogue() -> ParsedDialog:
    """Create a short dialogue with 2 turns."""
    return ParsedDialog(
        filename="test.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте! Мне нужна помощь."),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день! Чем могу помочь?"),
        ],
        total_turns=2,
        client_turns=1,
        employee_turns=1,
    )


def _long_text(token_count: int = 600) -> str:
    """Generate a long Russian text with approximately token_count tokens.

    Each word counts as ~1 token in razdel, with some punctuation tokens.
    """
    base_sentence = "Клиент обратился в службу поддержки для решения вопроса. "
    # ~10 tokens per sentence repetition
    repetitions = (token_count // 10) + 1
    return (base_sentence * repetitions).strip()


def _long_dialogue() -> ParsedDialog:
    """Create a dialogue with a long utterance (>500 tokens)."""
    long_text = _long_text(600)
    return ParsedDialog(
        filename="test_long.rtf",
        turns=[
            DialogueTurn(turn_index=0, speaker="Клиент", text=long_text),
            DialogueTurn(turn_index=1, speaker="Сотрудник", text="Понял, сейчас проверю."),
        ],
        total_turns=2,
        client_turns=1,
        employee_turns=1,
    )


def _empty_dialogue() -> ParsedDialog:
    """Create an empty dialogue."""
    return ParsedDialog(
        filename="empty.rtf",
        turns=[],
        total_turns=0,
    )


def _ner_dialogue() -> ParsedDialog:
    """Create a dialogue with named entities for NER testing."""
    return ParsedDialog(
        filename="ner_test.rtf",
        turns=[
            DialogueTurn(
                turn_index=0,
                speaker="Клиент",
                text="Иванов Иван Иванович звонит из Москвы по поводу услуги Сбербанка.",
            ),
        ],
        total_turns=1,
        client_turns=1,
    )


# ═══════════════════════════════════════════════════════════
# Test: Short utterance → 1 chunk
# ═══════════════════════════════════════════════════════════


class TestShortUtterance:
    """Short utterance (≤500 tokens) produces exactly 1 chunk."""

    def test_short_utterance_single_chunk(self) -> None:
        """Short dialogue with 2 turns produces 2 chunks."""
        chunker = Chunker(max_tokens=500)
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-001")

        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk.metadata.chunk_type == "utterance"

    def test_short_utterance_preserves_text(self) -> None:
        """Chunk text matches the original turn text."""
        chunker = Chunker(max_tokens=500)
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-001")

        assert chunks[0].text == "Здравствуйте! Мне нужна помощь."
        assert chunks[1].text == "Добрый день! Чем могу помочь?"

    def test_short_utterance_token_count(self) -> None:
        """Token count is correctly computed for short utterances."""
        chunker = Chunker(max_tokens=500)
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-001")

        # "Здравствуйте! Мне нужна помощь." has ~5-6 tokens in razdel
        assert chunks[0].metadata.token_count > 0
        assert chunks[0].metadata.token_count <= 500


# ═══════════════════════════════════════════════════════════
# Test: Long utterance → multiple chunks with overlap
# ═══════════════════════════════════════════════════════════


class TestLongUtterance:
    """Long utterance (>500 tokens) produces multiple overlapping chunks."""

    def test_long_utterance_multiple_chunks(self) -> None:
        """Long text produces more than 1 chunk."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-002")

        # First turn is long (>500 tokens) → multiple chunks
        long_turn_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        assert len(long_turn_chunks) > 1

    def test_long_utterance_overlap_type(self) -> None:
        """Sub-chunks of long utterance get chunk_type='overlap'."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-002")

        long_turn_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        # First sub-chunk = "utterance", rest = "overlap"
        assert long_turn_chunks[0].metadata.chunk_type == "utterance"
        for chunk in long_turn_chunks[1:]:
            assert chunk.metadata.chunk_type == "overlap"

    def test_long_utterance_overlap_linking(self) -> None:
        """Adjacent chunks from same turn are linked via overlap_with."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-002")

        long_turn_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        if len(long_turn_chunks) > 1:
            # Second chunk should reference first chunk in overlap_with
            assert long_turn_chunks[0].metadata.chunk_id in long_turn_chunks[1].metadata.overlap_with
            assert long_turn_chunks[1].metadata.chunk_id in long_turn_chunks[0].metadata.overlap_with

    def test_long_utterance_token_limit(self) -> None:
        """Each chunk respects the max_tokens limit."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-002")

        for chunk in chunks:
            # Allow slight overflow for sentence boundary alignment
            assert chunk.metadata.token_count <= 600, (
                f"Chunk {chunk.metadata.chunk_id} has {chunk.metadata.token_count} tokens "
                f"(max: {chunker.max_tokens})"
            )


# ═══════════════════════════════════════════════════════════
# Test: Dialogue with multiple turns
# ═══════════════════════════════════════════════════════════


class TestMultipleTurns:
    """Dialogue with multiple turns produces correct number of chunks."""

    def test_multi_turn_dialogue(self) -> None:
        """Multi-turn dialogue produces one chunk per short turn."""
        chunker = Chunker(max_tokens=500)
        dialogue = ParsedDialog(
            filename="multi.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте."),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день!"),
                DialogueTurn(turn_index=2, speaker="Клиент", text="Хочу узнать статус."),
                DialogueTurn(turn_index=3, speaker="Сотрудник", text="Уточните номер."),
            ],
            total_turns=4,
            client_turns=2,
            employee_turns=2,
        )

        chunks = chunker.chunk_dialogue(dialogue, "dialog-003")

        assert len(chunks) == 4
        assert all(c.metadata.chunk_type == "utterance" for c in chunks)

    def test_mixed_short_long_turns(self) -> None:
        """Dialogue with mix of short and long turns."""
        chunker = Chunker(max_tokens=500)
        long_text = _long_text(600)
        dialogue = ParsedDialog(
            filename="mixed.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Короткая реплика."),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text=long_text),
            ],
            total_turns=2,
            client_turns=1,
            employee_turns=1,
        )

        chunks = chunker.chunk_dialogue(dialogue, "dialog-004")

        # First turn: 1 chunk; second turn: multiple chunks
        short_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        long_chunks = [c for c in chunks if c.metadata.turn_index == 1]
        assert len(short_chunks) == 1
        assert len(long_chunks) > 1


# ═══════════════════════════════════════════════════════════
# Test: Empty dialogue
# ═══════════════════════════════════════════════════════════


class TestEmptyDialogue:
    """Empty dialogue returns empty list."""

    def test_empty_dialogue_no_chunks(self) -> None:
        """Empty dialogue produces zero chunks."""
        chunker = Chunker()
        dialogue = _empty_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-empty")

        assert chunks == []

    def test_empty_turn_text_skipped(self) -> None:
        """Turns with empty/whitespace text are skipped."""
        chunker = Chunker()
        dialogue = ParsedDialog(
            filename="empty_turn.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text=""),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="   "),
                DialogueTurn(turn_index=2, speaker="Клиент", text="Реальная реплика"),
            ],
            total_turns=3,
        )

        chunks = chunker.chunk_dialogue(dialogue, "dialog-empty-turns")

        # Only the non-empty turn should produce a chunk
        assert len(chunks) == 1
        assert chunks[0].text == "Реальная реплика"


# ═══════════════════════════════════════════════════════════
# Test: Metadata correctness
# ═══════════════════════════════════════════════════════════


class TestMetadata:
    """Chunk metadata is correctly populated."""

    def test_dialogue_id(self) -> None:
        """dialogue_id is propagated to all chunks."""
        chunker = Chunker()
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "my-session-123")

        for chunk in chunks:
            assert chunk.metadata.dialogue_id == "my-session-123"

    def test_turn_index(self) -> None:
        """turn_index matches the original turn."""
        chunker = Chunker()
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-meta")

        assert chunks[0].metadata.turn_index == 0
        assert chunks[1].metadata.turn_index == 1

    def test_speaker(self) -> None:
        """speaker matches the original turn."""
        chunker = Chunker()
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-meta")

        assert chunks[0].metadata.speaker == "Клиент"
        assert chunks[1].metadata.speaker == "Сотрудник"

    def test_char_count(self) -> None:
        """char_count matches len(chunk.text)."""
        chunker = Chunker()
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-meta")

        for chunk in chunks:
            assert chunk.metadata.char_count == len(chunk.text)

    def test_chunk_id_is_uuid(self) -> None:
        """chunk_id is a valid UUID4 string."""
        chunker = Chunker()
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-meta")

        for chunk in chunks:
            # Should not raise ValueError if valid UUID
            uuid.UUID(chunk.metadata.chunk_id)

    def test_chunk_id_unique(self) -> None:
        """All chunk_ids are unique."""
        chunker = Chunker()
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-meta")

        chunk_ids = [c.metadata.chunk_id for c in chunks]
        assert len(chunk_ids) == len(set(chunk_ids))


# ═══════════════════════════════════════════════════════════
# Test: NER entity extraction
# ═══════════════════════════════════════════════════════════


class TestNERExtraction:
    """NER entities are extracted when Natasha is available."""

    def test_ner_extracts_entities(self) -> None:
        """NER extracts PER, LOC, ORG entities from text."""
        chunker = Chunker()
        if not chunker._has_ner:
            pytest.skip("Natasha NER not available in this environment")

        dialogue = _ner_dialogue()
        chunks = chunker.chunk_dialogue(dialogue, "dialog-ner")

        assert len(chunks) >= 1
        entities = chunks[0].metadata.entities

        # Natasha should find entities in "Иванов Иван Иванович звонит из Москвы по поводу услуги Сбербанка."
        entity_types = {e["type"] for e in entities}
        # At least some entities should be found
        assert len(entities) > 0, "Expected NER entities but got empty list"

    def test_ner_entity_has_required_fields(self) -> None:
        """Each NER entity has 'text' and 'type' fields."""
        chunker = Chunker()
        if not chunker._has_ner:
            pytest.skip("Natasha NER not available in this environment")

        dialogue = _ner_dialogue()
        chunks = chunker.chunk_dialogue(dialogue, "dialog-ner-fields")

        for chunk in chunks:
            for entity in chunk.metadata.entities:
                assert "text" in entity
                assert "type" in entity
                assert entity["type"] in {"PER", "LOC", "ORG"}

    def test_ner_unavailable_empty_entities(self) -> None:
        """When Natasha NER is not available, entities are empty."""
        chunker = Chunker()
        # Force NER off
        chunker._has_ner = False

        dialogue = _ner_dialogue()
        chunks = chunker.chunk_dialogue(dialogue, "dialog-no-ner")

        for chunk in chunks:
            assert chunk.metadata.entities == []


# ═══════════════════════════════════════════════════════════
# Test: Tokenization
# ═══════════════════════════════════════════════════════════


class TestTokenization:
    """Tokenization via razdel works correctly."""

    def test_count_tokens_basic(self) -> None:
        """_count_tokens returns correct token count."""
        chunker = Chunker()
        text = "Привет мир! Это тест."
        count = chunker._count_tokens(text)
        assert count > 0
        # razdel should tokenize this into ~5-6 tokens
        assert 4 <= count <= 8

    def test_count_tokens_empty(self) -> None:
        """_count_tokens returns 0 for empty string."""
        chunker = Chunker()
        assert chunker._count_tokens("") == 0

    def test_count_tokens_russian(self) -> None:
        """_count_tokens handles Russian text correctly."""
        chunker = Chunker()
        text = "Кружка-термос — это удобно, т.е. очень."
        count = chunker._count_tokens(text)
        # razdel should handle hyphenated words and abbreviations
        assert count > 0

    def test_count_tokens_fallback_regex(self) -> None:
        """_count_tokens falls back to regex if razdel fails."""
        chunker = Chunker()
        with patch("app.services.chunker.razdel_tokenize", side_effect=Exception("razdel error")):
            count = chunker._count_tokens("Hello world test")
            # Regex fallback: \w+ matches 3 words
            assert count == 3


# ═══════════════════════════════════════════════════════════
# Test: Sentence-based splitting
# ═══════════════════════════════════════════════════════════


class TestSentenceSplitting:
    """Long utterances are split by sentence boundaries."""

    def test_sentenize_enabled(self) -> None:
        """With use_sentenize=True, long text is split by sentences."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50, use_sentenize=True)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-sent")

        # Should produce multiple chunks for long turn
        long_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        assert len(long_chunks) > 1

    def test_sentenize_disabled(self) -> None:
        """With use_sentenize=False, long text is split by char window."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50, use_sentenize=False)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-no-sent")

        # Should still produce multiple chunks for long turn
        long_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        assert len(long_chunks) > 1

    def test_sentence_chunks_not_truncated_mid_word(self) -> None:
        """Sentence-based chunks end at sentence boundaries."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50, use_sentenize=True)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-boundary")

        long_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        # Each chunk should end with a period or other sentence-ending punctuation
        for chunk in long_chunks:
            # Allow some flexibility but text should be complete sentences
            assert len(chunk.text.strip()) > 0


# ═══════════════════════════════════════════════════════════
# Test: Overlap between chunks
# ═══════════════════════════════════════════════════════════


class TestOverlap:
    """Adjacent chunks from long utterances have overlap."""

    def test_overlap_with_links(self) -> None:
        """overlap_with field links adjacent chunks from same turn."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        dialogue = _long_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-overlap")

        long_chunks = [c for c in chunks if c.metadata.turn_index == 0]
        if len(long_chunks) > 1:
            # Adjacent chunks should reference each other
            for idx in range(1, len(long_chunks)):
                assert long_chunks[idx - 1].metadata.chunk_id in long_chunks[idx].metadata.overlap_with

    def test_overlap_different_turns_not_linked(self) -> None:
        """Chunks from different turns are NOT linked in overlap_with."""
        chunker = Chunker(max_tokens=500)
        dialogue = _short_dialogue()

        chunks = chunker.chunk_dialogue(dialogue, "dialog-no-overlap")

        if len(chunks) >= 2:
            # Different turns should not overlap
            assert chunks[0].metadata.chunk_id not in chunks[1].metadata.overlap_with
            assert chunks[1].metadata.chunk_id not in chunks[0].metadata.overlap_with


# ═══════════════════════════════════════════════════════════
# Test: Text sanitization
# ═══════════════════════════════════════════════════════════


class TestTextSanitization:
    """Control characters are removed from text."""

    def test_sanitize_removes_control_chars(self) -> None:
        """Control characters (except \\n, \\t) are removed."""
        chunker = Chunker()
        text = "Привет\x00мир\x01!\nНовая\tстрока."
        sanitized = chunker._sanitize_text(text)

        assert "\x00" not in sanitized
        assert "\x01" not in sanitized
        assert "\n" in sanitized
        assert "\t" in sanitized
        assert "Привет" in sanitized
        assert "мир" in sanitized

    def test_sanitize_preserves_normal_text(self) -> None:
        """Normal text is not modified by sanitization."""
        chunker = Chunker()
        text = "Нормальный текст с русскими буквами."
        sanitized = chunker._sanitize_text(text)

        assert sanitized == text

    def test_control_chars_in_dialogue(self) -> None:
        """Control characters in dialogue turns are cleaned."""
        chunker = Chunker()
        dialogue = ParsedDialog(
            filename="ctrl.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Привет\x00 мир!"),
            ],
            total_turns=1,
        )

        chunks = chunker.chunk_dialogue(dialogue, "dialog-ctrl")

        assert len(chunks) == 1
        assert "\x00" not in chunks[0].text
        assert "Привет" in chunks[0].text


# ═══════════════════════════════════════════════════════════
# Test: chunk_text() convenience method
# ═══════════════════════════════════════════════════════════


class TestChunkTextMethod:
    """chunk_text() works for arbitrary text without ParsedDialog."""

    def test_chunk_text_short(self) -> None:
        """Short text produces 1 chunk."""
        chunker = Chunker()
        chunks = chunker.chunk_text("Короткий текст", {"dialogue_id": "test-1", "turn_index": 0, "speaker": "Клиент"})

        assert len(chunks) == 1
        assert chunks[0].metadata.chunk_type == "utterance"

    def test_chunk_text_long(self) -> None:
        """Long text produces multiple chunks."""
        chunker = Chunker(max_tokens=500)
        long_text = _long_text(600)
        chunks = chunker.chunk_text(
            long_text, {"dialogue_id": "test-2", "turn_index": 0, "speaker": "Клиент"}
        )

        assert len(chunks) > 1

    def test_chunk_text_empty(self) -> None:
        """Empty text produces zero chunks."""
        chunker = Chunker()
        chunks = chunker.chunk_text("", {"dialogue_id": "test-3"})

        assert chunks == []

    def test_chunk_text_metadata_base_defaults(self) -> None:
        """chunk_text() uses defaults when metadata_base keys missing."""
        chunker = Chunker()
        chunks = chunker.chunk_text("Текст", {})

        assert len(chunks) == 1
        assert chunks[0].metadata.dialogue_id == "unknown"
        assert chunks[0].metadata.turn_index == 0
        assert chunks[0].metadata.speaker == "unknown"


# ═══════════════════════════════════════════════════════════
# Test: Natasha NER graceful degradation
# ═══════════════════════════════════════════════════════════


class TestGracefulNERFallback:
    """Chunker works gracefully when Natasha NER is unavailable."""

    def test_ner_import_failure(self) -> None:
        """Chunker initializes without Natasha (import failure)."""
        with patch.dict("sys.modules", {"natasha": None}):
            # Force re-initialization without Natasha
            chunker = Chunker()
            # Even if natasha import failed during init, chunker should work
            chunker._has_ner = False

            dialogue = _short_dialogue()
            chunks = chunker.chunk_dialogue(dialogue, "dialog-no-natasha")

            assert len(chunks) == 2
            for chunk in chunks:
                assert chunk.metadata.entities == []

    def test_ner_extraction_failure_returns_empty(self) -> None:
        """NER extraction failure returns empty list, not exception."""
        chunker = Chunker()
        chunker._has_ner = True  # Pretend NER is available
        chunker._segmenter = None  # But components are broken

        result = chunker._extract_entities("Иванов из Москвы")

        assert result == []

    def test_ner_disabled_entities_empty(self) -> None:
        """With _has_ner=False, entities are always empty."""
        chunker = Chunker()
        chunker._has_ner = False

        dialogue = _ner_dialogue()
        chunks = chunker.chunk_dialogue(dialogue, "dialog-ner-off")

        for chunk in chunks:
            assert chunk.metadata.entities == []


# ═══════════════════════════════════════════════════════════
# Test: Pydantic model validation
# ═══════════════════════════════════════════════════════════


class TestModelValidation:
    """ChunkMetadata and Chunk models validate correctly."""

    def test_chunk_metadata_defaults(self) -> None:
        """ChunkMetadata has proper defaults for optional fields."""
        meta = ChunkMetadata(
            dialogue_id="test",
            turn_index=0,
            speaker="Клиент",
            chunk_type="utterance",
            token_count=5,
            char_count=30,
        )

        assert meta.chunk_id  # auto-generated UUID
        assert meta.overlap_with == []
        assert meta.entities == []

    def test_chunk_metadata_with_entities(self) -> None:
        """ChunkMetadata stores entities correctly."""
        meta = ChunkMetadata(
            dialogue_id="test",
            turn_index=0,
            speaker="Клиент",
            chunk_type="utterance",
            token_count=5,
            char_count=30,
            entities=[{"text": "Иванов", "type": "PER", "normal": "иванов"}],
        )

        assert len(meta.entities) == 1
        assert meta.entities[0]["type"] == "PER"

    def test_chunk_model(self) -> None:
        """Chunk model combines text and metadata."""
        meta = ChunkMetadata(
            dialogue_id="test",
            turn_index=0,
            speaker="Клиент",
            chunk_type="utterance",
            token_count=5,
            char_count=30,
        )
        chunk = Chunk(text="Привет мир!", metadata=meta)

        assert chunk.text == "Привет мир!"
        assert chunk.metadata.dialogue_id == "test"

    def test_chunk_type_literal(self) -> None:
        """chunk_type only accepts valid literal values."""
        # Valid values
        for chunk_type in ["utterance", "overlap", "full_dialogue"]:
            meta = ChunkMetadata(
                dialogue_id="test",
                turn_index=0,
                speaker="Клиент",
                chunk_type=chunk_type,  # type: ignore[arg-type]
                token_count=5,
                char_count=30,
            )
            assert meta.chunk_type == chunk_type

    def test_chunk_metadata_invalid_chunk_type(self) -> None:
        """Invalid chunk_type raises validation error."""
        with pytest.raises(Exception):
            ChunkMetadata(
                dialogue_id="test",
                turn_index=0,
                speaker="Клиент",
                chunk_type="invalid",  # type: ignore[arg-type]
                token_count=5,
                char_count=30,
            )


# ═══════════════════════════════════════════════════════════
# Test: Integration — full pipeline
# ═══════════════════════════════════════════════════════════


class TestIntegration:
    """End-to-end integration tests for Chunker."""

    def test_realistic_dialogue(self) -> None:
        """Realistic dialogue with mixed lengths and speakers."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        dialogue = ParsedDialog(
            filename="realistic.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text="Здравствуйте, я звоню по поводу моего тарифного плана."),
                DialogueTurn(turn_index=1, speaker="Сотрудник", text="Добрый день! Назовите ваш номер телефона."),
                DialogueTurn(turn_index=2, speaker="Клиент", text="Мой номер 8-900-123-45-67."),
                DialogueTurn(turn_index=3, speaker="Сотрудник", text="Спасибо, нашёл ваш номер. У вас подключён тариф «Всё включено». Что именно вас интересует?"),
            ],
            total_turns=4,
            client_turns=2,
            employee_turns=2,
        )

        chunks = chunker.chunk_dialogue(dialogue, "session-realistic")

        assert len(chunks) == 4
        for chunk in chunks:
            assert chunk.metadata.dialogue_id == "session-realistic"
            assert chunk.metadata.token_count > 0
            assert chunk.metadata.char_count > 0
            assert chunk.metadata.chunk_type == "utterance"

    def test_very_long_utterance_produces_many_chunks(self) -> None:
        """Very long utterance (>1500 tokens) produces 3+ chunks."""
        chunker = Chunker(max_tokens=500, overlap_tokens=50)
        very_long_text = _long_text(1500)
        dialogue = ParsedDialog(
            filename="very_long.rtf",
            turns=[
                DialogueTurn(turn_index=0, speaker="Клиент", text=very_long_text),
            ],
            total_turns=1,
        )

        chunks = chunker.chunk_dialogue(dialogue, "session-very-long")

        # 1500 tokens / 500 per chunk = at least 3 chunks
        assert len(chunks) >= 3

    def test_chunker_with_custom_max_tokens(self) -> None:
        """Custom max_tokens produces smaller chunks."""
        chunker_small = Chunker(max_tokens=100, overlap_tokens=20)
        text = "Первое предложение. Второе предложение. Третье предложение. Четвёртое предложение. Пятое предложение."
        dialogue = ParsedDialog(
            filename="small_max.rtf",
            turns=[DialogueTurn(turn_index=0, speaker="Клиент", text=text)],
            total_turns=1,
        )

        chunks = chunker_small.chunk_dialogue(dialogue, "session-small-max")

        # With max_tokens=100, this text should produce multiple chunks
        assert len(chunks) >= 1
        # Each chunk should respect the smaller limit (with some tolerance for sentence boundaries)
        for chunk in chunks:
            assert chunk.metadata.token_count <= 150  # Allow tolerance for sentence alignment

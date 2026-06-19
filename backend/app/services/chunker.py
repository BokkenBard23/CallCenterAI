"""Chunker service for FRIDA embeddings.

Splits dialogue text into chunks (300-500 tokens) with overlap for
vectorization via FRIDA embeddings.

Features:
  - razdel.tokenize for Russian-optimized tokenization (9 errors/1K tokens)
  - razdel.sentenize for sentence-level splitting of long utterances
  - Natasha NER for entity extraction (PER, LOC, ORG) into ChunkMetadata.entities
  - Sliding window: max 500 tokens per chunk, 50-token overlap between chunks
  - Graceful fallback when Natasha is not available (empty entities, warning log)
  - Text sanitization (control character removal)

Strategy:
  1. Short turn (<= max_tokens) → chunk_type="utterance" (1 turn = 1 chunk)
  2. Long turn (> max_tokens) → split into overlapping chunks (overlap 50 tokens)
     - razdel.sentenize for sentence boundaries
     - Sliding window: next chunk starts overlap_tokens before end of previous
     - chunk_type="overlap" for all sub-chunks after the first
  3. Empty dialogue → empty list

API contract:
  chunk_dialogue(dialogue: ParsedDialog, dialogue_id: str) -> List[Chunk]
  chunk_text(text: str, metadata_base: dict) -> List[Chunk]
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Dict, List, Optional

from razdel import sentenize as razdel_sentenize
from razdel import tokenize as razdel_tokenize

from app.models import Chunk, ChunkMetadata, ParsedDialog

logger = logging.getLogger(__name__)

# Default configuration constants
_DEFAULT_MAX_TOKENS = 500
_DEFAULT_OVERLAP_TOKENS = 50
_DEFAULT_USE_SENTENIZE = True


class Chunker:
    """Splits dialogues into chunks for FRIDA embeddings.

    Uses razdel for Russian tokenization and sentence splitting,
    Natasha NER for entity extraction, and sliding window with
    configurable overlap for long utterances.

    Attributes:
        max_tokens: Maximum tokens per chunk (default 500).
        overlap_tokens: Overlap between adjacent chunks (default 50).
        use_sentenize: Whether to use razdel.sentenize for sentence boundaries.
        _has_ner: Whether Natasha NER is available.
    """

    def __init__(
        self,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        overlap_tokens: int = _DEFAULT_OVERLAP_TOKENS,
        use_sentenize: bool = _DEFAULT_USE_SENTENIZE,
    ) -> None:
        """Initialize Chunker.

        Args:
            max_tokens: Maximum number of tokens per chunk.
            overlap_tokens: Number of tokens overlap between adjacent chunks.
            use_sentenize: Whether to use razdel.sentenize for sentence boundaries.
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.use_sentenize = use_sentenize

        # Natasha NER components (lazy initialization)
        self._segmenter: Optional[object] = None
        self._ner_tagger: Optional[object] = None
        self._morph_vocab: Optional[object] = None
        self._has_ner = False

        self._init_natasha_ner()

    def _init_natasha_ner(self) -> None:
        """Initialize Natasha NER components.

        Sets _has_ner to True on success, False on failure.
        Failure is non-fatal: chunker works without NER (empty entities).
        """
        try:
            from natasha import MorphVocab, NewsEmbedding, NewsNERTagger, Segmenter

            self._segmenter = Segmenter()
            emb = NewsEmbedding()
            self._ner_tagger = NewsNERTagger(emb)
            self._morph_vocab = MorphVocab()
            self._has_ner = True
            logger.info("Natasha NER initialized successfully")
        except Exception as exc:
            self._has_ner = False
            self._segmenter = None
            self._ner_tagger = None
            self._morph_vocab = None
            logger.warning("Natasha NER not available: %s. Entities will be empty.", exc)

    # ── Text sanitization ──────────────────────────────────────

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Sanitize text: remove control characters.

        Removes control characters (except \\n and \\t) to ensure
        clean text for tokenization and NER.

        Args:
            text: Input text to sanitize.

        Returns:
            Sanitized text with control characters removed.
        """
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # ── Token counting ────────────────────────────────────────

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using razdel.tokenize.

        Uses razdel as the primary tokenizer (best Russian quality:
        9 errors per 1000 tokens vs 24 for regex).

        Fallback chain: razdel → regex (if razdel fails).

        Args:
            text: Text to count tokens in.

        Returns:
            Number of tokens in the text.
        """
        try:
            return len(list(razdel_tokenize(text)))
        except Exception as exc:
            logger.warning("razdel.tokenize failed, falling back to regex: %s", exc)
            # Regex fallback: split on word boundaries
            return len(re.findall(r"\w+", text))

    # ── Entity extraction ──────────────────────────────────────

    def _extract_entities(self, text: str) -> List[Dict[str, str]]:
        """Extract named entities using Natasha NER.

        Extracts PER (person), LOC (location), ORG (organization) entities.
        Returns empty list if Natasha NER is not available or fails.

        Args:
            text: Text to extract entities from.

        Returns:
            List of entity dicts with keys: text, type, normal.
            Example: [{"text": "Иванов", "type": "PER", "normal": "иванов"}]
        """
        if not self._has_ner:
            return []

        try:
            from natasha import Doc

            doc = Doc(text)
            doc.segment(self._segmenter)  # type: ignore[arg-type]
            doc.tag_ner(self._ner_tagger)  # type: ignore[arg-type]

            entities: List[Dict[str, str]] = []
            for span in doc.spans:
                # Normalize entity (lemmatize)
                if self._morph_vocab is not None:
                    try:
                        span.normalize(self._morph_vocab)  # type: ignore[arg-type]
                    except Exception:
                        pass  # Non-fatal: normalization is best-effort

                entity: Dict[str, str] = {
                    "text": span.text,
                    "type": span.type,  # PER, LOC, ORG
                }
                # Add normalized form if available
                if hasattr(span, "normal") and span.normal:
                    entity["normal"] = span.normal

                entities.append(entity)

            return entities
        except Exception as exc:
            logger.warning("NER extraction failed: %s", exc)
            return []

    # ── Main API: chunk_dialogue ──────────────────────────────

    def chunk_dialogue(self, dialogue: ParsedDialog, dialogue_id: str) -> List[Chunk]:
        """Split entire dialogue into chunks.

        Each turn is processed independently:
          - Short turn (<= max_tokens) → 1 chunk with type="utterance"
          - Long turn (> max_tokens) → multiple chunks with overlap

        Args:
            dialogue: Parsed dialogue with turns.
            dialogue_id: Unique identifier for the dialogue (session_id).

        Returns:
            List of Chunk objects with metadata and NER entities.
        """
        if not dialogue.turns:
            return []

        chunks: List[Chunk] = []

        for turn_index, turn in enumerate(dialogue.turns):
            text = self._sanitize_text(turn.text)
            speaker = turn.speaker

            if not text.strip():
                continue

            token_count = self._count_tokens(text)

            if token_count <= self.max_tokens:
                # Short turn → single chunk
                chunk = Chunk(
                    text=text,
                    metadata=ChunkMetadata(
                        dialogue_id=dialogue_id,
                        turn_index=turn_index,
                        speaker=speaker,
                        chunk_type="utterance",
                        token_count=token_count,
                        char_count=len(text),
                        entities=self._extract_entities(text),
                    ),
                )
                chunks.append(chunk)
            else:
                # Long turn → split with overlap
                sub_chunks = self._chunk_long_text(
                    text=text,
                    dialogue_id=dialogue_id,
                    turn_index=turn_index,
                    speaker=speaker,
                )
                chunks.extend(sub_chunks)

        # Set overlap_with: link adjacent chunks from same turn
        self._compute_overlap_links(chunks)

        return chunks

    # ── Long text splitting ───────────────────────────────────

    def _chunk_long_text(
        self,
        text: str,
        dialogue_id: str,
        turn_index: int,
        speaker: str,
    ) -> List[Chunk]:
        """Split long text into overlapping chunks using sentence boundaries.

        Strategy:
          1. Use razdel.sentenize to split text into sentences
          2. Accumulate sentences until max_tokens is reached
          3. Start next chunk from overlap_tokens before the end
          4. All sub-chunks after the first get chunk_type="overlap"

        Args:
            text: Long text to split.
            dialogue_id: Dialogue identifier.
            turn_index: Turn index in the dialogue.
            speaker: Speaker role.

        Returns:
            List of overlapping Chunk objects.
        """
        chunks: List[Chunk] = []

        if self.use_sentenize:
            chunks = self._chunk_by_sentences(text, dialogue_id, turn_index, speaker)
        else:
            chunks = self._chunk_by_char_window(text, dialogue_id, turn_index, speaker)

        # Set chunk_type: first = "utterance", rest = "overlap"
        for idx, chunk in enumerate(chunks):
            if idx > 0:
                chunk.metadata.chunk_type = "overlap"

        return chunks

    def _chunk_by_sentences(
        self,
        text: str,
        dialogue_id: str,
        turn_index: int,
        speaker: str,
    ) -> List[Chunk]:
        """Split text by sentence boundaries with overlap.

        Uses razdel.sentenize for Russian-optimized sentence splitting
        (52 errors vs 92 for NLTK on standard benchmarks).

        Args:
            text: Text to split.
            dialogue_id: Dialogue identifier.
            turn_index: Turn index.
            speaker: Speaker role.

        Returns:
            List of Chunk objects with sentence-aligned boundaries.
        """
        sentences = list(razdel_sentenize(text))

        if not sentences:
            # Fallback to char-based window if sentenize returns nothing
            return self._chunk_by_char_window(text, dialogue_id, turn_index, speaker)

        chunks: List[Chunk] = []
        current_sentences: List[str] = []
        current_tokens = 0
        chunk_index = 0

        for sent in sentences:
            sent_text = sent.text
            sent_tokens = self._count_tokens(sent_text)

            # If adding this sentence exceeds max, emit current chunk
            if current_tokens + sent_tokens > self.max_tokens and current_sentences:
                chunk_text = " ".join(current_sentences)
                chunk = Chunk(
                    text=chunk_text,
                    metadata=ChunkMetadata(
                        dialogue_id=dialogue_id,
                        turn_index=turn_index,
                        speaker=speaker,
                        chunk_type="utterance" if chunk_index == 0 else "overlap",
                        token_count=self._count_tokens(chunk_text),
                        char_count=len(chunk_text),
                        entities=self._extract_entities(chunk_text),
                    ),
                )
                chunks.append(chunk)
                chunk_index += 1

                # Overlap: keep last few sentences for next chunk
                overlap_sentences: List[str] = []
                overlap_tokens = 0
                for prev_sent in reversed(current_sentences):
                    prev_tokens = self._count_tokens(prev_sent)
                    if overlap_tokens + prev_tokens > self.overlap_tokens:
                        break
                    overlap_sentences.insert(0, prev_sent)
                    overlap_tokens += prev_tokens

                current_sentences = overlap_sentences
                current_tokens = overlap_tokens

            current_sentences.append(sent_text)
            current_tokens += sent_tokens

        # Emit remaining sentences as last chunk
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            chunk = Chunk(
                text=chunk_text,
                metadata=ChunkMetadata(
                    dialogue_id=dialogue_id,
                    turn_index=turn_index,
                    speaker=speaker,
                    chunk_type="utterance" if chunk_index == 0 else "overlap",
                    token_count=self._count_tokens(chunk_text),
                    char_count=len(chunk_text),
                    entities=self._extract_entities(chunk_text),
                ),
            )
            chunks.append(chunk)

        return chunks

    def _chunk_by_char_window(
        self,
        text: str,
        dialogue_id: str,
        turn_index: int,
        speaker: str,
    ) -> List[Chunk]:
        """Split text by character window with token-based overlap.

        Fallback when sentenize is disabled. Uses a character window
        (~4 chars/token heuristic) with token-based overlap.

        Args:
            text: Text to split.
            dialogue_id: Dialogue identifier.
            turn_index: Turn index.
            speaker: Speaker role.

        Returns:
            List of Chunk objects with sliding window boundaries.
        """
        chunks: List[Chunk] = []
        # Approximate chars per token for Russian text
        chars_per_token = 4
        window_chars = self.max_tokens * chars_per_token
        overlap_chars = self.overlap_tokens * chars_per_token

        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + window_chars, len(text))
            chunk_text = text[start:end].strip()

            if not chunk_text:
                break

            # Verify token count and shrink if needed
            token_count = self._count_tokens(chunk_text)
            if token_count > self.max_tokens and end < len(text):
                # Step back to find a safe boundary
                while (
                    end > start + overlap_chars
                    and self._count_tokens(text[start:end]) > self.max_tokens
                ):
                    end -= chars_per_token
                chunk_text = text[start:end].strip()
                token_count = self._count_tokens(chunk_text)

            chunk = Chunk(
                text=chunk_text,
                metadata=ChunkMetadata(
                    dialogue_id=dialogue_id,
                    turn_index=turn_index,
                    speaker=speaker,
                    chunk_type="utterance" if chunk_index == 0 else "overlap",
                    token_count=token_count,
                    char_count=len(chunk_text),
                    entities=self._extract_entities(chunk_text),
                ),
            )
            chunks.append(chunk)

            # Move forward with overlap
            step = max(end - start - overlap_chars, chars_per_token)
            start += step
            chunk_index += 1

            # Safety: avoid infinite loop
            if start >= end:
                start = end

        return chunks

    # ── Public API: chunk_text ────────────────────────────────

    def chunk_text(self, text: str, metadata_base: Dict[str, object]) -> List[Chunk]:
        """Split arbitrary text into chunks.

        Convenience method for chunking text without a full ParsedDialog.
        Delegates to _chunk_long_text if text exceeds max_tokens,
        otherwise returns a single chunk.

        Args:
            text: Text to split into chunks.
            metadata_base: Dict with keys: dialogue_id, turn_index, speaker.

        Returns:
            List of Chunk objects.
        """
        text = self._sanitize_text(text)

        if not text.strip():
            return []

        token_count = self._count_tokens(text)

        if token_count <= self.max_tokens:
            chunk = Chunk(
                text=text,
                metadata=ChunkMetadata(
                    dialogue_id=str(metadata_base.get("dialogue_id", "unknown")),
                    turn_index=int(metadata_base.get("turn_index", 0)),
                    speaker=str(metadata_base.get("speaker", "unknown")),
                    chunk_type="utterance",
                    token_count=token_count,
                    char_count=len(text),
                    entities=self._extract_entities(text),
                ),
            )
            return [chunk]

        return self._chunk_long_text(
            text=text,
            dialogue_id=str(metadata_base.get("dialogue_id", "unknown")),
            turn_index=int(metadata_base.get("turn_index", 0)),
            speaker=str(metadata_base.get("speaker", "unknown")),
        )

    # ── Overlap linking ──────────────────────────────────────

    def _compute_overlap_links(self, chunks: List[Chunk]) -> None:
        """Set overlap_with field for adjacent chunks from same turn.

        Chunks from the same turn that are adjacent in the list
        are linked via their chunk_id in overlap_with.

        Args:
            chunks: List of chunks to link.
        """
        for idx in range(1, len(chunks)):
            prev = chunks[idx - 1]
            curr = chunks[idx]

            # Link only chunks from same dialogue+turn
            if (
                prev.metadata.dialogue_id == curr.metadata.dialogue_id
                and prev.metadata.turn_index == curr.metadata.turn_index
            ):
                curr.metadata.overlap_with.append(prev.metadata.chunk_id)
                prev.metadata.overlap_with.append(curr.metadata.chunk_id)

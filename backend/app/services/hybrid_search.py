"""Hybrid search service: morphological + semantic + NER boost via RRF.

Combines three search signals through Reciprocal Rank Fusion (RRF):
  1. Morphological search (pymorphy3) via existing search.py — precision
  2. Semantic search (FRIDA embeddings + FAISS) via VectorStore — relevance
  3. NER boost (Natasha) — entity-based ranking adjustment

RRF Formula:
  score(doc) = Σ (1 / (rank_morph(doc) + k)) + Σ (1 / (rank_semantic(doc) + k))
  k = 60 (IR literature standard)

NER Boost:
  If query contains named entities (PER, LOC, ORG), chunks with matching
  entities receive a boost: ner_boost = boost_per_match × matched_count
  PER matches receive higher weight (ner_per_weight multiplier).

Graceful Degradation:
  1. FRIDA unavailable → morphological-only search, source="morph"
  2. Natasha NER unavailable → no NER boost, use_ner=False
  3. No dictionaries → semantic-only search, source="semantic"
  4. Empty query → []

API contract:
  search(query, dialogue, dictionaries, top_k, use_semantic, use_ner)
    → List[HybridSearchResult]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models import (
    DictionaryNode,
    DictMatch,
    HybridSearchResult,
    ParsedDialog,
    VectorSearchResult,
)
from app.services.embedding import FridaEmbeddingService
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Default configuration constants
_DEFAULT_RRF_K = 60
_DEFAULT_NER_BOOST_PER_MATCH = 0.1
_DEFAULT_NER_PER_WEIGHT = 1.5
_DEFAULT_TOP_K = 10


class HybridSearchService:
    """Гибридный поиск: морфология (точность) + семантика (релевантность) + NER (ранжирование).

    Reciprocal Rank Fusion (RRF):
        score(doc) = Σ (1 / (rank_morph(doc) + k)) + Σ (1 / (rank_semantic(doc) + k))
        k = 60 (default, IR literature standard)

    NER Boost: если query содержит сущности, чанки с теми же сущностями получают буст
    Fallback: если FRIDA недоступна → только морфологический поиск
    """

    def __init__(
        self,
        embedding_service: FridaEmbeddingService,
        vector_store: VectorStore,
        rrf_k: int = _DEFAULT_RRF_K,
        ner_boost_per_match: float = _DEFAULT_NER_BOOST_PER_MATCH,
        ner_per_weight: float = _DEFAULT_NER_PER_WEIGHT,
    ) -> None:
        """Initialize HybridSearchService.

        Args:
            embedding_service: FridaEmbeddingService for query embedding.
            vector_store: VectorStore for semantic search.
            rrf_k: RRF constant k (default 60, IR literature standard).
            ner_boost_per_match: NER boost per matched entity (default 0.1).
            ner_per_weight: PER entity weight multiplier (default 1.5).
        """
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.rrf_k = rrf_k
        self.ner_boost_per_match = ner_boost_per_match
        self.ner_per_weight = ner_per_weight

        # Natasha NER components (lazy initialization)
        self._segmenter: Optional[Any] = None
        self._ner_tagger: Optional[Any] = None
        self._morph_vocab: Optional[Any] = None
        self._has_ner: bool = False

        self._init_natasha_ner()

    def _init_natasha_ner(self) -> None:
        """Initialize Natasha NER components for query entity extraction.

        Sets _has_ner to True on success, False on failure.
        Failure is non-fatal: search works without NER (no boost).
        """
        try:
            from natasha import MorphVocab, NewsEmbedding, NewsNERTagger, Segmenter

            self._segmenter = Segmenter()
            emb = NewsEmbedding()
            self._ner_tagger = NewsNERTagger(emb)
            self._morph_vocab = MorphVocab()
            self._has_ner = True
            logger.info("HybridSearch: Natasha NER initialized successfully")
        except Exception as exc:
            self._has_ner = False
            self._segmenter = None
            self._ner_tagger = None
            self._morph_vocab = None
            logger.warning(
                "HybridSearch: Natasha NER not available: %s. NER boost disabled.", exc,
            )

    # ── Main API ─────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        dialogue: Optional[ParsedDialog] = None,
        dictionaries: Optional[List[DictionaryNode]] = None,
        top_k: int = _DEFAULT_TOP_K,
        use_semantic: bool = True,
        use_ner: bool = True,
    ) -> List[HybridSearchResult]:
        """Гибридный поиск.

        1. Морфологический поиск (если есть dictionaries и dialogue)
        2. Семантический поиск (если use_semantic и FRIDA доступна)
        3. NER-анализ query и чанков (если use_ner и NLP-сервис доступен)
        4. Объединение через RRF с NER-бустом
        5. Сортировка по combined_score

        Args:
            query: Поисковый запрос (для семантики и NER).
            dialogue: Диалог для морфологического поиска.
            dictionaries: Словари для морфологического поиска.
            top_k: Количество результатов.
            use_semantic: Использовать ли семантический поиск.
            use_ner: Использовать ли NER-ранжирование.

        Returns:
            Список HybridSearchResult, отсортированный по combined_score (desc).
        """
        # Validation: empty query
        if not query or not query.strip():
            return []

        # Clamp top_k to valid range
        if top_k < 1:
            top_k = 1
        if top_k > 100:
            top_k = 100

        # Determine search modes
        can_morph = dialogue is not None and dictionaries is not None and len(dictionaries) > 0
        can_semantic = use_semantic
        can_ner = use_ner and self._has_ner

        # Step 1: Morphological search
        morph_results: List[_MorphResult] = []
        if can_morph:
            morph_results = await self._morph_search(query, dialogue, dictionaries)

        # Step 2: Semantic search
        semantic_results: List[VectorSearchResult] = []
        if can_semantic:
            semantic_results = await self._semantic_search(query, top_k=top_k * 2)

        # Determine source label
        has_morph = len(morph_results) > 0
        has_semantic = len(semantic_results) > 0

        if has_morph and has_semantic:
            source = "hybrid"
        elif has_morph:
            source = "morph"
        elif has_semantic:
            source = "semantic"
        else:
            return []

        # Step 3: NER analysis
        query_entities: List[Dict[str, str]] = []
        if can_ner:
            query_entities = self._extract_query_entities(query)
            if not query_entities:
                can_ner = False

        # Step 4: RRF merge
        merged = self._reciprocal_rank_fusion(
            morph_results=morph_results,
            semantic_results=semantic_results,
        )

        # Step 5: Apply NER boost
        if can_ner and query_entities:
            merged = self._apply_ner_boost(merged, query_entities)
            # Update source if NER boost changed ranking
            if any(r.ner_boost > 0 for r in merged):
                if source == "hybrid":
                    source = "hybrid"

        # Set source label
        for result in merged:
            if result.ner_boost > 0 and result.source == "hybrid":
                result.source = "ner_boost" if result.ner_boost > 0 and not has_morph else source
            else:
                result.source = source

        # Sort by combined_score desc
        merged.sort(key=lambda r: r.combined_score, reverse=True)

        # Return top_k
        return merged[:top_k]

    # ── Morphological search ─────────────────────────────────────

    async def _morph_search(
        self,
        query: str,
        dialogue: ParsedDialog,
        dictionaries: List[DictionaryNode],
    ) -> List[_MorphResult]:
        """Run morphological search via existing search.py.

        Args:
            query: Search query (unused in morph, kept for API consistency).
            dialogue: Parsed dialogue to search in.
            dictionaries: Dictionary nodes with conditions.

        Returns:
            List of _MorphResult with turn_index, text, speaker, morph_match.
        """
        try:
            from app.services.search import run_hierarchical_search

            search_result = await run_hierarchical_search(
                dialog=dialogue,
                dictionaries=dictionaries,
            )

            # Convert DictMatch results to _MorphResult
            results: List[_MorphResult] = []
            seen_turns: Set[int] = set()

            for match in search_result.matches:
                if match.turn_index not in seen_turns:
                    # Find the turn text
                    turn_text = ""
                    for turn in dialogue.turns:
                        if turn.turn_index == match.turn_index:
                            turn_text = turn.text
                            break

                    results.append(
                        _MorphResult(
                            turn_index=match.turn_index,
                            text=turn_text,
                            speaker=match.speaker,
                            dialogue_id=dialogue.filename,
                            morph_match=match,
                        )
                    )
                    seen_turns.add(match.turn_index)

            return results

        except Exception as exc:
            logger.error("Morphological search failed: %s", exc, exc_info=True)
            return []

    # ── Semantic search ──────────────────────────────────────────

    async def _semantic_search(
        self,
        query: str,
        top_k: int = 20,
    ) -> List[VectorSearchResult]:
        """Run semantic search via FRIDA embeddings + VectorStore.

        Args:
            query: Search query to embed and search.
            top_k: Number of results to return.

        Returns:
            List of VectorSearchResult from VectorStore search.
        """
        try:
            # Check if FRIDA is available
            if not await self.embedding_service.is_available():
                logger.warning("FRIDA unavailable — skipping semantic search")
                return []

            # Embed query
            query_vector = await self.embedding_service.embed(query)

            # Search VectorStore
            results = self.vector_store.search(query_vector, k=top_k)

            return results

        except ConnectionError:
            logger.warning("FRIDA circuit breaker open — skipping semantic search")
            return []
        except Exception as exc:
            logger.error("Semantic search failed: %s", exc, exc_info=True)
            return []

    # ── NER: query entity extraction ────────────────────────────

    def _extract_query_entities(self, query: str) -> List[Dict[str, str]]:
        """Extract named entities from query using Natasha NER.

        Extracts PER (person), LOC (location), ORG (organization) entities.
        Returns empty list if Natasha NER is not available or fails.

        Args:
            query: Query text to extract entities from.

        Returns:
            List of entity dicts with keys: text, type, normal.
            Example: [{"text": "Иванов", "type": "PER", "normal": "иванов"}]
        """
        if not self._has_ner:
            return []

        try:
            from natasha import Doc

            doc = Doc(query)
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
                if hasattr(span, "normal") and span.normal:
                    entity["normal"] = span.normal

                entities.append(entity)

            if entities:
                logger.debug(
                    "Query NER: extracted %d entities from '%s'",
                    len(entities),
                    query[:50],
                )

            return entities

        except Exception as exc:
            logger.warning("Query NER extraction failed: %s", exc)
            return []

    # ── NER: boost computation ───────────────────────────────────

    def _compute_ner_boost(
        self,
        query_entities: List[Dict[str, str]],
        chunk_entities: List[Dict[str, str]],
    ) -> Tuple[float, List[str]]:
        """Compute NER boost for a chunk based on matching entities.

        Match logic:
          - Compare entity text (case-insensitive) or normal form
          - PER matches get ner_per_weight multiplier (1.5×)
          - Total boost = boost_per_match × weighted_match_count

        Args:
            query_entities: Entities extracted from the query.
            chunk_entities: Entities from chunk metadata.

        Returns:
            Tuple of (ner_boost, matched_entity_texts).
        """
        if not query_entities or not chunk_entities:
            return 0.0, []

        # Build lookup sets for chunk entities (text and normal)
        chunk_entity_lookup: Dict[str, str] = {}  # lowercase text/normal → type
        for entity in chunk_entities:
            text_lower = entity.get("text", "").lower()
            normal_lower = entity.get("normal", "").lower()
            entity_type = entity.get("type", "")
            if text_lower:
                chunk_entity_lookup[text_lower] = entity_type
            if normal_lower and normal_lower != text_lower:
                chunk_entity_lookup[normal_lower] = entity_type

        matched: List[str] = []
        weighted_count = 0.0

        for q_entity in query_entities:
            q_text_lower = q_entity.get("text", "").lower()
            q_normal_lower = q_entity.get("normal", "").lower()
            q_type = q_entity.get("type", "")

            # Check match against chunk entities
            matched_type: Optional[str] = None
            if q_text_lower and q_text_lower in chunk_entity_lookup:
                matched_type = chunk_entity_lookup[q_text_lower]
            elif q_normal_lower and q_normal_lower in chunk_entity_lookup:
                matched_type = chunk_entity_lookup[q_normal_lower]

            if matched_type is not None:
                matched.append(q_entity.get("text", ""))
                # PER entities get higher weight
                if q_type == "PER" or matched_type == "PER":
                    weighted_count += self.ner_per_weight
                else:
                    weighted_count += 1.0

        boost = self.ner_boost_per_match * weighted_count
        return boost, matched

    # ── RRF: Reciprocal Rank Fusion ──────────────────────────────

    def _reciprocal_rank_fusion(
        self,
        morph_results: List[_MorphResult],
        semantic_results: List[VectorSearchResult],
    ) -> List[HybridSearchResult]:
        """Combine morphological and semantic results via RRF.

        RRF Formula:
            score(doc) = Σ (1 / (rank_morph(doc) + k)) + Σ (1 / (rank_semantic(doc) + k))
            k = self.rrf_k (default 60)

        Each unique (dialogue_id, turn_index) pair is a document.
        Morphological results are ranked by their position in the match list.
        Semantic results are ranked by their position in the search results.

        Args:
            morph_results: Results from morphological search.
            semantic_results: Results from semantic search.

        Returns:
            List of HybridSearchResult with combined_score, sorted desc.
        """
        # Key: (dialogue_id, turn_index) → HybridSearchResult accumulator
        merged: Dict[Tuple[str, int], HybridSearchResult] = {}

        # Process morphological results — assign ranks
        for rank, morph in enumerate(morph_results, start=1):
            key = (morph.dialogue_id, morph.turn_index)
            rrf_contribution = 1.0 / (rank + self.rrf_k)

            if key in merged:
                merged[key].morph_score = 1.0
                merged[key].morph_match = morph.morph_match
                merged[key].combined_score += rrf_contribution
            else:
                merged[key] = HybridSearchResult(
                    text=morph.text,
                    dialogue_id=morph.dialogue_id,
                    turn_index=morph.turn_index,
                    speaker=morph.speaker,
                    morph_score=1.0,
                    morph_match=morph.morph_match,
                    combined_score=rrf_contribution,
                    source="morph",
                )

        # Process semantic results — assign ranks
        for rank, semantic in enumerate(semantic_results, start=1):
            key = (semantic.dialogue_id, semantic.turn_index)
            rrf_contribution = 1.0 / (rank + self.rrf_k)

            if key in merged:
                merged[key].semantic_score = semantic.score
                merged[key].combined_score += rrf_contribution
            else:
                merged[key] = HybridSearchResult(
                    text=semantic.text,
                    dialogue_id=semantic.dialogue_id,
                    turn_index=semantic.turn_index,
                    speaker=semantic.speaker,
                    semantic_score=semantic.score,
                    combined_score=rrf_contribution,
                    source="semantic",
                )

        return list(merged.values())

    # ── NER boost application ────────────────────────────────────

    def _apply_ner_boost(
        self,
        results: List[HybridSearchResult],
        query_entities: List[Dict[str, str]],
    ) -> List[HybridSearchResult]:
        """Apply NER boost to results based on matching entities.

        For each result, compare query entities with chunk entities.
        Results with matching entities receive a boost to combined_score.

        Args:
            results: Current search results from RRF.
            query_entities: Entities extracted from the query.

        Returns:
            Updated results with ner_boost and matched_entities populated.
        """
        for result in results:
            # Get chunk entities from VectorSearchResult or morph match
            # We need to look up chunk entities from the vector store
            chunk_entities = self._get_chunk_entities(result)

            boost, matched = self._compute_ner_boost(query_entities, chunk_entities)
            result.ner_boost = boost
            result.matched_entities = matched
            result.combined_score += boost

        return results

    def _get_chunk_entities(self, result: HybridSearchResult) -> List[Dict[str, str]]:
        """Get NER entities for a search result from VectorStore metadata.

        Searches the vector store metadata for a chunk matching the result's
        dialogue_id and turn_index, then returns its entities.

        Args:
            result: HybridSearchResult to look up entities for.

        Returns:
            List of entity dicts from chunk metadata.
        """
        # Look through vector store metadata for matching chunk
        for meta in self.vector_store._metadata:
            if (
                meta.get("dialogue_id") == result.dialogue_id
                and meta.get("turn_index") == result.turn_index
            ):
                return meta.get("entities", [])

        return []

    # ── Observability ────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics.

        Returns:
            Dictionary with configuration and NER availability.
        """
        return {
            "rrf_k": self.rrf_k,
            "ner_boost_per_match": self.ner_boost_per_match,
            "ner_per_weight": self.ner_per_weight,
            "ner_available": self._has_ner,
            "vector_store_total_vectors": self.vector_store.get_stats().get(
                "total_vectors", 0,
            ),
        }


# ── Internal helper class ────────────────────────────────────────


class _MorphResult:
    """Internal helper for morphological search results before RRF merge."""

    __slots__ = ("turn_index", "text", "speaker", "dialogue_id", "morph_match")

    def __init__(
        self,
        turn_index: int,
        text: str,
        speaker: str,
        dialogue_id: str,
        morph_match: Optional[DictMatch] = None,
    ) -> None:
        self.turn_index = turn_index
        self.text = text
        self.speaker = speaker
        self.dialogue_id = dialogue_id
        self.morph_match = morph_match

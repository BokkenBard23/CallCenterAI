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
    EnhancedHybridSearchResult,
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
# BM25 sparse scores can be unbounded; clamp to [0, 1] before LogOdds fusion.
_BM25_PROB_CLAMP_MAX = 10.0


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

    # ── Enhanced search (BM25 + advanced fusion + explainability) ──

    async def search_enhanced(
        self,
        query: str,
        dialogue: Optional[ParsedDialog] = None,
        dictionaries: Optional[List[DictionaryNode]] = None,
        top_k: int = _DEFAULT_TOP_K,
        use_semantic: bool = True,
        use_ner: bool = True,
        use_bm25: bool = True,
        fusion_strategy: str = "rrf",
        explain: bool = False,
    ) -> List[EnhancedHybridSearchResult]:
        """Enhanced hybrid search: morph + semantic + BM25 + advanced fusion.

        Adds a third sparse-retrieval channel (BM25 indexed over the session's
        chunk texts) and replaces the inline RRF with the ``app.services.fusion``
        dispatcher that supports RRF / Convex / LogOdds strategies. Optionally
        computes token-level explanations for the top results.

        Graceful degradation:
          - If BM25 indexing fails or the corpus is empty → falls back to the
            plain ``search()`` path (results wrapped in EnhancedHybridSearchResult
            with ``bm25_score=0``).
          - If ``explain=True`` but the embedding service is unavailable →
            ``token_contributions`` is left empty.
          - If any unexpected exception is raised → the call falls back to the
            plain ``search()`` path (matches the existing graceful-degradation
            pattern of this service).

        Args:
            query: Search query text.
            dialogue: Parsed dialogue (for morph search + BM25 corpus).
            dictionaries: Dictionaries for morphological search.
            top_k: Number of results to return.
            use_semantic: Whether to include FAISS cosine search.
            use_ner: Whether to include NER boost.
            use_bm25: Whether to build a BM25 index over the dialogue turns and
                fuse it as a third channel.
            fusion_strategy: One of "rrf" | "convex" | "log_odds".
            explain: If True, compute token-level explanations for top-K results.

        Returns:
            List of EnhancedHybridSearchResult sorted by combined_score desc.
        """
        # Validation: empty query
        if not query or not query.strip():
            return []

        # Clamp top_k
        if top_k < 1:
            top_k = 1
        if top_k > 100:
            top_k = 100

        try:
            return await self._search_enhanced_impl(
                query=query,
                dialogue=dialogue,
                dictionaries=dictionaries,
                top_k=top_k,
                use_semantic=use_semantic,
                use_ner=use_ner,
                use_bm25=use_bm25,
                fusion_strategy=fusion_strategy,
                explain=explain,
            )
        except Exception as exc:
            # Graceful degradation: fall back to plain search and wrap results.
            logger.warning(
                "search_enhanced failed (%s); falling back to plain search()", exc,
                exc_info=True,
            )
            base_results = await self.search(
                query=query,
                dialogue=dialogue,
                dictionaries=dictionaries,
                top_k=top_k,
                use_semantic=use_semantic,
                use_ner=use_ner,
            )
            return [
                EnhancedHybridSearchResult(**r.model_dump())
                for r in base_results
            ]

    async def _search_enhanced_impl(
        self,
        query: str,
        dialogue: Optional[ParsedDialog],
        dictionaries: Optional[List[DictionaryNode]],
        top_k: int,
        use_semantic: bool,
        use_ner: bool,
        use_bm25: bool,
        fusion_strategy: str,
        explain: bool,
    ) -> List[EnhancedHybridSearchResult]:
        """Internal enhanced search implementation (no validation/fallback wrapper)."""
        from app.services.bm25 import BM25Scorer
        from app.services import fusion as fusion_mod

        # ── Step 1: gather the same per-channel results as plain search() ──
        can_morph = dialogue is not None and dictionaries is not None and len(dictionaries) > 0
        can_semantic = use_semantic
        can_ner = use_ner and self._has_ner

        morph_results: List[_MorphResult] = []
        if can_morph:
            morph_results = await self._morph_search(query, dialogue, dictionaries)

        semantic_results: List[VectorSearchResult] = []
        if can_semantic:
            semantic_results = await self._semantic_search(query, top_k=top_k * 2)

        # ── Step 2: BM25 channel (optional, third sparse signal) ──
        bm25_ranking: List[Tuple[int, float]] = []  # (chunk_idx, score)
        bm25_chunk_texts: List[str] = []
        bm25_scorer: Optional[BM25Scorer] = None

        if use_bm25 and dialogue is not None and len(dialogue.turns) > 0:
            try:
                bm25_chunk_texts = [t.text for t in dialogue.turns]
                bm25_scorer = BM25Scorer(k1=1.2, b=0.75, lemmatize=True)
                bm25_scorer.index(bm25_chunk_texts)
                bm25_ranking = bm25_scorer.score(query, top_k=len(bm25_chunk_texts))
            except Exception as exc:
                logger.warning("search_enhanced: BM25 channel failed: %s", exc)
                bm25_ranking = []
                bm25_scorer = None

        # ── Step 3: NER query entities (same logic as plain search) ──
        query_entities: List[Dict[str, str]] = []
        if can_ner:
            query_entities = self._extract_query_entities(query)
            if not query_entities:
                can_ner = False

        # ── Step 4: build per-channel rankings keyed by (dialogue_id, turn_index) ──
        # Map each channel's results to a list of (doc_key, score) for fusion.
        # doc_key is a (dialogue_id, turn_index) tuple serialized via a dict index.
        doc_keys: Dict[Tuple[str, int], int] = {}
        doc_meta: List[Dict[str, object]] = []  # parallel list of metadata per doc_key

        def _key_for(dialogue_id: str, turn_index: int) -> int:
            k = (dialogue_id, turn_index)
            if k not in doc_keys:
                doc_keys[k] = len(doc_meta)
                doc_meta.append({"dialogue_id": dialogue_id, "turn_index": turn_index})
            return doc_keys[k]

        # Morph channel: rank by morph match order; "score" set to 1.0 (matched)
        # so RRF/Convex have a non-zero signal.
        morph_ranking: List[Tuple[int, float]] = []
        morph_doc_lookup: Dict[int, _MorphResult] = {}
        for rank, morph in enumerate(morph_results, start=1):
            doc_idx = _key_for(morph.dialogue_id, morph.turn_index)
            morph_ranking.append((doc_idx, 1.0 / rank))  # higher = better rank
            morph_doc_lookup[doc_idx] = morph

        # Semantic channel: rank by cosine score (already in [0, 1] for FAISS IP
        # with L2-normalized vectors).
        semantic_ranking: List[Tuple[int, float]] = []
        semantic_doc_lookup: Dict[int, VectorSearchResult] = {}
        for rank, semantic in enumerate(semantic_results, start=1):
            doc_idx = _key_for(semantic.dialogue_id, semantic.turn_index)
            semantic_ranking.append((doc_idx, semantic.score))
            semantic_doc_lookup[doc_idx] = semantic

        # BM25 channel: rank by BM25 score, clamped to [0,1] via score/max for
        # LogOdds compatibility. RRF ignores magnitude; Convex min-max normalizes.
        bm25_doc_ranking: List[Tuple[int, float]] = []
        bm25_max = max((s for _, s in bm25_ranking), default=0.0)
        for chunk_idx, score in bm25_ranking:
            if chunk_idx < 0 or chunk_idx >= len(bm25_chunk_texts):
                continue
            # Build a doc_key from the chunk's turn_index using the dialogue filename.
            # BM25 chunks are indexed in turn order, so chunk_idx == turn_index.
            turn_index = chunk_idx
            dialogue_id = dialogue.filename if dialogue is not None else ""
            doc_idx = _key_for(dialogue_id, turn_index)
            normalized_score = (score / bm25_max) if bm25_max > 0 else 0.0
            bm25_doc_ranking.append((doc_idx, normalized_score))

        # ── Step 5: fuse via the chosen strategy ──
        # Default weights: dense + morph + sparse (BM25).
        channels: List[List[Tuple[int, float]]] = []
        weights: List[float] = []

        if morph_ranking:
            channels.append(morph_ranking)
            weights.append(1.0)
        if semantic_ranking:
            channels.append(semantic_ranking)
            weights.append(1.0)
        if bm25_doc_ranking:
            channels.append(bm25_doc_ranking)
            weights.append(1.0)

        if not channels:
            return []

        fusion_strategy_lower = (fusion_strategy or "rrf").lower()
        if fusion_strategy_lower == "log_odds":
            # LogOdds expects exactly two channels (dense, sparse).
            # Use semantic as dense and BM25 as sparse; morph is dropped here
            # (cannot be calibrated as a probability) — falls back to RRF if
            # either is missing.
            if semantic_ranking and bm25_doc_ranking:
                fused = fusion_mod.log_odds_fusion(
                    dense_scores=semantic_ranking,
                    sparse_scores=bm25_doc_ranking,
                )
            else:
                fused = fusion_mod.reciprocal_rank_fusion(channels, k=self.rrf_k)
        elif fusion_strategy_lower == "convex":
            w_sum = sum(weights)
            norm_weights = [w / w_sum for w in weights] if w_sum > 0 else None
            fused = fusion_mod.convex_fusion(channels, weights=norm_weights)
        else:  # rrf
            fused = fusion_mod.reciprocal_rank_fusion(channels, k=self.rrf_k)

        # ── Step 6: apply NER boost (same logic as plain search) ──
        # Build HybridSearchResult objects to reuse the existing NER boost path.
        merged: Dict[Tuple[str, int], EnhancedHybridSearchResult] = {}
        for doc_idx, fused_score in fused[: top_k * 2]:
            meta = doc_meta[doc_idx]
            dialogue_id = str(meta["dialogue_id"])
            turn_index = int(meta["turn_index"])

            # Pull text + speaker + per-channel scores from whichever channel had it.
            morph = morph_doc_lookup.get(doc_idx)
            semantic = semantic_doc_lookup.get(doc_idx)

            text = ""
            speaker = ""
            morph_score = 0.0
            semantic_score = 0.0
            morph_match: Optional[DictMatch] = None

            if morph is not None:
                text = morph.text
                speaker = morph.speaker
                morph_score = 1.0
                morph_match = morph.morph_match
            if semantic is not None:
                text = text or semantic.text
                speaker = speaker or semantic.speaker
                semantic_score = semantic.score

            # BM25 score for the result row (raw BM25, not normalized).
            bm25_score = 0.0
            if bm25_scorer is not None and dialogue is not None:
                try:
                    bm25_score = bm25_scorer.score_document(query, turn_index)
                except Exception:
                    bm25_score = 0.0

            source_label = "hybrid"
            if morph is not None and semantic is None and not bm25_doc_ranking:
                source_label = "morph"
            elif semantic is not None and morph is None and not bm25_doc_ranking:
                source_label = "semantic"

            result = EnhancedHybridSearchResult(
                text=text,
                dialogue_id=dialogue_id,
                turn_index=turn_index,
                speaker=speaker,
                morph_score=morph_score,
                morph_match=morph_match,
                semantic_score=semantic_score,
                bm25_score=bm25_score,
                combined_score=float(fused_score),
                source=source_label,
            )
            merged[(dialogue_id, turn_index)] = result

        results_list = list(merged.values())

        # Apply NER boost (reuses plain-search logic; mutates combined_score).
        if can_ner and query_entities:
            results_list = self._apply_ner_boost_enhanced(results_list, query_entities)

        # Sort and trim.
        results_list.sort(key=lambda r: r.combined_score, reverse=True)
        results_list = results_list[:top_k]

        # ── Step 7: optional token-level explainability on top results ──
        if explain and results_list:
            try:
                from app.services.explainer import explain_match
            except Exception as exc:
                logger.warning("search_enhanced: explainer import failed: %s", exc)
                explain = False

            if explain:
                frida_available = False
                try:
                    frida_available = await self.embedding_service.is_available()
                except Exception:
                    frida_available = False

                if frida_available:
                    for r in results_list:
                        try:
                            contributions = await explain_match(
                                query=query,
                                text=r.text,
                                embedder=self.embedding_service,
                                top_n=10,
                            )
                            r.token_contributions = contributions
                        except Exception as exc:
                            logger.warning(
                                "search_enhanced: explain_match failed for turn %d: %s",
                                r.turn_index,
                                exc,
                            )
                            r.token_contributions = []

        return results_list

    def _apply_ner_boost_enhanced(
        self,
        results: List[EnhancedHybridSearchResult],
        query_entities: List[Dict[str, str]],
    ) -> List[EnhancedHybridSearchResult]:
        """Apply NER boost to enhanced results (mirrors _apply_ner_boost).

        Wrapped into a thin wrapper so the base ``_apply_ner_boost`` (which
        operates on HybridSearchResult) can be reused without leaking the
        Enhanced subclass into the legacy code path.
        """
        # Reuse the existing computation logic by building HybridSearchResult
        # shadows, boosting, then writing ner_boost back onto the enhanced rows.
        base_shadows: List[HybridSearchResult] = [
            HybridSearchResult(**r.model_dump(exclude={"bm25_score", "token_contributions"}))
            for r in results
        ]
        boosted = self._apply_ner_boost(base_shadows, query_entities)
        for r, b in zip(results, boosted):
            r.ner_boost = b.ner_boost
            r.matched_entities = b.matched_entities
            # _apply_ner_boost added the boost to the shadow's combined_score;
            # mirror the final value onto the enhanced row.
            r.combined_score = b.combined_score
        return results

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

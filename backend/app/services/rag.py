"""RAG pipeline service: retrieve relevant fragments → generate answer.

Orchestrates the full RAG (Retrieval-Augmented Generation) pipeline:
  1. Embed question via FRIDA (FridaEmbeddingService)
  2. Retrieve relevant fragments via HybridSearchService
     (combines morphology + semantic + NER boost via RRF)
  3. Build context from top-k retrieved fragments
  4. Generate answer via LLM with RAG-specific prompt
  5. Return answer with source citations

CRITICAL: RAG inference must use a GLM model (glm-xlarge family code) only.
Previously glm-5.1 was used; it is now decommissioned → glm-xlarge (GLM-5.2 family).
Qwen model gives HTTP 500 on /api/v2/Rag/inference endpoint.
This is documented in the code and enforced via _RAG_DEFAULT_MODEL constant.

Fallback chain:
  - FRIDA unavailable → morph-only search (no semantic), generate answer from morph results
  - LLM unavailable → return retrieved fragments without generated answer
  - Both unavailable → return empty result with error message
  - Empty vector store → return empty result with informational error
  - HybridSearchService not initialized → return error result

Citation format: dialogue_id + turn_index + text_snippet (stable for future RAG chat UI).

API contract:
  query(question, session_id, top_k, provider_id) → RagQueryResponse
  get_status() → Dict[str, Any]
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.models import (
    HybridSearchResult,
    RagQueryResponse,
    RagSourceFragment,
    VectorSearchResult,
)

logger = logging.getLogger(__name__)

# CRITICAL: RAG inference must use a GLM model only (glm-xlarge family code).
# glm-5.1 was decommissioned → replaced by glm-xlarge (GLM-5.2 family, per
# official Beeline AI docs: https://docs.ai.beeline.ru/quickstart/models/).
# Qwen model returns HTTP 500 on /api/v2/Rag/inference.
# This constant is used as the default model for RAG answer generation.
_RAG_DEFAULT_MODEL = "glm-xlarge"

# RAG-specific system prompt: answer based ONLY on provided context.
#
# NOTE: Mirrored in backend/app/prompts/rag.yaml (managed by prompt_manager).
# Inline constant below is kept as backward-compat fallback — see
# _resolve_system_prompt() in app.services.llm.
_RAG_SYSTEM_PROMPT = """\
Ты — помощник для анализа диалогов колл-центра. Отвечай на вопросы, основываясь ТОЛЬКО на предоставленном контексте из диалогов.

Правила:
1. Отвечай только на основе предоставленного контекста.
2. Указывай источники в формате [1], [2] и т.д., где число — номер фрагмента в контексте.
3. Если контекст не содержит ответа на вопрос, прямо скажи об этом.
4. Не придумывай информацию, которой нет в контексте.
5. Отвечай на русском языке."""

# Maximum context length in characters to prevent token overflow
_MAX_CONTEXT_CHARS = 12000

# Context block template
_CONTEXT_BLOCK_TEMPLATE = "[{idx}] Диалог {dialogue_id}, реплика {turn_index} ({speaker}): {text}"

# Citation pattern: [1], [2], etc.
_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


class RAGService:
    """RAG pipeline: retrieve relevant fragments → generate answer.

    Uses existing HybridSearchService for retrieval and LLM providers
    for answer generation. Does NOT replace or modify any existing services.

    Attributes:
        hybrid_search_service: HybridSearchService for fragment retrieval.
        embedding_service: FridaEmbeddingService for query embedding.
        vector_store: VectorStore for direct search when needed.
        _rag_model: Model name forced for RAG inference (GLM-5.1).
    """

    def __init__(
        self,
        hybrid_search_service: Any,  # HybridSearchService — typed as Any to avoid circular import
        embedding_service: Any,  # FridaEmbeddingService
        vector_store: Any,  # VectorStore
    ) -> None:
        """Initialize RAGService.

        Args:
            hybrid_search_service: HybridSearchService instance for retrieval.
            embedding_service: FridaEmbeddingService instance for FRIDA embedding.
            vector_store: VectorStore instance for direct FAISS search.
        """
        self.hybrid_search_service = hybrid_search_service
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self._rag_model = _RAG_DEFAULT_MODEL

    # ── Main API ─────────────────────────────────────────────

    async def query(
        self,
        question: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
        provider_id: str = "beeline",
    ) -> RagQueryResponse:
        """Full RAG pipeline: embed → retrieve → build context → generate answer.

        Fallback chain:
          1. FRIDA unavailable → morph-only search, generate from morph results
          2. LLM unavailable → return fragments without generated answer
          3. Both unavailable → empty result with error
          4. Empty vector store → empty result with informational error

        Args:
            question: User's question about the dialogues.
            session_id: Optional session ID to restrict search scope.
            top_k: Number of fragments to retrieve (1-20).
            provider_id: LLM provider for answer generation.

        Returns:
            RagQueryResponse with answer, sources, and metadata.
        """
        if not question or not question.strip():
            return RagQueryResponse(
                question=question,
                error="Question cannot be empty",
            )

        # Step 1: Retrieve relevant fragments
        fragments, search_source = await self._retrieve_fragments(
            question=question,
            session_id=session_id,
            top_k=top_k,
        )

        if not fragments:
            # Check why we got no fragments
            vector_stats = self.vector_store.get_stats()
            if vector_stats.get("total_vectors", 0) == 0:
                return RagQueryResponse(
                    question=question,
                    search_source=search_source,
                    error="No dialogues indexed. Upload and index dialogues first.",
                )
            return RagQueryResponse(
                question=question,
                search_source=search_source,
                context_used=0,
                error="No relevant fragments found for the given question.",
            )

        # Step 2: Build context from fragments
        context_blocks, context_used = self._build_context(fragments)

        if not context_blocks:
            return RagQueryResponse(
                question=question,
                sources=self._fragments_to_sources(fragments, search_source),
                search_source=search_source,
                context_used=0,
                error="Could not build context from retrieved fragments.",
            )

        # Step 3: Generate answer via LLM
        answer, provider, model, llm_error = await self._generate_answer(
            question=question,
            context_blocks=context_blocks,
            provider_id=provider_id,
        )

        # Step 4: Build response with sources and citations
        sources = self._fragments_to_sources(fragments[:context_used], search_source)

        # If LLM failed, return fragments without answer
        if llm_error is not None:
            return RagQueryResponse(
                question=question,
                answer="",
                sources=sources,
                context_used=context_used,
                search_source=search_source,
                provider="none",
                model="",
                error=f"Retrieval succeeded but answer generation failed: {llm_error}",
            )

        return RagQueryResponse(
            question=question,
            answer=answer,
            sources=sources,
            context_used=context_used,
            search_source=search_source,
            provider=provider,
            model=model,
        )

    # ── Retrieval ────────────────────────────────────────────

    async def _retrieve_fragments(
        self,
        question: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
    ) -> tuple[list[HybridSearchResult], str]:
        """Retrieve relevant fragments via HybridSearchService.

        If session_id is provided, tries to get dialogue and dictionaries
        from session store for morphological search. Otherwise, relies
        on semantic-only search.

        Falls back to semantic-only if morphological resources unavailable.

        Args:
            question: Search query.
            session_id: Optional session filter.
            top_k: Number of results to retrieve.

        Returns:
            Tuple of (fragments, search_source).
        """
        dialogue = None
        dictionaries = None

        # Try to get dialogue/dictionaries from session store for morph search
        if session_id:
            try:
                from app.utils.session import session_store

                session = session_store.get(session_id)
                if session is not None:
                    dialogue = session.dialog
                    if session.dictionaries:
                        dictionaries = list(session.dictionaries.values())
            except Exception as exc:
                logger.warning(
                    "RAG: could not get session %s for morph search: %s",
                    session_id,
                    exc,
                )

        # Use HybridSearchService for retrieval
        try:
            results = await self.hybrid_search_service.search(
                query=question,
                dialogue=dialogue,
                dictionaries=dictionaries,
                top_k=top_k,
                use_semantic=True,
                use_ner=True,
            )

            # Filter by session_id if provided (for semantic results)
            if session_id and results:
                results = [
                    r for r in results if r.dialogue_id == session_id
                ]

            # Determine search source from results
            search_source = "hybrid"
            if results:
                search_source = results[0].source
                # Normalize source labels
                if search_source not in ("morph", "semantic", "hybrid", "ner_boost"):
                    search_source = "hybrid"

            return results, search_source

        except Exception as exc:
            logger.error("RAG: hybrid search failed: %s", exc, exc_info=True)

            # Fallback: try semantic-only search directly via VectorStore
            return await self._semantic_fallback_search(question, session_id, top_k)

    async def _semantic_fallback_search(
        self,
        question: str,
        session_id: Optional[str],
        top_k: int,
    ) -> tuple[list[HybridSearchResult], str]:
        """Fallback: semantic-only search when HybridSearchService fails.

        Embeds question via FRIDA and searches VectorStore directly.
        If FRIDA is also unavailable, returns empty results.

        Args:
            question: Search query.
            session_id: Optional session filter.
            top_k: Number of results.

        Returns:
            Tuple of (fragments, search_source='semantic' or 'none').
        """
        try:
            # Check FRIDA availability
            if not await self.embedding_service.is_available():
                logger.warning("RAG: FRIDA unavailable — cannot perform semantic fallback search")
                return [], "none"

            # Embed query
            query_vector = await self.embedding_service.embed(question)

            # Search VectorStore
            semantic_results = self.vector_store.search(query_vector, k=top_k)

            # Filter by session_id if provided
            if session_id:
                semantic_results = [
                    r for r in semantic_results if r.dialogue_id == session_id
                ]

            # Convert VectorSearchResult → HybridSearchResult
            fragments: list[HybridSearchResult] = []
            for result in semantic_results:
                fragments.append(
                    HybridSearchResult(
                        text=result.text,
                        dialogue_id=result.dialogue_id,
                        turn_index=result.turn_index,
                        speaker=result.speaker,
                        semantic_score=result.score,
                        combined_score=result.score,
                        source="semantic",
                    )
                )

            return fragments, "semantic"

        except ConnectionError:
            logger.warning("RAG: FRIDA circuit breaker open — semantic fallback unavailable")
            return [], "none"
        except Exception as exc:
            logger.error("RAG: semantic fallback search failed: %s", exc, exc_info=True)
            return [], "none"

    # ── Context building ─────────────────────────────────────

    def _build_context(
        self,
        fragments: List[HybridSearchResult],
    ) -> tuple[list[str], int]:
        """Build numbered context blocks from retrieved fragments.

        Each fragment is formatted as:
            [idx] Диалог dialogue_id, реплика turn_index (speaker): text

        Context is truncated to _MAX_CONTEXT_CHARS to prevent token overflow.

        Args:
            fragments: Retrieved fragments from search.

        Returns:
            Tuple of (context_blocks, context_used_count).
        """
        blocks: list[str] = []
        total_chars = 0
        context_used = 0

        for i, fragment in enumerate(fragments, start=1):
            block = _CONTEXT_BLOCK_TEMPLATE.format(
                idx=i,
                dialogue_id=fragment.dialogue_id,
                turn_index=fragment.turn_index,
                speaker=fragment.speaker,
                text=fragment.text,
            )

            # Truncate individual block if too long
            if len(block) > 1000:
                block = block[:997] + "..."

            # Check if adding this block exceeds context limit
            if total_chars + len(block) > _MAX_CONTEXT_CHARS:
                # Try truncated version
                remaining = _MAX_CONTEXT_CHARS - total_chars
                if remaining > 100:
                    block = block[:remaining - 3] + "..."
                    blocks.append(block)
                    context_used += 1
                break

            blocks.append(block)
            total_chars += len(block)
            context_used += 1

        return blocks, context_used

    # ── Answer generation ────────────────────────────────────

    async def _generate_answer(
        self,
        question: str,
        context_blocks: List[str],
        provider_id: str = "beeline",
    ) -> tuple[str, str, str, Optional[str]]:
        """Generate answer via LLM with RAG-specific prompt.

        CRITICAL: Uses a GLM model (glm-xlarge family code) only for RAG inference.
        glm-5.1 was decommissioned → glm-xlarge (GLM-5.2 family). Qwen model gives HTTP 500 on /api/v2/Rag/inference.

        Uses circuit breaker + fallback chain from existing LLM infrastructure.
        System prompt instructs model to answer ONLY from context and cite sources.

        Args:
            question: User's question.
            context_blocks: Numbered context blocks from retrieved fragments.
            provider_id: LLM provider ID (default: beeline).

        Returns:
            Tuple of (answer, provider, model, error).
            On success: (answer, provider, model, None).
            On failure: ("", "none", "", error_message).
        """
        from app.services.llm import (
            get_provider,
            _get_circuit_breaker,
            _get_fallback_order,
            _resolve_system_prompt,
        )

        # Build user prompt with context
        context_text = "\n\n".join(context_blocks)
        user_prompt = f"Контекст:\n{context_text}\n\nВопрос: {question}"

        # CRITICAL: Force GLM model (glm-xlarge family code) for RAG inference.
        # Qwen returns HTTP 500 on /api/v2/Rag/inference.
        model_override = self._rag_model

        # Get ordered fallback chain
        provider_order = _get_fallback_order(provider_id)

        last_error: Optional[str] = None

        for pid in provider_order:
            cb = _get_circuit_breaker(pid)

            # Check circuit breaker
            if not cb.can_execute():
                logger.info(
                    "RAG LLM: circuit breaker [%s] is %s — skipping",
                    pid,
                    cb.state,
                )
                continue

            provider = get_provider(pid)
            if provider is None:
                continue

            # External Guardrails providers are unreliable — warn on use.
            if pid in ("yandexgpt", "gigachat"):
                logger.warning(
                    "RAG: using %s which goes through Guardrails — may fail",
                    pid,
                )

            try:
                raw_response = await provider.generate(
                    prompt=user_prompt,
                    model=model_override,
                    system_prompt=_resolve_system_prompt("rag", _RAG_SYSTEM_PROMPT),
                )

                # Record success in circuit breaker
                cb.record_success()

                answer = raw_response.strip() if raw_response else ""

                if not answer:
                    last_error = "LLM returned empty response"
                    continue

                return answer, pid, model_override, None

            except (ConnectionError, TimeoutError) as exc:
                error_msg = str(exc).lower()
                if "not configured" not in error_msg:
                    cb.record_failure()
                last_error = str(exc)
                logger.warning(
                    "RAG LLM: provider %s failed: %s — trying next",
                    pid,
                    exc,
                )
                continue
            except Exception as exc:
                cb.record_failure()
                last_error = str(exc)
                logger.error(
                    "RAG LLM: provider %s unexpected error: %s",
                    pid,
                    exc,
                )
                continue

        # All providers failed
        logger.error("RAG LLM: all providers failed. Last error: %s", last_error)
        return "", "none", "", last_error or "All LLM providers unavailable"

    # ── Source mapping ────────────────────────────────────────

    @staticmethod
    def _fragments_to_sources(
        fragments: List[HybridSearchResult],
        search_source: str,
    ) -> List[RagSourceFragment]:
        """Convert HybridSearchResult list to RagSourceFragment list.

        Preserves citation format: dialogue_id + turn_index + text_snippet.

        Args:
            fragments: Search results to convert.
            search_source: Search method used.

        Returns:
            List of RagSourceFragment with provenance and relevance info.
        """
        sources: List[RagSourceFragment] = []
        for fragment in fragments:
            # Truncate text snippet for display
            snippet = fragment.text
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."

            sources.append(
                RagSourceFragment(
                    dialogue_id=fragment.dialogue_id,
                    turn_index=fragment.turn_index,
                    speaker=fragment.speaker,
                    text_snippet=snippet,
                    relevance_score=fragment.combined_score,
                    search_source=search_source,
                )
            )
        return sources

    # ── Status ───────────────────────────────────────────────

    async def get_status(self) -> Dict[str, Any]:
        """Get RAG service status for monitoring.

        Returns:
            Dict with FRIDA availability, vector store stats,
            LLM provider status, and RAG model info.
        """
        # Check FRIDA availability
        frida_available = False
        try:
            frida_available = await self.embedding_service.is_available()
        except Exception:
            frida_available = False

        # Get vector store stats
        vector_stats = self.vector_store.get_stats()

        # Get hybrid search stats
        hybrid_stats = self.hybrid_search_service.get_stats()

        # Check LLM providers
        from app.services.llm import get_provider, _get_circuit_breaker

        provider_status: Dict[str, Any] = {}
        for pid in ("beeline", "beeline_fast", "qwen36", "qwen35", "ollama", "yandexgpt", "gigachat"):
            provider = get_provider(pid)
            cb = _get_circuit_breaker(pid)
            provider_status[pid] = {
                "configured": provider is not None,
                "circuit_breaker_state": cb.state,
            }

        return {
            "frida_available": frida_available,
            "vector_store": vector_stats,
            "hybrid_search": hybrid_stats,
            "rag_model": self._rag_model,
            "rag_model_note": "GLM model (glm-xlarge family code) only for RAG inference (Qwen gives HTTP 500 on /api/v2/Rag/inference)",
            "providers": provider_status,
        }

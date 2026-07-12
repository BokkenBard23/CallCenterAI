"""Offline corpus mining service for dictionary discovery (Track B).

Composition over existing services — НЕ duplicates embedding/llm/search logic:
  - :class:`FridaEmbeddingService` (existing) для фраз + диалогов (FRIDA-only, 1536-dim)
  - :class:`VectorStore` (existing, FAISS IndexFlatIP) для похожих
  - :class:`LLMProvider` (existing, GLM/Qwen via :func:`get_provider`) для self-summary +
    classification + audit (existing per-provider semaphores: GLM=2, Qwen3.5=3, Qwen3.6=3)
  - :func:`run_hierarchical_search` (existing, FROZEN) — baseline dict matches (composition
    reference only, НЕ modified)
  - :class:`Chunker` (existing) для dialogue segmentation
  - :func:`parse_rtf_file` (existing) для corpus files
  - :class:`MiningStore` (extended) для persistence + checkpoint/resume

НЕ production-runtime — НЕ вызывается из :mod:`app.services.search`. В production
остаётся только XML-словарь + ``search.py``. Итоговый продукт = XML-словарь
(парсимый ``xml_parser.py`` + ``search.py``).

LLM concurrency
---------------
This service does NOT create new semaphores. It reuses the per-provider
semaphores configured in :class:`app.services.llm.LLMProvider` subclasses
(GLM=2, Qwen3.5=3, Qwen3.6=3, total max 8 parallel). Calls go through
:func:`app.services.llm.get_provider` and ``provider.generate(...)``, which
already acquire the correct semaphore internally.

Checkpointing
------------
Every ``_CHECKPOINT_EVERY`` (25) processed dialogues a checkpoint row is
written to ``mining_checkpoints`` and ``mining_jobs.checkpoint_at`` /
``processed_dialogues`` are updated. Long-running job loops check the job
status after each checkpoint and stop early if the job was cancelled.

JSON output parsing
-------------------
LLM prompts instruct the model to return strict JSON. :func:`_parse_llm_json`
tolerates markdown code fences and trailing whitespace; on failure it returns
a degraded default value (logged) rather than raising — partial results are
preferred for the Quick Win demo profile.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.models import (
    AuditJobResult,
    AuditRecommendation,
    ConfidenceLabel,
    FNCandidate,
    FindFNJobResult,
    FindFNResponse,
    FindSimilarResponse,
    IndexCorpusResponse,
    MiningJobStatus,
    PhraseGroupAudit,
    SimilarDialogue,
)
from app.services.chunker import Chunker
from app.services.embedding import FridaEmbeddingService
from app.services.llm import _get_fallback_order, get_provider
from app.services.prompt_manager import prompt_manager
from app.services.rtf_parser import parse_rtf_file
from app.services.search import run_hierarchical_search  # FROZEN — composition reference only
from app.services.session_store_sqlite import MiningStore
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Checkpoint granularity (master plan §4.3): every 25 processed dialogues.
_CHECKPOINT_EVERY = 25

# Snippet length (chars) for SimilarDialogue / FNCandidate snippets.
_SNIPPET_LEN = 240

# Primary LLM provider id for mining (GLM family — shared semaphore, 2 slots).
_PRIMARY_LLM_PROVIDER = "beeline"


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE | re.IGNORECASE)


def _strip_code_fence(text: str) -> str:
    """Strip leading/trailing markdown code fences from an LLM response."""
    return _FENCE_RE.sub("", text.strip()).strip()


def _parse_llm_json(raw: str, default: Any) -> Any:
    """Parse an LLM JSON response, tolerating markdown fences.

    Returns ``default`` on parse failure (logged at WARNING). Never raises —
    callers prefer degraded partial results for the demo profile.
    """
    if not raw:
        return default
    cleaned = _strip_code_fence(raw)
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError) as exc:
        logger.warning("LLM JSON parse failed (%s); raw=%r", exc, raw[:200])
        return default


def _now_iso() -> str:
    return datetime.now().isoformat()


def _snippet(text: str, length: int = _SNIPPET_LEN) -> str:
    """Return the first ``length`` characters of ``text`` with an ellipsis."""
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "…"


def _map_label(raw_label: Any) -> ConfidenceLabel:
    """Normalise an LLM label string to a :class:`ConfidenceLabel` value.

    Tolerates partial / misspelled inputs by mapping to ``uncertain``.
    """
    if isinstance(raw_label, str):
        label = raw_label.strip().lower()
        if label in ("relevant", "релевантен", "релевантно", "релевантный"):
            return ConfidenceLabel.relevant
        if label in ("irrelevant", "нерелевантен", "нерелевантно", "нерелевантный", "not relevant"):
            return ConfidenceLabel.irrelevant
        if label in ("uncertain", "частично", "partial", "partially", "не уверен", "неуверенно"):
            return ConfidenceLabel.uncertain
    return ConfidenceLabel.uncertain


def _clamp_score(value: Any) -> float:
    """Coerce a score-like value to a float in [0, 1]."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _gather_phrase_texts(node: Any) -> List[Tuple[str, str]]:
    """Collect ``(phrase_group_id, phrase_text)`` pairs from a DictionaryNode tree.

    Walks conditions of each node and uses the condition ``text`` as the
    phrase text and a synthetic id ``"<root_name>:<condition_index>"`` when
    a stable PhraseGroup id is not available. The exact ``phrase_group_id``
    format is not a frozen invariant — it is consumed only by this service
    and the mining UI for display.
    """
    pairs: List[Tuple[str, str]] = []
    visited: set[int] = set()

    def walk(n: Any, root_name: str) -> None:
        if id(n) in visited:
            return
        visited.add(id(n))
        conditions = getattr(n, "conditions", None) or []
        for idx, cond in enumerate(conditions):
            text = getattr(cond, "text", "")
            if not text:
                continue
            # Prefer explicit phrase_groups content if present; fall back to text.
            pg = getattr(cond, "phrase_groups", None) or []
            pg_id: str = f"{root_name}:{idx}"
            if pg:
                # Take the joined words of the first phrase group as the phrase text.
                first_pg = pg[0]
                words = getattr(first_pg, "words", None)
                if words:
                    joined = " ".join(words)
                    if joined.strip():
                        text = joined
            pairs.append((pg_id, text))
        for child in getattr(n, "children", None) or []:
            walk(child, root_name)

    walk(node, getattr(node, "name", "dict"))
    return pairs


# ═══════════════════════════════════════════════════════════
# DictionaryMiningService
# ═══════════════════════════════════════════════════════════


class DictionaryMiningService:
    """Offline corpus mining service.

    НЕ production-runtime. НЕ заменяет ``search.py``. Composition over existing
    services (embedding, vector_store, llm, search, chunker, rtf_parser,
    session_store_sqlite).

    All long-running operations (``index_corpus``, ``find_false_negatives``,
    ``audit_full_dictionary``) are run as background :class:`asyncio.Task`s by
    the router and report progress via :meth:`get_job_status` polling.
    """

    def __init__(
        self,
        embedding_service: FridaEmbeddingService,
        vector_store: VectorStore,
        chunker: Chunker,
        mining_store: MiningStore,
        primary_provider_id: str = _PRIMARY_LLM_PROVIDER,
    ) -> None:
        self._embedding = embedding_service
        self._vector_store = vector_store
        self._chunker = chunker
        self._mining_store = mining_store
        self._primary_provider_id = primary_provider_id
        # Track running asyncio tasks so router can await / cancel if needed.
        self._running_tasks: Dict[str, asyncio.Task[None]] = {}

    # ── LLM access ────────────────────────────────────────────

    async def _call_llm(
        self,
        prompt_name: str,
        user_prompt: str,
        provider_id: Optional[str] = None,
    ) -> Optional[str]:
        """Call an LLM via the standard fallback chain.

        Resolves the system prompt from ``prompts/mining.yaml`` via
        :data:`prompt_manager`. The existing per-provider semaphores
        (GLM=2, Qwen3.5=3, Qwen3.6=3) are acquired internally by
        :meth:`LLMProvider.generate` — this service does NOT create new
        semaphores.
        """
        cfg = prompt_manager.get(prompt_name)
        system_prompt = cfg.format_system() if cfg is not None else ""
        primary = provider_id or self._primary_provider_id
        order = _get_fallback_order(primary)
        last_error: Optional[Exception] = None
        for pid in order:
            provider = get_provider(pid)
            if provider is None:
                continue
            try:
                raw = await provider.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                )
                if raw:
                    return raw
                logger.warning("mining LLM %s returned empty response", pid)
            except (ConnectionError, TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "mining LLM %s failed (%s) — trying next provider", pid, exc,
                )
                continue
            except Exception as exc:
                last_error = exc
                logger.error("mining LLM %s unexpected error: %s", pid, exc)
                continue
        if last_error is not None:
            logger.error("mining LLM all providers failed: %s", last_error)
        return None

    # ── Job lifecycle ─────────────────────────────────────────

    def _make_job_id(self, job_type: str) -> str:
        return f"mining-{job_type}-{uuid.uuid4().hex[:16]}"

    def _register_task(self, job_id: str, task: asyncio.Task[None]) -> None:
        self._running_tasks[job_id] = task

        def _cleanup(_t: asyncio.Task[None]) -> None:
            self._running_tasks.pop(job_id, None)

        task.add_done_callback(_cleanup)

    def cancel_running_task(self, job_id: str) -> bool:
        """Cancel the asyncio task backing a job. Returns True if cancelled."""
        task = self._running_tasks.get(job_id)
        if task is not None and not task.done():
            return task.cancel()
        return False

    # ── index_corpus ──────────────────────────────────────────

    async def index_corpus(
        self,
        directory_path: str,
        dictionary_id: str,
        session_id: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> IndexCorpusResponse:
        """Index all RTF files in ``directory_path``.

        Flow:
          1. List ``*.rtf`` files in ``directory_path``.
          2. For each RTF: ``parse_rtf_file`` → turns → ``chunker.chunk_text``
             → ``embedding_service.embed_texts`` → ``vector_store.add``.
          3. Persist dialogue row in ``mining_corpus``.
          4. Checkpoint every ``_CHECKPOINT_EVERY`` dialogues.
          5. Update ``mining_jobs`` row to ``completed``.

        Invalid RTF files are skipped with a warning; the job continues. If
        no RTF files exist, raises :class:`ValueError` (router maps to 400).
        """
        directory = Path(directory_path)
        if not directory.is_dir():
            raise ValueError(f"directory_path does not exist: {directory_path}")

        rtf_files = sorted(directory.glob("*.rtf"))
        if not rtf_files:
            raise ValueError(f"no .rtf files found in {directory_path}")

        job_id = self._make_job_id("index")
        self._mining_store.create_job(
            job_id=job_id,
            session_id=session_id,
            dictionary_id=dictionary_id,
            directory_path=directory_path,
            job_type="index",
        )
        self._mining_store.update_job(
            job_id, status="running", total_dialogues=len(rtf_files)
        )

        processed = 0
        failed = 0
        try:
            for rtf_path in rtf_files:
                if self._is_cancelled(job_id):
                    break
                try:
                    parsed = await parse_rtf_file(rtf_path, rtf_path.name)
                except (ValueError, OSError) as exc:
                    logger.warning("mining.index: skip %s (%s)", rtf_path.name, exc)
                    failed += 1
                    continue

                dialogue_id = f"{job_id}:{rtf_path.stem}"
                full_text = "\n".join(t.text for t in parsed.turns)
                channel = "ANY"
                if parsed.turns:
                    speakers = {t.speaker for t in parsed.turns}
                    if speakers == {"Клиент"}:
                        channel = "CLIENT"
                    elif speakers == {"Сотрудник"}:
                        channel = "OPERATOR"

                # Chunk + embed + add to FAISS (composition over existing services).
                all_chunks = []
                for turn_idx, turn in enumerate(parsed.turns):
                    chunks = self._chunker.chunk_text(
                        turn.text,
                        metadata_base={
                            "dialogue_id": dialogue_id,
                            "turn_index": turn_idx,
                            "speaker": turn.speaker,
                        },
                    )
                    all_chunks.extend(chunks)

                if all_chunks:
                    embeddings = await self._embedding.embed_texts(
                        [c.text for c in all_chunks]
                    )
                    metadata = [
                        {
                            "chunk_id": c.metadata.chunk_id,
                            "dialogue_id": dialogue_id,
                            "text": c.text,
                            "turn_index": c.metadata.turn_index,
                            "speaker": c.metadata.speaker,
                            "chunk_type": c.metadata.chunk_type,
                            "entities": c.metadata.entities,
                        }
                        for c in all_chunks
                    ]
                    self._vector_store.add(embeddings, metadata)

                self._mining_store.add_corpus_entry(
                    job_id=job_id,
                    dialogue_id=dialogue_id,
                    file_path=str(rtf_path),
                    text=full_text,
                    channel=channel,
                    turn_count=len(parsed.turns),
                )

                processed += 1
                if processed % _CHECKPOINT_EVERY == 0:
                    self._mining_store.add_checkpoint(job_id, processed, dialogue_id)
                if progress_cb is not None:
                    progress_cb(processed, len(rtf_files))

            final_status = "cancelled" if self._is_cancelled(job_id) else "completed"
            warning: Optional[str] = None
            if failed > 0:
                warning = f"обработано {processed}, пропущено невалидных RTF: {failed}"
                if final_status == "completed":
                    final_status = "partial"
            self._mining_store.update_job(
                job_id,
                status=final_status,
                processed_dialogues=processed,
                completed_at=_now_iso(),
                warning=warning,
            )
        except Exception as exc:
            logger.exception("mining.index_corpus failed for job=%s", job_id)
            self._mining_store.update_job(
                job_id, status="failed", error=str(exc), completed_at=_now_iso()
            )
            raise

        return IndexCorpusResponse(
            job_id=job_id,
            status="running",
            total_dialogues=len(rtf_files),
            message=f"indexing started for {len(rtf_files)} RTF files",
        )

    # ── find_similar_to_phrase ────────────────────────────────

    async def find_similar_to_phrase(
        self,
        phrase_group_id: str,
        phrase_text: str,
        top_k: int = 20,
    ) -> FindSimilarResponse:
        """Find ``top_k`` dialogues similar to ``phrase_text``.

        Uses ``embedding_service.embed_texts`` + ``vector_store.search``
        (existing services). Results are deduplicated by ``dialogue_id``
        keeping the highest score.
        """
        if not phrase_text:
            return FindSimilarResponse(
                phrase_group_id=phrase_group_id, total=0, dialogues=[]
            )

        embeddings = await self._embedding.embed_texts([phrase_text])
        if not embeddings:
            return FindSimilarResponse(
                phrase_group_id=phrase_group_id, total=0, dialogues=[]
            )
        query_vector = embeddings[0]
        raw_hits = self._vector_store.search(query_vector, k=max(top_k * 3, top_k))

        # Dedup by dialogue_id, keep max score, accumulate turn_count + channel.
        best: Dict[str, SimilarDialogue] = {}
        for hit in raw_hits:
            existing = best.get(hit.dialogue_id)
            if existing is not None and existing.score >= hit.score:
                continue
            channel = _normalise_channel(hit.speaker)
            best[hit.dialogue_id] = SimilarDialogue(
                dialogue_id=hit.dialogue_id,
                file_path=hit.dialogue_id,
                snippet=_snippet(hit.text),
                score=_clamp_score(hit.score),
                channel=channel,
                turn_count=int(getattr(hit, "turn_index", 0) or 0),
            )

        dialogues = list(best.values())[:top_k]
        return FindSimilarResponse(
            phrase_group_id=phrase_group_id,
            total=len(dialogues),
            dialogues=dialogues,
        )

    # ── find_false_negatives ─────────────────────────────────

    async def find_false_negatives(
        self,
        dictionary_node: Any,
        job_id: str,
        threshold: float = 0.7,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> FindFNResponse:
        """Find FN candidates: dialogues NOT matched by the dict but vector-close.

        Flow per corpus dialogue:
          1. ``run_hierarchical_search`` (FROZEN) → if ``total_matches > 0`` skip.
          2. Else embed dict phrases and search the vector store; if top score
             ``>= threshold`` → LLM verify via ``find_fn`` prompt.
          3. Persist ``FNCandidate`` row + ``mining_fn_candidates``.

        Checkpoint every ``_CHECKPOINT_EVERY`` dialogues. LLM failures degrade
        to ``uncertain`` label (logged); the job continues (partial).
        """
        corpus = self._mining_store.list_corpus(job_id)
        total = len(corpus)
        if total == 0:
            return FindFNResponse(
                job_id=job_id,
                dictionary_id=getattr(dictionary_node, "name", ""),
                total=0,
                candidates=[],
                partial=False,
            )

        phrase_pairs = _gather_phrase_texts(dictionary_node)
        if not phrase_pairs:
            return FindFNResponse(
                job_id=job_id,
                dictionary_id=getattr(dictionary_node, "name", ""),
                total=0,
                candidates=[],
                partial=False,
            )

        # Pre-embed all dict phrases once (reuse across dialogues).
        phrase_texts = [text for _id, text in phrase_pairs]
        phrase_embeddings = await self._embedding.embed_texts(phrase_texts)

        self._mining_store.update_job(job_id, status="running", total_dialogues=total)

        candidates: List[FNCandidate] = []
        processed = 0
        partial = False
        dicts_list = [dictionary_node]

        try:
            for entry in corpus:
                if self._is_cancelled(job_id):
                    break
                processed += 1

                # Build a minimal ParsedDialog-like object for the FROZEN search.
                # run_hierarchical_search only reads `turns` (turn_index, speaker, text).
                turns = _build_turns_for_search(entry)
                pseudo_dialog = _PseudoDialog(turns=turns)

                try:
                    search_result = await run_hierarchical_search(
                        pseudo_dialog,  # type: ignore[arg-type]
                        dicts_list,
                    )
                except Exception as exc:
                    logger.warning(
                        "mining.find_fn: search failed for %s (%s)",
                        entry["dialogue_id"], exc,
                    )
                    continue

                if search_result.total_matches > 0:
                    continue  # Not a false negative.

                # Vector-close check across all dict phrase embeddings.
                best_score = 0.0
                best_phrase_id: Optional[str] = None
                for (pg_id, _text), emb in zip(phrase_pairs, phrase_embeddings):
                    hits = self._vector_store.search(emb, k=1)
                    for hit in hits:
                        if hit.dialogue_id == entry["dialogue_id"] and hit.score > best_score:
                            best_score = float(hit.score)
                            best_phrase_id = pg_id

                if best_score < threshold:
                    continue

                # LLM verify.
                llm_raw = await self._call_llm(
                    "find_fn",
                    _format_find_fn_user_prompt(entry["text"]),
                )
                if llm_raw is None:
                    partial = True
                    continue

                payload = _parse_llm_json(llm_raw, default={})
                if not isinstance(payload, dict):
                    payload = {}

                label = _map_label(payload.get("label"))
                score = _clamp_score(payload.get("score"))
                reason = str(payload.get("reason") or "").strip()
                proposed = payload.get("proposed_phrase")
                proposed_phrase: Optional[str]
                if isinstance(proposed, str) and proposed.strip():
                    proposed_phrase = proposed.strip()
                else:
                    proposed_phrase = None

                candidate = FNCandidate(
                    dialogue_id=entry["dialogue_id"],
                    file_path=entry["file_path"],
                    snippet=_snippet(entry["text"]),
                    score=_clamp_score(best_score),
                    llm_label=label,
                    llm_score=score,
                    llm_reason=reason,
                    proposed_phrase=proposed_phrase,
                )
                candidates.append(candidate)
                self._mining_store.add_fn_candidate(
                    job_id=job_id,
                    dialogue_id=entry["dialogue_id"],
                    score=best_score,
                    llm_label=label.value,
                    phrase_group_id=best_phrase_id,
                    llm_score=score,
                    llm_reason=reason,
                    proposed_phrase=proposed_phrase,
                )

                if processed % _CHECKPOINT_EVERY == 0:
                    self._mining_store.add_checkpoint(
                        job_id, processed, entry["dialogue_id"]
                    )
                if progress_cb is not None:
                    progress_cb(processed, total)

            final_status = "cancelled" if self._is_cancelled(job_id) else "completed"
            if partial and final_status == "completed":
                final_status = "partial"
            result = FindFNJobResult(candidates=candidates)
            self._mining_store.update_job(
                job_id,
                status=final_status,
                processed_dialogues=processed,
                completed_at=_now_iso(),
                warning=("LLM rate limited — partial results" if partial else None),
                result_json=self._mining_store.dump_json(result.model_dump()),
            )
        except Exception as exc:
            logger.exception("mining.find_false_negatives failed for job=%s", job_id)
            self._mining_store.update_job(
                job_id, status="failed", error=str(exc), completed_at=_now_iso()
            )
            raise

        return FindFNResponse(
            job_id=job_id,
            dictionary_id=getattr(dictionary_node, "name", ""),
            total=len(candidates),
            candidates=candidates,
            partial=partial,
        )

    # ── audit_phrase_group ───────────────────────────────────

    async def audit_phrase_group(
        self,
        phrase_group_id: str,
        phrase_text: str,
        job_id: str,
    ) -> PhraseGroupAudit:
        """Run an LLM audit on a single PhraseGroup.

        Returns a :class:`PhraseGroupAudit` (recall, missed_count,
        recommendations, llm_explanation). Persisted to ``mining_audit_results``.
        """
        llm_raw = await self._call_llm(
            "audit_phrase_group",
            _format_audit_user_prompt(phrase_text),
        )
        if llm_raw is None:
            audit = PhraseGroupAudit(
                phrase_group_id=phrase_group_id,
                phrase_text=phrase_text,
                recall=0.0,
                missed_count=0,
                recommendations=[],
                llm_explanation="LLM unavailable",
            )
        else:
            payload = _parse_llm_json(llm_raw, default={})
            if not isinstance(payload, dict):
                payload = {}
            recommendations = _build_recommendations(payload.get("recommendations"))
            audit = PhraseGroupAudit(
                phrase_group_id=phrase_group_id,
                phrase_text=phrase_text,
                recall=_clamp_score(payload.get("recall")),
                missed_count=int(payload.get("missed_count") or 0),
                recommendations=recommendations,
                llm_explanation=str(payload.get("explanation") or "").strip(),
            )

        self._mining_store.add_audit_result(
            job_id=job_id,
            phrase_group_id=phrase_group_id,
            phrase_text=phrase_text,
            recall=audit.recall,
            missed_count=audit.missed_count,
            recommendations_json=self._mining_store.dump_json(
                [r.model_dump() for r in audit.recommendations]
            ),
            llm_explanation=audit.llm_explanation,
        )
        return audit

    # ── audit_full_dictionary ────────────────────────────────

    async def audit_full_dictionary(
        self,
        dictionary_node: Any,
        job_id: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> List[PhraseGroupAudit]:
        """Audit every PhraseGroup in the dictionary.

        Checkpoint every ``_CHECKPOINT_EVERY`` PhraseGroups. LLM failures
        degrade per-group (audit with empty explanation), the job continues.
        """
        pairs = _gather_phrase_texts(dictionary_node)
        total = len(pairs)
        if total == 0:
            return []

        self._mining_store.update_job(job_id, status="running", total_dialogues=total)
        results: List[PhraseGroupAudit] = []
        processed = 0
        partial = False

        try:
            for pg_id, phrase_text in pairs:
                if self._is_cancelled(job_id):
                    break
                try:
                    audit = await self.audit_phrase_group(pg_id, phrase_text, job_id)
                except Exception as exc:
                    logger.warning(
                        "mining.audit: group %s failed (%s)", pg_id, exc
                    )
                    audit = PhraseGroupAudit(
                        phrase_group_id=pg_id,
                        phrase_text=phrase_text,
                        recall=0.0,
                        missed_count=0,
                        recommendations=[],
                        llm_explanation=f"audit failed: {exc}",
                    )
                    partial = True
                results.append(audit)
                processed += 1
                if processed % _CHECKPOINT_EVERY == 0:
                    self._mining_store.add_checkpoint(job_id, processed, pg_id)
                if progress_cb is not None:
                    progress_cb(processed, total)

            final_status = "cancelled" if self._is_cancelled(job_id) else "completed"
            if partial and final_status == "completed":
                final_status = "partial"
            result = AuditJobResult(phrase_groups=results)
            self._mining_store.update_job(
                job_id,
                status=final_status,
                processed_dialogues=processed,
                completed_at=_now_iso(),
                warning=("LLM failures — partial results" if partial else None),
                result_json=self._mining_store.dump_json(result.model_dump()),
            )
        except Exception as exc:
            logger.exception("mining.audit_full_dictionary failed for job=%s", job_id)
            self._mining_store.update_job(
                job_id, status="failed", error=str(exc), completed_at=_now_iso()
            )
            raise

        return results

    # ── Job status / cancel / checkpoint ─────────────────────

    async def get_job_status(self, job_id: str) -> Optional[MiningJobStatus]:
        """Return the current status of a mining job (or None if not found)."""
        row = self._mining_store.get_job(job_id)
        if row is None:
            return None
        total = int(row["total_dialogues"] or 0)
        processed = int(row["processed_dialogues"] or 0)
        progress = (processed / total) if total > 0 else 0.0
        result_json = row.get("result_json")
        result_payload: Optional[Any] = self._mining_store.load_json(result_json)
        return MiningJobStatus(
            job_id=row["job_id"],
            status=row["status"],  # type: ignore[arg-type]
            job_type=row["job_type"],  # type: ignore[arg-type]
            progress=progress,
            processed_dialogues=processed,
            total_dialogues=total,
            checkpoint_at=row["checkpoint_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            warning=row["warning"],
            result=result_payload,
        )

    async def cancel_job(self, job_id: str) -> bool:
        """Mark a job as cancelled + cancel its asyncio task (if running)."""
        self.cancel_running_task(job_id)
        return self._mining_store.cancel_job(job_id)

    async def checkpoint(
        self,
        job_id: str,
        processed_count: int,
        last_dialogue_id: str,
    ) -> None:
        """Persist a checkpoint row + update the job row (called by long loops)."""
        self._mining_store.add_checkpoint(job_id, processed_count, last_dialogue_id)

    async def resume_from_checkpoint(self, job_id: str) -> Optional[int]:
        """Return the last checkpoint's processed_count, or None if none."""
        return self._mining_store.get_last_checkpoint(job_id)

    # ── Internals ─────────────────────────────────────────────

    def _is_cancelled(self, job_id: str) -> bool:
        """Check whether the job row has been marked cancelled."""
        row = self._mining_store.get_job(job_id)
        if row is None:
            return True  # Job gone — treat as cancelled to stop the loop.
        return row["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════
# Prompt formatting helpers
# ═══════════════════════════════════════════════════════════


def _format_find_fn_user_prompt(dialogue_text: str) -> str:
    return (
        "Диалог:\n"
        f"{dialogue_text}\n\n"
        "Оцени, содержит ли этот диалог фразы, которые должны были match словарём, "
        "но не match. Если да — предложи фразу для добавления."
    )


def _format_audit_user_prompt(phrase_text: str) -> str:
    return (
        "PhraseGroup содержит следующие фразы:\n"
        f"{phrase_text}\n\n"
        "Дай оценку recall, missed_count и рекомендации по улучшению."
    )


# ═══════════════════════════════════════════════════════════
# Result parsing helpers
# ═══════════════════════════════════════════════════════════


def _build_recommendations(raw: Any) -> List[AuditRecommendation]:
    """Build a list of :class:`AuditRecommendation` from LLM JSON output."""
    if not isinstance(raw, list):
        return []
    out: List[AuditRecommendation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rec_type = str(item.get("type") or "").strip().lower()
        if rec_type not in (
            "add_phrase", "remove_phrase", "adjust_word_distance", "add_exception"
        ):
            continue
        phrase = str(item.get("phrase") or "").strip()
        if not phrase:
            continue
        word_distance_raw = item.get("word_distance")
        word_distance: Optional[int]
        if word_distance_raw is None:
            word_distance = None
        else:
            try:
                word_distance = int(word_distance_raw)
            except (TypeError, ValueError):
                word_distance = None
        out.append(
            AuditRecommendation(
                type=rec_type,  # type: ignore[arg-type]
                phrase=phrase,
                reason=str(item.get("reason") or "").strip(),
                word_distance=word_distance,
            )
        )
    return out


def _normalise_channel(speaker: str) -> str:
    """Map a speaker string to CLIENT / OPERATOR / ANY."""
    if not speaker:
        return "ANY"
    s = speaker.strip().lower()
    if "клиент" in s or "client" in s:
        return "CLIENT"
    if "сотрудник" in s or "operator" in s or "employee" in s:
        return "OPERATOR"
    return "ANY"


# ═══════════════════════════════════════════════════════════
# Minimal dialog shim for the FROZEN run_hierarchical_search
# ═══════════════════════════════════════════════════════════


class _PseudoDialog:
    """Minimal duck-typed object exposing ``turns`` for ``run_hierarchical_search``.

    The FROZEN search function reads ``dialog.turns`` (List[DialogueTurn]).
    We rebuild the same shape from a persisted corpus row without modifying
    the frozen ``search.py`` module.
    """

    def __init__(self, turns: List[Any]) -> None:
        self.turns = turns


def _build_turns_for_search(entry: Dict[str, Any]) -> List[Any]:
    """Rebuild minimal DialogueTurn-shaped objects from a corpus row's text.

    The corpus stores the full joined dialogue text; ``run_hierarchical_search``
    only inspects ``turn.text`` / ``turn.speaker`` / ``turn.turn_index``.
    We split on newlines (each non-empty line becomes a turn).
    """
    from app.models import DialogueTurn

    text = entry.get("text") or ""
    channel = entry.get("channel") or "ANY"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    speaker = "Клиент" if channel == "CLIENT" else "Сотрудник" if channel == "OPERATOR" else "Клиент"
    turns: List[DialogueTurn] = []
    for idx, line in enumerate(lines):
        # Toggle speaker for ANY dialogues to mimic alternating dialogue.
        if channel == "ANY":
            speaker = "Клиент" if idx % 2 == 0 else "Сотрудник"
        turns.append(
            DialogueTurn(turn_index=idx, speaker=speaker, text=line, timestamp=None)
        )
    return turns

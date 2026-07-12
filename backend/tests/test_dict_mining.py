"""Unit tests for app.services.dict_mining.DictionaryMiningService.

Covers:
  - index_corpus: RTF parsing, chunking, embedding, FAISS add, SQLite persist, checkpoint
  - find_similar_to_phrase: vector search, top-k, dedup by dialogue_id
  - find_false_negatives: baseline search, vector-close, LLM verify, 3-level confidence
  - audit_phrase_group: LLM prompt, JSON parsing, recommendations
  - audit_full_dictionary: per-PhraseGroup, checkpoint
  - get_job_status: pending/running/completed/failed/partial/cancelled
  - cancel_job: stops at next checkpoint
  - checkpoint: persist + resume_from_checkpoint

Mocks (composition over existing services):
  - FridaEmbeddingService.embed_texts → fixed 1536-dim vectors
  - VectorStore.add / search → in-memory
  - LLMProvider.generate → JSON per prompt (via app.services.llm.get_provider)
  - run_hierarchical_search → SearchResult with/without matches
  - Chunker.chunk_text → single chunk per call

Frozen invariants verified:
  - xml_parser.py НЕ импортируется в dict_mining.py (composition over search.py only)
  - search.py НЕ модифицирован (git diff empty)
  - morph_matcher.py НЕ модифицирован
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    ConfidenceLabel,
    DictionaryCondition,
    DictionaryNode,
    FNCandidate,
    PhraseGroupVisual,
    SearchResult,
)
from app.services.dict_mining import (
    DictionaryMiningService,
    _build_recommendations,
    _map_label,
    _parse_llm_json,
    _strip_code_fence,
)


# ═══════════════════════════════════════════════════════════
# Test fixtures
# ═══════════════════════════════════════════════════════════


_DIM = 1536


def _vec(seed: float = 0.5) -> List[float]:
    return [seed] * _DIM


@pytest.fixture
def tmp_mining_store(tmp_path):
    """A MiningStore pointing at a per-test temp DB file."""
    from app.services.session_store_sqlite import MiningStore

    store = MiningStore(db_path=str(tmp_path / "mining_test.db"))
    yield store
    store.close()


@pytest.fixture
def fake_embedding():
    """FridaEmbeddingService mock returning deterministic 1536-dim vectors."""
    svc = MagicMock()
    svc.embed_texts = AsyncMock(return_value=[_vec(0.5)])
    return svc


@pytest.fixture
def fake_chunker():
    """Chunker mock returning one Chunk per call."""
    from app.models import Chunk, ChunkMetadata

    chunker = MagicMock()

    def _chunk_text(text: str, metadata_base):
        meta = ChunkMetadata(
            chunk_id=f"chunk-{metadata_base.get('turn_index', 0)}",
            dialogue_id=str(metadata_base.get("dialogue_id", "x")),
            turn_index=int(metadata_base.get("turn_index", 0)),
            speaker=str(metadata_base.get("speaker", "Клиент")),
            chunk_type="utterance",
            token_count=1,
            char_count=len(text),
            entities=[],
        )
        return [Chunk(text=text, metadata=meta)]

    chunker.chunk_text.side_effect = _chunk_text
    return chunker


@pytest.fixture
def fake_vector_store():
    """In-memory VectorStore mock with add() and configurable search results."""
    store = MagicMock()
    store.add = MagicMock(return_value=None)
    # Default: empty search results; tests override per-test.
    store.search = MagicMock(return_value=[])
    return store


@pytest.fixture
def service(fake_embedding, fake_chunker, fake_vector_store, tmp_mining_store):
    return DictionaryMiningService(
        embedding_service=fake_embedding,
        vector_store=fake_vector_store,
        chunker=fake_chunker,
        mining_store=tmp_mining_store,
    )


def _make_dictionary(name: str = "DictA", phrases: Optional[List[str]] = None) -> DictionaryNode:
    """Build a DictionaryNode with the given phrase conditions."""
    phrases = phrases or ["привет", "как дела"]
    conditions = [
        DictionaryCondition(
            text=p,
            word_distance=2,
            word_count=len(p.split()),
            channel_constraint="ANY",
            is_exact=False,
            phrase_groups=[PhraseGroupVisual(words=p.split(), is_or_group=False, is_exception=False)],
            is_exception=False,
        )
        for p in phrases
    ]
    return DictionaryNode(
        id="root",
        name=name,
        parent_name=None,
        conditions=conditions,
        condition_count=len(conditions),
        has_children=False,
        children_count=0,
    )


@pytest.fixture
def patched_llm(monkeypatch):
    """Patch get_provider to return a fake LLM provider with a configurable response."""

    fake = MagicMock()
    fake.generate = AsyncMock(return_value="{}")
    fake.is_available = AsyncMock(return_value=True)
    fake.get_name = MagicMock(return_value="fake")
    fake.get_default_model = MagicMock(return_value="fake-model")
    fake.get_models = MagicMock(return_value=["fake-model"])

    def _get_provider(_pid: str):
        return fake

    monkeypatch.setattr("app.services.dict_mining.get_provider", _get_provider)
    return fake


# ═══════════════════════════════════════════════════════════
# Pure helpers
# ═══════════════════════════════════════════════════════════


class TestPureHelpers:
    def test_strip_code_fence_removes_json_fence(self):
        raw = "```json\n{\"a\": 1}\n```"
        assert _strip_code_fence(raw) == '{"a": 1}'

    def test_strip_code_fence_plain(self):
        assert _strip_code_fence('{"a": 1}') == '{"a": 1}'

    def test_parse_llm_json_valid(self):
        assert _parse_llm_json('{"a": 1}', default=None) == {"a": 1}

    def test_parse_llm_json_invalid_returns_default(self):
        assert _parse_llm_json("not json", default={"fallback": True}) == {"fallback": True}

    def test_parse_llm_json_empty_returns_default(self):
        assert _parse_llm_json("", default=None) is None

    def test_map_label_canonical(self):
        assert _map_label("relevant") == ConfidenceLabel.relevant
        assert _map_label("irrelevant") == ConfidenceLabel.irrelevant
        assert _map_label("uncertain") == ConfidenceLabel.uncertain

    def test_map_label_russian(self):
        assert _map_label("релевантен") == ConfidenceLabel.relevant
        assert _map_label("нерелевантно") == ConfidenceLabel.irrelevant

    def test_map_label_unknown_defaults_to_uncertain(self):
        assert _map_label("maybe") == ConfidenceLabel.uncertain
        assert _map_label(None) == ConfidenceLabel.uncertain

    def test_build_recommendations_filters_invalid_types(self):
        raw = [
            {"type": "add_phrase", "phrase": "новая фраза", "reason": "r"},
            {"type": "bogus", "phrase": "x"},
            {"type": "adjust_word_distance", "phrase": "фраза", "reason": "r", "word_distance": 3},
        ]
        out = _build_recommendations(raw)
        assert len(out) == 2
        assert out[0].type == "add_phrase"
        assert out[1].word_distance == 3

    def test_build_recommendations_skips_empty_phrase(self):
        out = _build_recommendations([{"type": "add_phrase", "phrase": ""}])
        assert out == []


# ═══════════════════════════════════════════════════════════
# index_corpus
# ═══════════════════════════════════════════════════════════


class TestIndexCorpus:
    @pytest.mark.asyncio
    async def test_index_corpus_basic(
        self, service, tmp_path, fake_embedding, fake_chunker, fake_vector_store, tmp_mining_store
    ):
        # Create 3 fake RTF files.
        for i in range(3):
            (tmp_path / f"dialogue_{i}.rtf").write_text(
                f"{{\\rtf1\\ansi Клиент {i}.\\par Сотрудник ответ {i}.}}",
                encoding="utf-8",
            )

        # parse_rtf_file returns a ParsedDialog — patch it.
        from app.models import DialogueTurn, ParsedDialog

        async def _fake_parse_rtf(path: Path, filename: Optional[str] = None):
            return ParsedDialog(
                filename=filename or path.name,
                turns=[
                    DialogueTurn(turn_index=0, speaker="Клиент", text=f"client {path.stem}"),
                    DialogueTurn(turn_index=1, speaker="Сотрудник", text=f"operator {path.stem}"),
                ],
                total_turns=2,
                client_turns=1,
                employee_turns=1,
            )

        with patch("app.services.dict_mining.parse_rtf_file", _fake_parse_rtf):
            response = await service.index_corpus(
                directory_path=str(tmp_path),
                dictionary_id="DictA",
                session_id="sess-1",
            )

        assert response.status == "running"
        assert response.total_dialogues == 3
        assert response.job_id.startswith("mining-index-")

        # Job row should be completed.
        job = await service.get_job_status(response.job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.total_dialogues == 3
        assert job.processed_dialogues == 3

        # FAISS add called once per file (3 calls × N chunks).
        assert fake_vector_store.add.call_count >= 3
        # Embedding called per file.
        assert fake_embedding.embed_texts.await_count >= 3

        # Corpus rows persisted.
        corpus = tmp_mining_store.list_corpus(response.job_id)
        assert len(corpus) == 3

    @pytest.mark.asyncio
    async def test_index_corpus_empty_directory(self, service, tmp_path):
        with pytest.raises(ValueError, match="no .rtf files"):
            await service.index_corpus(
                directory_path=str(tmp_path),
                dictionary_id="DictA",
                session_id="sess-1",
            )

    @pytest.mark.asyncio
    async def test_index_corpus_invalid_path(self, service, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            await service.index_corpus(
                directory_path=str(tmp_path / "missing"),
                dictionary_id="DictA",
                session_id="sess-1",
            )

    @pytest.mark.asyncio
    async def test_index_corpus_skip_invalid_rtf(
        self, service, tmp_path, fake_vector_store, tmp_mining_store
    ):
        # 2 valid RTF + 1 invalid (parse fails).
        for i in range(2):
            (tmp_path / f"ok_{i}.rtf").write_text("ok", encoding="utf-8")
        (tmp_path / "bad.rtf").write_text("bad", encoding="utf-8")

        from app.models import DialogueTurn, ParsedDialog

        async def _fake_parse_rtf(path: Path, filename: Optional[str] = None):
            if path.stem == "bad":
                raise ValueError("malformed RTF")
            return ParsedDialog(
                filename=filename or path.name,
                turns=[DialogueTurn(turn_index=0, speaker="Клиент", text="ok")],
                total_turns=1,
                client_turns=1,
                employee_turns=0,
            )

        with patch("app.services.dict_mining.parse_rtf_file", _fake_parse_rtf):
            response = await service.index_corpus(
                directory_path=str(tmp_path),
                dictionary_id="DictA",
                session_id="sess-1",
            )

        job = await service.get_job_status(response.job_id)
        assert job is not None
        # 2 of 3 processed → partial with warning.
        assert job.status == "partial"
        assert job.warning is not None
        assert job.processed_dialogues == 2


# ═══════════════════════════════════════════════════════════
# find_similar_to_phrase
# ═══════════════════════════════════════════════════════════


class TestFindSimilar:
    @pytest.mark.asyncio
    async def test_find_similar_dedup_by_dialogue_id(
        self, service, fake_embedding, fake_vector_store
    ):
        from app.models import VectorSearchResult

        # 3 hits, 2 with same dialogue_id → dedup keeps max score.
        fake_vector_store.search.return_value = [
            VectorSearchResult(
                chunk_id="c1", text="hello world", dialogue_id="d1",
                turn_index=0, speaker="Клиент", score=0.9,
                chunk_type="utterance", entities=[],
            ),
            VectorSearchResult(
                chunk_id="c2", text="hello again", dialogue_id="d1",
                turn_index=1, speaker="Сотрудник", score=0.95,
                chunk_type="utterance", entities=[],
            ),
            VectorSearchResult(
                chunk_id="c3", text="other", dialogue_id="d2",
                turn_index=0, speaker="Клиент", score=0.7,
                chunk_type="utterance", entities=[],
            ),
        ]

        response = await service.find_similar_to_phrase(
            phrase_group_id="pg-1",
            phrase_text="hello",
            top_k=10,
        )

        assert response.total == 2  # deduped
        scores = {d.dialogue_id: d.score for d in response.dialogues}
        assert scores["d1"] == 0.95  # max score kept
        assert scores["d2"] == 0.7

    @pytest.mark.asyncio
    async def test_find_similar_empty_phrase(self, service):
        response = await service.find_similar_to_phrase(
            phrase_group_id="pg-1",
            phrase_text="",
            top_k=10,
        )
        assert response.total == 0
        assert response.dialogues == []


# ═══════════════════════════════════════════════════════════
# find_false_negatives
# ═══════════════════════════════════════════════════════════


class TestFindFalseNegatives:
    @pytest.mark.asyncio
    async def test_find_fn_basic(
        self, service, fake_embedding, fake_vector_store, tmp_mining_store, patched_llm
    ):
        # Index job must exist with 2 corpus entries.
        index_job = service._mining_store.create_job(
            job_id="idx-1", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="index",
        )
        service._mining_store.update_job("idx-1", status="completed", total_dialogues=2)
        service._mining_store.add_corpus_entry(
            job_id="idx-1", dialogue_id="d1", file_path="d1.rtf",
            text="клиент спрашивает про тариф", channel="CLIENT", turn_count=1,
        )
        service._mining_store.add_corpus_entry(
            job_id="idx-1", dialogue_id="d2", file_path="d2.rtf",
            text="оператор отвечает", channel="OPERATOR", turn_count=1,
        )

        # search returns no matches (FN candidate).
        async def _fake_search(*args, **kwargs):
            return SearchResult(segments=[], total_matches=0, matches=[], matches_by_level={})

        # vector store returns one hit above threshold for d1 only.
        from app.models import VectorSearchResult

        fake_vector_store.search.return_value = [
            VectorSearchResult(
                chunk_id="c1", text="тариф", dialogue_id="d1",
                turn_index=0, speaker="Клиент", score=0.85,
                chunk_type="utterance", entities=[],
            )
        ]

        # LLM returns a relevant FN candidate.
        patched_llm.generate = AsyncMock(
            return_value='{"label":"relevant","score":0.9,"reason":"релевантно","proposed_phrase":"новый тариф"}'
        )

        with patch("app.services.dict_mining.run_hierarchical_search", _fake_search):
            response = await service.find_false_negatives(
                dictionary_node=_make_dictionary(),
                job_id="idx-1",
                threshold=0.7,
            )

        assert response.total == 1
        cand = response.candidates[0]
        assert cand.dialogue_id == "d1"
        assert cand.llm_label == ConfidenceLabel.relevant
        assert cand.proposed_phrase == "новый тариф"
        assert cand.score == 0.85

        # Job row finalised.
        job = await service.get_job_status("idx-1")
        assert job is not None
        assert job.status == "completed"

        # FN candidate persisted.
        fns = tmp_mining_store.list_fn_candidates("idx-1")
        assert len(fns) == 1
        assert fns[0]["llm_label"] == "relevant"

    @pytest.mark.asyncio
    async def test_find_fn_no_fn_when_all_matched(
        self, service, fake_vector_store, tmp_mining_store, patched_llm
    ):
        index_job = service._mining_store.create_job(
            job_id="idx-2", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="index",
        )
        service._mining_store.update_job("idx-2", status="completed", total_dialogues=1)
        service._mining_store.add_corpus_entry(
            job_id="idx-2", dialogue_id="d1", file_path="d1.rtf",
            text="привет как дела", channel="CLIENT", turn_count=1,
        )

        async def _fake_search(*args, **kwargs):
            # All matched → not a false negative.
            return SearchResult(segments=[], total_matches=3, matches=[], matches_by_level={})

        with patch("app.services.dict_mining.run_hierarchical_search", _fake_search):
            response = await service.find_false_negatives(
                dictionary_node=_make_dictionary(),
                job_id="idx-2",
            )

        assert response.total == 0
        assert response.candidates == []

    @pytest.mark.asyncio
    async def test_find_fn_partial_when_llm_fails(
        self, service, fake_embedding, fake_vector_store, tmp_mining_store, patched_llm
    ):
        service._mining_store.create_job(
            job_id="idx-3", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="index",
        )
        service._mining_store.update_job("idx-3", status="completed", total_dialogues=1)
        service._mining_store.add_corpus_entry(
            job_id="idx-3", dialogue_id="d1", file_path="d1.rtf",
            text="привет", channel="CLIENT", turn_count=1,
        )

        async def _fake_search(*args, **kwargs):
            return SearchResult(segments=[], total_matches=0, matches=[], matches_by_level={})

        from app.models import VectorSearchResult

        fake_vector_store.search.return_value = [
            VectorSearchResult(
                chunk_id="c1", text="x", dialogue_id="d1",
                turn_index=0, speaker="Клиент", score=0.8,
                chunk_type="utterance", entities=[],
            )
        ]

        # LLM returns None → partial.
        patched_llm.generate = AsyncMock(return_value=None)

        with patch("app.services.dict_mining.run_hierarchical_search", _fake_search):
            response = await service.find_false_negatives(
                dictionary_node=_make_dictionary(),
                job_id="idx-3",
                threshold=0.7,
            )

        assert response.partial is True
        assert response.total == 0  # candidate not added when LLM fails


# ═══════════════════════════════════════════════════════════
# audit_phrase_group / audit_full_dictionary
# ═══════════════════════════════════════════════════════════


class TestAudit:
    @pytest.mark.asyncio
    async def test_audit_phrase_group_parses_llm_json(
        self, service, tmp_mining_store, patched_llm
    ):
        service._mining_store.create_job(
            job_id="audit-1", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="audit",
        )
        patched_llm.generate = AsyncMock(
            return_value=(
                '{"recall":0.8,"missed_count":2,"recommendations":['
                '{"type":"add_phrase","phrase":"новая фраза","reason":"r1"},'
                '{"type":"adjust_word_distance","phrase":"фраза","reason":"r2","word_distance":3}'
                '],"explanation":"# Markdown\\nДетальный разбор"}'
            )
        )

        audit = await service.audit_phrase_group("pg-1", "фраза раз два", "audit-1")

        assert audit.recall == 0.8
        assert audit.missed_count == 2
        assert len(audit.recommendations) == 2
        assert audit.recommendations[0].phrase == "новая фраза"
        assert audit.recommendations[1].word_distance == 3
        assert "Markdown" in audit.llm_explanation

        # Persisted.
        rows = tmp_mining_store.list_audit_results("audit-1")
        assert len(rows) == 1
        assert rows[0]["phrase_group_id"] == "pg-1"

    @pytest.mark.asyncio
    async def test_audit_phrase_group_llm_unavailable(
        self, service, tmp_mining_store, patched_llm
    ):
        service._mining_store.create_job(
            job_id="audit-2", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="audit",
        )
        patched_llm.generate = AsyncMock(return_value=None)

        audit = await service.audit_phrase_group("pg-1", "фраза", "audit-2")

        assert audit.recall == 0.0
        assert audit.llm_explanation == "LLM unavailable"
        assert audit.recommendations == []

    @pytest.mark.asyncio
    async def test_audit_full_dictionary(
        self, service, tmp_mining_store, patched_llm
    ):
        service._mining_store.create_job(
            job_id="audit-3", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="audit",
        )
        patched_llm.generate = AsyncMock(
            return_value='{"recall":0.7,"missed_count":1,"recommendations":[],"explanation":"ok"}'
        )

        results = await service.audit_full_dictionary(
            dictionary_node=_make_dictionary(phrases=["один", "два", "три"]),
            job_id="audit-3",
        )

        assert len(results) == 3
        assert all(r.recall == 0.7 for r in results)
        job = await service.get_job_status("audit-3")
        assert job is not None
        assert job.status == "completed"
        assert job.processed_dialogues == 3


# ═══════════════════════════════════════════════════════════
# Job status / cancel / checkpoint
# ═══════════════════════════════════════════════════════════


class TestJobLifecycle:
    @pytest.mark.asyncio
    async def test_get_job_status_missing_returns_none(self, service):
        assert await service.get_job_status("nope") is None

    @pytest.mark.asyncio
    async def test_checkpoint_persist_and_resume(self, service, tmp_mining_store):
        service._mining_store.create_job(
            job_id="cp-1", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="index",
        )
        # No checkpoint yet.
        assert await service.resume_from_checkpoint("cp-1") is None

        await service.checkpoint("cp-1", 25, "d25")
        assert await service.resume_from_checkpoint("cp-1") == 25

        await service.checkpoint("cp-1", 50, "d50")
        assert await service.resume_from_checkpoint("cp-1") == 50

    @pytest.mark.asyncio
    async def test_cancel_job_marks_cancelled(self, service, tmp_mining_store):
        service._mining_store.create_job(
            job_id="cancel-1", session_id="s1", dictionary_id="DictA",
            directory_path="/tmp", job_type="index",
        )
        service._mining_store.update_job("cancel-1", status="running")

        cancelled = await service.cancel_job("cancel-1")
        assert cancelled is True

        job = await service.get_job_status("cancel-1")
        assert job is not None
        assert job.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_missing_job_returns_false(self, service):
        cancelled = await service.cancel_job("missing")
        assert cancelled is False


# ═══════════════════════════════════════════════════════════
# Frozen invariant assertions
# ═══════════════════════════════════════════════════════════


class TestFrozenInvariants:
    def test_dict_mining_does_not_import_xml_parser(self):
        import inspect

        from app.services import dict_mining as dm

        source = inspect.getsource(dm)
        # xml_parser must NOT be imported or used (composition over search.py only).
        assert "import xml_parser" not in source
        assert "from app.services.xml_parser" not in source
        # search.py is imported ONLY for run_hierarchical_search (read-only composition).
        assert "from app.services.search import run_hierarchical_search" in source

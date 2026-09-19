"""Tests for the local TF-IDF embedding provider (Wave 1 offline fallback).

Covers:
  - Unit: LocalTfidfEmbeddingService (tokenization, determinism, vocabulary
    cap, normalization, OOV handling, save/load persistence, stats).
  - Unit: embedding provider switch (EMBEDDING_PROVIDER=frida|local|auto)
    including the auto-fallback path when FRIDA is unreachable.
  - Integration: full index + search round-trip with NO network —
    LocalTfidfEmbeddingService + VectorStore + HybridSearchService.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.embedding import FridaEmbeddingService
from app.services.embedding_factory import (
    _normalize_mode,
    provider_status,
    resolve_embedding_service,
)
from app.services.hybrid_search import HybridSearchService
from app.services.local_embedding import LocalTfidfEmbeddingService
from app.services.vector_store import VectorStore

# ── Russian test corpus (dialogue-like texts) ──────────────────────

_DOC_TARIFF = (
    "Добрый день, меня интересует подключение тарифа безлимитный интернет. "
    "Сколько стоит переход на новый тариф и какие условия?"
)
_DOC_ROAMING = (
    "Здравствуйте, я поехал за границу и у меня не работает роуминг. "
    "Не могу позвонить и интернет не ловит за рубежом."
)
_DOC_BLOCKED = (
    "Мой номер заблокирован, не могу совершать исходящие звонки. "
    "Почему заблокировали сим карту и как разблокировать?"
)
_DOC_DELIVERY = (
    "Хочу уточнить сроки доставки сим карты курьером. "
    "Когда привезут заказанный пакет документов?"
)

_CORPUS = [_DOC_TARIFF, _DOC_ROAMING, _DOC_BLOCKED, _DOC_DELIVERY]


def _norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


# ═══════════════════════════════════════════════════════════
# Unit: LocalTfidfEmbeddingService
# ═══════════════════════════════════════════════════════════


class TestLocalTfidfUnit:
    def test_embed_before_fit_returns_zero_vector(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=32)
        vec = asyncio.run(svc.embed("привет мир"))
        assert len(vec) == 32
        assert all(x == 0.0 for x in vec)

    async def test_embed_batch_fits_and_returns_nonzero(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=128)
        vectors = await svc.embed_batch(_CORPUS)
        assert len(vectors) == len(_CORPUS)
        for vec in vectors:
            assert len(vec) == 128
            assert _norm(vec) == pytest.approx(1.0, abs=1e-5)
        # Vocab must have grown from the corpus
        assert svc.vocab_size > 0
        assert svc.get_stats()["n_docs_fitted"] == len(_CORPUS)

    async def test_query_after_batch_is_in_same_space(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=128)
        await svc.embed_batch(_CORPUS)
        query_vec = await svc.embed("тариф интернет подключение")
        assert len(query_vec) == 128
        assert _norm(query_vec) == pytest.approx(1.0, abs=1e-5)

    async def test_embed_does_not_mutate_fitted_state(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=128)
        await svc.embed_batch(_CORPUS)
        vocab_before = svc.vocab_size
        docs_before = svc.get_stats()["n_docs_fitted"]
        await svc.embed("абсолютно новый запрос с невиданными словами")
        assert svc.vocab_size == vocab_before
        assert svc.get_stats()["n_docs_fitted"] == docs_before

    def test_deterministic_same_corpus_same_vectors(self) -> None:
        svc1 = LocalTfidfEmbeddingService(dimension=256)
        svc2 = LocalTfidfEmbeddingService(dimension=256)
        v1 = asyncio.run(svc1.embed_batch(_CORPUS))
        v2 = asyncio.run(svc2.embed_batch(_CORPUS))
        assert v1 == v2

    def test_vocabulary_is_sorted(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=256)
        asyncio.run(svc.embed_batch(_CORPUS))
        assert svc._vocab == sorted(svc._vocab)

    def test_vocabulary_cap_freezes_growth(self) -> None:
        # dimension=4 → only 4 distinct tokens fit
        svc = LocalTfidfEmbeddingService(dimension=4)
        added = asyncio.run(svc.embed_batch(["один два три четыре пять шесть"]))
        # All vectors must still be of length 4
        vec = asyncio.run(svc.embed("один два"))
        assert len(vec) == 4
        # Fitting more texts cannot extend the vocabulary beyond the cap
        asyncio.run(svc.embed_batch(["ещё больше совершенно новых слов"]))
        assert svc.vocab_size <= 4

    async def test_is_available_always_true(self) -> None:
        svc = LocalTfidfEmbeddingService()
        assert await svc.is_available() is True

    def test_stats_shape(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=64)
        asyncio.run(svc.embed_batch(_CORPUS))
        stats = svc.get_stats()
        assert stats["provider"] == "local"
        assert stats["dimension"] == 64
        assert stats["vocab_size"] > 0
        assert stats["n_docs_fitted"] == len(_CORPUS)

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        svc = LocalTfidfEmbeddingService(dimension=256)
        asyncio.run(svc.embed_batch(_CORPUS))
        query = "подключение тарифа"
        vec_before = asyncio.run(svc.embed(query))
        svc.save(str(tmp_path))

        restored = LocalTfidfEmbeddingService(dimension=256)
        assert restored.load(str(tmp_path)) is True
        vec_after = asyncio.run(restored.embed(query))
        assert vec_before == vec_after

    def test_load_missing_file_returns_false(self, tmp_path: Path) -> None:
        svc = LocalTfidfEmbeddingService(dimension=256)
        assert svc.load(str(tmp_path)) is False

    def test_load_dimension_mismatch_is_ignored(self, tmp_path: Path) -> None:
        svc = LocalTfidfEmbeddingService(dimension=128)
        asyncio.run(svc.embed_batch(_CORPUS))
        svc.save(str(tmp_path))
        other = LocalTfidfEmbeddingService(dimension=256)
        assert other.load(str(tmp_path)) is False

    def test_embed_texts_alias(self) -> None:
        svc = LocalTfidfEmbeddingService(dimension=128)
        via_alias = asyncio.run(svc.embed_texts(_CORPUS))
        assert len(via_alias) == len(_CORPUS)


# ═══════════════════════════════════════════════════════════
# Regression (MAJOR-1): append-only vocabulary / cross-batch stability
# ═══════════════════════════════════════════════════════════


class TestCrossBatchIndexStability:
    """MAJOR-1 regression: partial_fit used to re-sort the full vocabulary,
    shifting indices of already-embedded tokens. FAISS vectors stored
    earlier became misaligned with new query vectors — an exact-match
    query returned cosine 0.0 after a second batch was indexed.

    The vocabulary must be append-only: once a token gets an index, it
    never changes; IDF weights are frozen at first fit.
    """

    _BATCH_B = [
        "Абонент просит справку счёт и детализацию начислений",
        "Бонусные баллы начислены за своевременную оплату связи",
    ]

    async def test_exact_match_query_retains_similarity_after_second_batch(
        self,
    ) -> None:
        """Reviewer's repro: embed batch A → embed batch B (new tokens) →
        query identical to doc1 must keep cosine >= 0.99 against doc1's
        vector stored from batch A."""
        svc = LocalTfidfEmbeddingService(dimension=256)
        vectors_a = await svc.embed_batch(_CORPUS)
        stored_doc1 = vectors_a[0]

        await svc.embed_batch(self._BATCH_B)

        query_vec = await svc.embed(_DOC_TARIFF)
        # Both vectors are L2-normalized → dot product == cosine.
        cosine = sum(a * b for a, b in zip(stored_doc1, query_vec))
        assert cosine >= 0.99

    async def test_token_indices_never_shift_after_new_batches(self) -> None:
        """New tokens sorting alphabetically BEFORE existing ones must not
        re-index anything (this is exactly what the old re-sort broke)."""
        svc = LocalTfidfEmbeddingService(dimension=256)
        await svc.embed_batch(_CORPUS)
        indices_before = dict(svc._token_to_idx)
        assert len(indices_before) > 0

        # Tokens starting with 'а'/'б' sort before most of batch A's tokens.
        await svc.embed_batch(["аарон абонент бонус валюта график"])

        for tok, idx in indices_before.items():
            assert svc._token_to_idx[tok] == idx

    async def test_same_text_reembedded_is_identical_vector(self) -> None:
        """Frozen-IDF + stable indices ⇒ a previously embedded text
        re-embedded later yields the exact same vector."""
        svc = LocalTfidfEmbeddingService(dimension=256)
        vectors_a = await svc.embed_batch(_CORPUS)

        await svc.embed_batch(self._BATCH_B)

        again = await svc.embed(_DOC_TARIFF)
        assert again == vectors_a[0]

    async def test_cap_freeze_keeps_existing_indices_stable(self) -> None:
        """Vocabulary frozen at the dimension cap: no new tokens, and the
        indices of already-fitted tokens must not move either."""
        svc = LocalTfidfEmbeddingService(dimension=4)
        await svc.embed_batch(["один два три четыре пять шесть"])
        indices_before = dict(svc._token_to_idx)
        assert 0 < svc.vocab_size <= 4

        await svc.embed_batch(["ещё больше совершенно новых слов"])

        assert svc.vocab_size <= 4
        for tok, idx in indices_before.items():
            assert svc._token_to_idx[tok] == idx

    def test_save_load_preserves_insertion_order_multibatch(
        self, tmp_path: Path
    ) -> None:
        """load() must restore the vocabulary in saved insertion order
        (no re-sort): a multi-batch (unsorted) vocab round-trips exactly."""
        svc = LocalTfidfEmbeddingService(dimension=256)
        asyncio.run(svc.embed_batch(_CORPUS))
        asyncio.run(svc.embed_batch(self._BATCH_B))
        # Multi-batch vocab is append-only, hence NOT globally sorted —
        # exactly the case the old re-sorting load() would corrupt.
        assert svc._vocab != sorted(svc._vocab)
        query = _DOC_TARIFF
        vec_before = asyncio.run(svc.embed(query))
        svc.save(str(tmp_path))

        restored = LocalTfidfEmbeddingService(dimension=256)
        assert restored.load(str(tmp_path)) is True
        assert restored._vocab == svc._vocab
        vec_after = asyncio.run(restored.embed(query))
        assert vec_before == vec_after


# ═══════════════════════════════════════════════════════════
# Unit: provider switch (EMBEDDING_PROVIDER=frida|local|auto)
# ═══════════════════════════════════════════════════════════


class TestProviderSwitch:
    def test_normalize_mode_valid_values(self) -> None:
        assert _normalize_mode("frida") == "frida"
        assert _normalize_mode("local") == "local"
        assert _normalize_mode("auto") == "auto"

    def test_normalize_mode_invalid_falls_back_to_auto(self) -> None:
        assert _normalize_mode("gpt-4") == "auto"
        assert _normalize_mode("") == "auto"

    async def test_local_mode_returns_local_service(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "embedding_provider", "local")
        service, provider, mode = await resolve_embedding_service()
        assert isinstance(service, LocalTfidfEmbeddingService)
        assert provider == "local"
        assert mode == "local"

    async def test_frida_mode_returns_frida_service(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "embedding_provider", "frida")
        service, provider, mode = await resolve_embedding_service()
        try:
            assert isinstance(service, FridaEmbeddingService)
            assert provider == "frida"
            assert mode == "frida"
        finally:
            await service.http_client.aclose()

    async def test_auto_falls_back_to_local_when_frida_unavailable(
        self, monkeypatch
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "embedding_provider", "auto")

        async def unavailable(self) -> bool:
            return False

        monkeypatch.setattr(FridaEmbeddingService, "is_available", unavailable)
        service, provider, mode = await resolve_embedding_service()
        assert isinstance(service, LocalTfidfEmbeddingService)
        assert provider == "local"
        assert mode == "auto"

    async def test_auto_falls_back_to_local_on_probe_timeout(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "embedding_provider", "auto")
        monkeypatch.setattr(settings, "embedding_probe_timeout", 0.2)

        async def hang(self) -> bool:
            await asyncio.sleep(30.0)
            return True

        monkeypatch.setattr(FridaEmbeddingService, "is_available", hang)
        service, provider, mode = await resolve_embedding_service()
        assert isinstance(service, LocalTfidfEmbeddingService)
        assert provider == "local"

    async def test_auto_prefers_frida_when_available(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "embedding_provider", "auto")

        async def available(self) -> bool:
            return True

        monkeypatch.setattr(FridaEmbeddingService, "is_available", available)
        service, provider, mode = await resolve_embedding_service()
        try:
            assert isinstance(service, FridaEmbeddingService)
            assert provider == "frida"
            assert mode == "auto"
        finally:
            await service.http_client.aclose()

    def test_provider_status_reads_app_state(self) -> None:
        state = SimpleNamespace(embedding_provider="local", embedding_mode="auto")
        assert provider_status(state) == {"provider": "local", "mode": "auto"}

    def test_provider_status_defaults_without_state(self) -> None:
        state = SimpleNamespace()
        status = provider_status(state)
        assert status["provider"] == "frida"
        assert status["mode"] == "unknown"


# ═══════════════════════════════════════════════════════════
# Integration: fully local index + search round-trip (no network)
# ═══════════════════════════════════════════════════════════


class TestLocalSemanticSearchRoundTrip:
    async def test_index_and_search_finds_relevant_doc(self) -> None:
        """Full offline round-trip: TF-IDF embed → VectorStore.add → search."""
        dim = 512
        svc = LocalTfidfEmbeddingService(dimension=dim)
        store = VectorStore(dimension=dim)

        embeddings = await svc.embed_batch(_CORPUS)
        metadata = [
            {
                "chunk_id": f"chunk_{i}",
                "dialogue_id": f"dialog_{i}",
                "text": text,
                "turn_index": 0,
                "speaker": "client",
                "chunk_type": "turn",
                "entities": [],
            }
            for i, text in enumerate(_CORPUS)
        ]
        store.add(embeddings, metadata)
        assert store.get_stats()["total_vectors"] == len(_CORPUS)

        # Query about tariffs must rank the tariff document first
        query_vec = await svc.embed("как подключить безлимитный тариф на интернет")
        results = store.search(query_vec, k=4)

        assert len(results) >= 1
        assert _DOC_TARIFF in results[0].text
        assert results[0].score > 0.0

    async def test_hybrid_search_semantic_path_works_locally(self) -> None:
        """HybridSearchService._semantic_search degrades to a fully
        functional local mode when the embedding service is the local
        TF-IDF provider (is_available() is always True, no network)."""
        dim = 512
        svc = LocalTfidfEmbeddingService(dimension=dim)
        store = VectorStore(dimension=dim)

        embeddings = await svc.embed_batch(_CORPUS)
        metadata = [
            {
                "chunk_id": f"chunk_{i}",
                "dialogue_id": f"dialog_{i}",
                "text": text,
                "turn_index": 0,
                "speaker": "client",
                "chunk_type": "turn",
                "entities": [],
            }
            for i, text in enumerate(_CORPUS)
        ]
        store.add(embeddings, metadata)

        hybrid = HybridSearchService(
            embedding_service=svc,
            vector_store=store,
        )

        results = await hybrid._semantic_search("роуминг за границей", top_k=3)
        assert len(results) >= 1
        assert _DOC_ROAMING in results[0].text

    async def test_indexed_dialogue_survives_delete_and_reindex(self) -> None:
        """Vector store transactional delete works with local vectors too."""
        dim = 256
        svc = LocalTfidfEmbeddingService(dimension=dim)
        store = VectorStore(dimension=dim)

        embeddings = await svc.embed_batch([_DOC_TARIFF, _DOC_ROAMING])
        metadata = [
            {
                "chunk_id": "c0",
                "dialogue_id": "d0",
                "text": _DOC_TARIFF,
                "turn_index": 0,
                "speaker": "client",
                "chunk_type": "turn",
                "entities": [],
            },
            {
                "chunk_id": "c1",
                "dialogue_id": "d1",
                "text": _DOC_ROAMING,
                "turn_index": 0,
                "speaker": "client",
                "chunk_type": "turn",
                "entities": [],
            },
        ]
        store.add(embeddings, metadata)

        removed = store.delete_by_dialogue("d0")
        assert removed == 1
        assert store.has_dialogue("d0") is False
        assert store.has_dialogue("d1") is True

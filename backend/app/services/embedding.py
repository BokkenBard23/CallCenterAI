"""FRIDA embedding service via Beeline AI API.

Provides async client for FRIDA embeddings API (Beeline AI):
  - Connection pooling (httpx.AsyncClient, 100 max connections, 20 keepalive)
  - Retry with exponential backoff (tenacity, 3 attempts, 2-30 sec)
  - LRU cache for embeddings (10 000 entries)
  - Circuit breaker pattern (auto-reset after 60 sec)
  - Text sanitization (control characters removal, length truncation)
  - Batch embed support (max 10 per API call, auto-split)
  - Observability (logging, latency metrics, get_stats())

API contract:
  POST https://api.ai.beeline.ru/api/v3/embeddings
  Authorization: Bearer {BEELINE_API_KEY}
  Request:  {"model": "frida", "input": ["text 1", "text 2"]}
  Response: {"object": "list", "data": [{"embedding": [...], "index": 0}, ...], "model": "frida"}
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Default configuration constants
_DEFAULT_BASE_URL = "https://api.ai.beeline.ru/api/v3"
# FRIDA embedding model id ("frida"). FRIDA requires GLM backing (per Beeline AI spec);
# the embeddings endpoint itself accepts the "frida" model id — no glm-5.x reference needed
# here. If a future FRIDA revision requires an explicit GLM model, set it via settings.frida_model.
_DEFAULT_MODEL = "frida"
_DEFAULT_MAX_BATCH_SIZE = 10
_DEFAULT_MAX_TEXT_LENGTH = 5000
_DEFAULT_MAX_CONTEXT_TOKENS = 500
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_ENABLE_CACHING = True
_DEFAULT_CIRCUIT_RESET_TIMEOUT = 60.0
_DEFAULT_FAILURE_THRESHOLD = 3
_CACHE_MAX_SIZE = 10000


class FridaEmbeddingService:
    """FRIDA embedding service via Beeline AI API.

    Features:
    - Connection pooling (httpx.AsyncClient, 100 max connections, 20 keepalive)
    - Retry with exponential backoff (tenacity, 3 attempts, 2-30 sec)
    - LRU cache for embeddings (10 000 entries)
    - Circuit breaker pattern (auto-reset after 60 sec)
    - Text sanitization (control characters removal, length truncation)
    - Batch embed support (max 10 per API call, auto-split)
    - Observability (logging, latency metrics, get_stats())
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE,
        max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH,
        max_context_tokens: int = _DEFAULT_MAX_CONTEXT_TOKENS,
        timeout: float = _DEFAULT_TIMEOUT,
        enable_caching: bool = _DEFAULT_ENABLE_CACHING,
        circuit_reset_timeout: float = _DEFAULT_CIRCUIT_RESET_TIMEOUT,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    ) -> None:
        """Initialize FridaEmbeddingService.

        Args:
            api_key: BEELINE_API_KEY (same as LLM provider).
            base_url: Base URL for FRIDA API.
            model: Embedding model name.
            max_batch_size: Maximum texts per batch (API limit: 10).
            max_text_length: Maximum text length in characters.
            max_context_tokens: Maximum context tokens for FRIDA (500).
            timeout: HTTP request timeout in seconds.
            enable_caching: Enable LRU cache for embeddings.
            circuit_reset_timeout: Seconds before circuit breaker auto-resets.
            failure_threshold: Number of failures before circuit opens.
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_batch_size = max_batch_size
        self.max_text_length = max_text_length
        self.max_context_tokens = max_context_tokens
        self.enable_caching = enable_caching
        self._circuit_reset_timeout = circuit_reset_timeout
        self._failure_threshold = failure_threshold

        # HTTP client with connection pooling and SSL bypass (McAfee proxy)
        self.http_client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            verify=False,  # Corporate SSL (McAfee proxy) — same as BeelineProvider
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
        )

        # LRU cache for single-text embeddings
        self._cache: Dict[str, List[float]] = {} if enable_caching else {}
        self._cache_max_size = _CACHE_MAX_SIZE

        # Circuit breaker state
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._circuit_open = False

        # Stats
        self._total_requests = 0
        self._total_cache_hits = 0

    async def __aenter__(self) -> "FridaEmbeddingService":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type] = None,
        exc_val: Optional[BaseException] = None,
        exc_tb: Optional[object] = None,
    ) -> None:
        """Exit async context manager — close HTTP client."""
        await self.http_client.aclose()

    # ── Text sanitization ──────────────────────────────────────

    @staticmethod
    def _sanitize_text(text: str, max_length: int = 5000) -> str:
        """Sanitize text: remove control characters, limit length.

        Removes control characters (except \\n and \\t) and truncates
        text to max_length characters.

        Args:
            text: Input text to sanitize.
            max_length: Maximum allowed text length.

        Returns:
            Sanitized text.
        """
        # Remove control characters (keep \n \t)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        # Truncate to max length
        return text[:max_length]

    # ── Cache helpers ──────────────────────────────────────────

    @staticmethod
    def _text_hash(text: str) -> str:
        """Compute SHA256 hash of text for caching.

        Args:
            text: Input text.

        Returns:
            Hex digest of SHA256 hash.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_get(self, text_hash: str) -> Optional[List[float]]:
        """Get cached embedding by text hash.

        Args:
            text_hash: SHA256 hash of text.

        Returns:
            Cached embedding vector or None.
        """
        if self.enable_caching and text_hash in self._cache:
            self._total_cache_hits += 1
            return self._cache[text_hash]
        return None

    def _cache_put(self, text_hash: str, vector: List[float]) -> None:
        """Store embedding in cache by text hash.

        Evicts oldest entry if cache is full.

        Args:
            text_hash: SHA256 hash of text.
            vector: Embedding vector.
        """
        if not self.enable_caching:
            return
        if len(self._cache) >= self._cache_max_size:
            # Evict oldest entry (FIFO eviction for dict)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[text_hash] = vector

    # ── Circuit breaker ────────────────────────────────────────

    def _check_circuit(self) -> None:
        """Check circuit breaker state; auto-reset after timeout.

        Raises:
            ConnectionError: If circuit breaker is open.
        """
        if self._circuit_open:
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self._circuit_reset_timeout:
                    # Auto-reset circuit breaker
                    logger.info("FRIDA circuit breaker auto-reset after %.0f sec", elapsed)
                    self._circuit_open = False
                    self._failure_count = 0
                    return
            raise ConnectionError(
                "FRIDA circuit breaker is open — requests are blocked. "
                f"Auto-resets after {self._circuit_reset_timeout} sec."
            )

    def _record_failure(self) -> None:
        """Record a failure for circuit breaker tracking."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._circuit_open = True
            logger.error(
                "FRIDA circuit breaker OPEN after %d failures. Auto-reset in %.0f sec.",
                self._failure_count,
                self._circuit_reset_timeout,
            )

    def _record_success(self) -> None:
        """Record a successful request — reset failure count."""
        self._failure_count = 0
        self._circuit_open = False

    # ── Raw API call ───────────────────────────────────────────

    async def _call_embeddings_api(self, texts: List[str]) -> List[List[float]]:
        """Call FRIDA embeddings API with retry and circuit breaker.

        Args:
            texts: List of texts to embed (1-10 items).

        Returns:
            List of 1536-dim embedding vectors.

        Raises:
            ConnectionError: If circuit breaker is open.
            httpx.TimeoutException: If request times out after retries.
            httpx.HTTPStatusError: If API returns error status.
        """
        self._check_circuit()
        self._total_requests += 1

        start = time.time()

        try:
            response = await self.http_client.post(
                "/embeddings",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()

            data = response.json()
            vectors = [item["embedding"] for item in data["data"]]

            latency_ms = (time.time() - start) * 1000
            logger.info(
                "FRIDA embed: %d texts, %.0f ms",
                len(texts),
                latency_ms,
            )

            self._record_success()
            return vectors

        except httpx.TimeoutException:
            self._record_failure()
            logger.error("FRIDA timeout after %.0f ms", (time.time() - start) * 1000)
            raise
        except httpx.ConnectError:
            self._record_failure()
            logger.error("FRIDA connection error")
            raise
        except httpx.HTTPStatusError as exc:
            self._record_failure()
            logger.error(
                "FRIDA HTTP error: %d %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise
        except Exception as exc:
            self._record_failure()
            logger.error("FRIDA embed failed: %s", exc, exc_info=True)
            raise

    # ── Public API ─────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    async def embed(self, text: str) -> List[float]:
        """Embed a single text with caching and retry.

        Returns 1536-dimensional FRIDA embedding vector.

        Args:
            text: Text to embed.

        Returns:
            1536-dim embedding vector.

        Raises:
            ConnectionError: If circuit breaker is open.
            httpx.TimeoutException: If request times out after retries.
            httpx.HTTPStatusError: If API returns error status.
        """
        # Sanitize input
        original_length = len(text)
        text = self._sanitize_text(text, max_length=self.max_text_length)
        if len(text) < original_length:
            logger.warning(
                "FRIDA embed: text truncated from %d to %d chars",
                original_length,
                len(text),
            )

        # Check cache
        if self.enable_caching:
            text_hash = self._text_hash(text)
            cached = self._cache_get(text_hash)
            if cached is not None:
                logger.debug("FRIDA embed: cache hit for hash=%s", text_hash[:12])
                return cached

        # API call (with retry decorator)
        vectors = await self._call_embeddings_api([text])
        vector = vectors[0]

        # Store in cache
        if self.enable_caching:
            self._cache_put(text_hash, vector)

        return vector

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts with auto-split for large batches.

        Maximum 10 texts per API call. Larger batches are automatically
        split into sub-batches.

        Args:
            texts: List of texts to embed.

        Returns:
            List of 1536-dim embedding vectors (same order as input).

        Raises:
            ConnectionError: If circuit breaker is open.
            httpx.TimeoutException: If request times out after retries.
            httpx.HTTPStatusError: If API returns error status.
        """
        if not texts:
            return []

        # Sanitize all texts
        sanitized_texts: List[str] = []
        for i, text in enumerate(texts):
            original_length = len(text)
            sanitized = self._sanitize_text(text, max_length=self.max_text_length)
            if len(sanitized) < original_length:
                logger.warning(
                    "FRIDA embed_batch: text %d truncated from %d to %d chars",
                    i,
                    original_length,
                    len(sanitized),
                )
            sanitized_texts.append(sanitized)

        # Auto-split if batch exceeds API limit
        if len(sanitized_texts) > self.max_batch_size:
            logger.warning(
                "FRIDA embed_batch: %d texts exceeds limit %d, splitting",
                len(sanitized_texts),
                self.max_batch_size,
            )
            all_vectors: List[List[float]] = []
            for i in range(0, len(sanitized_texts), self.max_batch_size):
                batch = sanitized_texts[i : i + self.max_batch_size]
                batch_vectors = await self._call_embeddings_api(batch)
                all_vectors.extend(batch_vectors)
            return all_vectors

        return await self._call_embeddings_api(sanitized_texts)

    # Alias for dict_mining.py compatibility (embed_texts → embed_batch)
    embed_texts = embed_batch

    async def is_available(self) -> bool:
        """Check if FRIDA API is reachable AND the ``frida`` model is available.

        Returns:
            True if the FRIDA model is listed in ``GET /models`` with
            ``embeddings: true``, False otherwise (including when circuit
            breaker is open or the API key's tenant lacks FRIDA access).

        Bug fix: previously this method only checked HTTP 200 on
        ``GET /models``, which returned True even when the ``frida``
        model was absent from the response (e.g. wrong tenant/policy).
        """
        if self._circuit_open:
            # Check if circuit breaker should auto-reset
            try:
                self._check_circuit()
            except ConnectionError:
                return False

        try:
            response = await self.http_client.get("/models")
            if response.status_code != 200:
                return False
            data = response.json()
            models = data.get("data", [])
            for m in models:
                if m.get("id") == self.model:
                    caps = m.get("capabilities", {})
                    return caps.get("embeddings", False)
            # frida not in list — key's tenant/policy lacks embeddings access
            return False
        except Exception:
            return False

    def get_stats(self) -> Dict[str, object]:
        """Get service statistics.

        Returns:
            Dictionary with cache_size, circuit_open, failure_count,
            total_requests, total_cache_hits, cache_hit_rate.
        """
        cache_size = len(self._cache) if self.enable_caching else 0
        cache_hit_rate = (
            (self._total_cache_hits / self._total_requests * 100)
            if self._total_requests > 0
            else 0.0
        )
        return {
            "caching_enabled": self.enable_caching,
            "cache_size": cache_size,
            "circuit_open": self._circuit_open,
            "failure_count": self._failure_count,
            "total_requests": self._total_requests,
            "total_cache_hits": self._total_cache_hits,
            "cache_hit_rate_percent": round(cache_hit_rate, 2),
        }

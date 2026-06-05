"""LiteLLM-based embedding service for unified provider access."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any

import batched  # type: ignore[import-untyped]
import litellm
from opentelemetry import trace

from context_service.config.config_loader import load_config
from context_service.config.logging import get_logger
from context_service.config.settings import ModelRateLimitConfig
from context_service.embeddings.rate_limit import get_embedding_rate_limiter
from context_service.embeddings.token_budget_batcher import TokenBudgetBatcher
from context_service.telemetry.metrics import (
    record_embedding,
    record_embedding_batch_size,
    record_embedding_cache_miss,
)
from context_service.telemetry.tracing import traced

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

_embedding_semaphore: asyncio.Semaphore | None = None


class LiteLLMEmbeddingError(Exception):
    """Raised when LiteLLM embedding operations fail."""

    pass


def _get_embedding_semaphore(max_concurrent: int) -> asyncio.Semaphore:
    """Get or create the fallback in-memory semaphore (used when Redis unavailable)."""
    global _embedding_semaphore
    if _embedding_semaphore is None:
        _embedding_semaphore = asyncio.Semaphore(max_concurrent)
    return _embedding_semaphore


class LiteLLMEmbeddingService:
    """LiteLLM embedding client supporting multiple providers.

    Model format examples:
        - "openai/text-embedding-3-small"
        - "vertex_ai/text-embedding-005"
        - "jina_ai/jina-embeddings-v3"
    """

    def __init__(
        self,
        model: str,
        dimensions: int = 768,
        max_input_chars: int = 30000,
        rate_limit: ModelRateLimitConfig | None = None,
        _embedding_cache: EmbeddingCache | None = None,
        batching_enabled: bool = True,
        batch_size: int = 32,
        timeout_ms: int = 100,
        small_batch_threshold: int = 4,
        batching_mode: str = "count",
        token_budget: int = 8000,
        max_batch_size: int = 64,
    ) -> None:
        """Initialize the LiteLLM embedding service.

        Args:
            model: LiteLLM model identifier (e.g., "openai/text-embedding-3-small").
            dimensions: Output embedding dimensions.
            max_input_chars: Maximum input length in characters before truncation.
                Defaults to 30000 (~8000 tokens). Inputs exceeding this are truncated
                with a warning to avoid silent model-side truncation.
            rate_limit: Rate limiting configuration. Defaults to ModelRateLimitConfig().
            _embedding_cache: Optional Redis-backed embedding cache.
            batching_enabled: Whether to use dynamic batching for single-text embeds.
            batch_size: Maximum batch size for count-based batching.
            timeout_ms: Max wait time in ms before flushing a partial batch.
            small_batch_threshold: Batch sizes at or below this bypass the timeout wait.
            batching_mode: "count" for count-based or "token_budget" for token-based.
            token_budget: Maximum tokens per batch (token_budget mode only).
            max_batch_size: Hard cap on texts per batch (token_budget mode only).
        """
        self._model = model
        self._dimensions = dimensions
        self._max_input_chars = max_input_chars
        self._rate_limit = rate_limit or ModelRateLimitConfig()
        self._embedding_cache = _embedding_cache
        self._batching_enabled = batching_enabled
        self._batch_size = batch_size
        self._timeout_ms = timeout_ms
        self._small_batch_threshold = small_batch_threshold
        self._batching_mode = batching_mode
        self._token_budget = token_budget
        self._max_batch_size = max_batch_size
        self._batched_fn: Any | None = None
        self._batched_fn_lock: asyncio.Lock = asyncio.Lock()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @classmethod
    def from_config(
        cls,
        _embedding_cache: EmbeddingCache | None = None,
    ) -> LiteLLMEmbeddingService:
        """Create a LiteLLMEmbeddingService from config/embeddings.yaml.

        Args:
            _embedding_cache: Optional Redis-backed embedding cache.

        Returns:
            Configured LiteLLMEmbeddingService.
        """
        config = load_config("embeddings")

        # Load rate_limit from YAML, fall back to defaults
        rate_limit_dict = config.get("rate_limit", {})
        rate_limit = ModelRateLimitConfig(**rate_limit_dict)

        batching = config.get("batching", {})

        return cls(
            model=config["model"],
            dimensions=config["dimensions"],
            max_input_chars=config.get("max_input_chars", 30000),
            rate_limit=rate_limit,
            _embedding_cache=_embedding_cache,
            batching_enabled=batching.get("enabled", True),
            batch_size=batching.get("batch_size", 32),
            timeout_ms=batching.get("timeout_ms", 100),
            small_batch_threshold=batching.get("small_batch_threshold", 4),
            batching_mode=batching.get("mode", "count"),
            token_budget=batching.get("token_budget", 8000),
            max_batch_size=batching.get("max_batch_size", 64),
        )

    @traced(capture_args=["texts"])
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            LiteLLMEmbeddingError: If embedding generation fails.
        """
        if not texts:
            return []

        # LiteLLM doesn't distinguish tasks; use a constant for cache key
        task = "passage"

        # Check cache first
        if self._embedding_cache:
            cached_results: list[list[float] | None] = []
            uncached_texts: list[str] = []
            uncached_indices: list[int] = []

            for i, text in enumerate(texts):
                cached = await self._embedding_cache.get(text, task)
                if cached is not None:
                    cached_results.append(cached)
                else:
                    cached_results.append(None)
                    uncached_texts.append(text)
                    uncached_indices.append(i)

            if not uncached_texts:
                result = [r for r in cached_results if r is not None]
                if len(result) != len(texts):
                    raise AssertionError(
                        f"Cache/batch length mismatch: {len(result)} vs {len(texts)}"
                    )
                return result

            # Record cache misses
            for _ in uncached_texts:
                record_embedding_cache_miss(task)

            # Embed uncached texts
            embeddings = await self._embed_batch(uncached_texts)

            # Store in cache and merge results
            for idx, (text, embedding) in enumerate(zip(uncached_texts, embeddings, strict=True)):
                await self._embedding_cache.set(text, task, embedding)
                cached_results[uncached_indices[idx]] = embedding

            result = [r for r in cached_results if r is not None]
            if len(result) != len(texts):
                raise AssertionError(f"Cache/batch length mismatch: {len(result)} vs {len(texts)}")
            return result

        return await self._embed_batch(texts)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via LiteLLM with rate limiting and retry.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            LiteLLMEmbeddingError: If embedding generation fails after retries.
        """
        record_embedding_batch_size(len(texts))
        truncated: list[str] = []
        for text in texts:
            if len(text) > self._max_input_chars:
                logger.warning(
                    "embedding_input_truncated",
                    original_length=len(text),
                    max_chars=self._max_input_chars,
                    model=self._model,
                )
                truncated.append(text[: self._max_input_chars])
            else:
                truncated.append(text)
        texts = truncated

        # Use Redis rate limiter if available, else fall back to in-memory semaphore
        redis_limiter = get_embedding_rate_limiter()
        fallback_semaphore = _get_embedding_semaphore(self._rate_limit.max_concurrent_requests)
        last_error: Exception | None = None

        for attempt in range(self._rate_limit.max_retries + 1):
            with tracer.start_as_current_span(
                "embedding.litellm",
                attributes={
                    "model": self._model,
                    "batch_size": len(texts),
                    "attempt": attempt,
                    "rate_limiter": "redis" if redis_limiter else "memory",
                },
            ) as span:
                try:
                    result = await self._do_embed_request(
                        texts, redis_limiter, fallback_semaphore, span
                    )
                    return result
                except Exception as e:
                    last_error = e
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))

                    is_retryable = self._is_retryable_error(e)
                    if not is_retryable or attempt >= self._rate_limit.max_retries:
                        logger.error(
                            "embedding_failed",
                            error=str(e),
                            model=self._model,
                            attempt=attempt,
                            retryable=is_retryable,
                        )
                        raise LiteLLMEmbeddingError(f"Embedding failed: {e}") from e

                    delay = min(
                        self._rate_limit.retry_base_delay_seconds * (2**attempt)
                        + random.uniform(0, 1),
                        self._rate_limit.retry_max_delay_seconds,
                    )
                    logger.warning(
                        "embedding_retry",
                        error=str(e),
                        model=self._model,
                        attempt=attempt,
                        delay_seconds=delay,
                    )
                    await asyncio.sleep(delay)

        raise LiteLLMEmbeddingError(f"Embedding failed after retries: {last_error}")

    async def _do_embed_request(
        self,
        texts: list[str],
        redis_limiter: object | None,
        fallback_semaphore: asyncio.Semaphore,
        span: trace.Span,
    ) -> list[list[float]]:
        """Execute the actual embedding request with rate limiting."""
        from context_service.embeddings.rate_limit import EmbeddingRateLimiter

        start = time.perf_counter()

        if redis_limiter and isinstance(redis_limiter, EmbeddingRateLimiter):
            async with redis_limiter:
                response = await litellm.aembedding(
                    model=self._model,
                    input=texts,
                    dimensions=self._dimensions,
                    timeout=self._rate_limit.timeout_seconds,
                )
        else:
            async with fallback_semaphore:
                response = await litellm.aembedding(
                    model=self._model,
                    input=texts,
                    dimensions=self._dimensions,
                    timeout=self._rate_limit.timeout_seconds,
                )

        duration_ms = (time.perf_counter() - start) * 1000
        span.set_attribute("duration_ms", duration_ms)
        record_embedding(self._model, duration_ms)
        return [item["embedding"] for item in response.data]

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (rate limit, timeout, transient)."""
        error_str = str(error).lower()
        retryable_patterns = [
            "rate limit",
            "ratelimit",
            "429",
            "timeout",
            "timed out",
            "resource exhausted",
            "503",
            "502",
            "504",
            "connection",
            "temporarily unavailable",
        ]
        return any(pattern in error_str for pattern in retryable_patterns)

    async def _get_or_create_batched_fn(self) -> Any:
        """Lazily create the batched embedding function for this instance."""
        if self._batched_fn is not None:
            return self._batched_fn

        async with self._batched_fn_lock:
            # Double-check after acquiring lock
            if self._batched_fn is not None:
                return self._batched_fn

            if self._batching_mode == "token_budget":
                self._batched_fn = TokenBudgetBatcher(
                    model=self._model,
                    embed_fn=self._embed_batch,
                    token_budget=self._token_budget,
                    max_batch_size=self._max_batch_size,
                    timeout_ms=self._timeout_ms,
                )
            else:
                @batched.aio.dynamically(  # type: ignore[untyped-decorator]
                    batch_size=self._batch_size,
                    timeout_ms=self._timeout_ms,
                    small_batch_threshold=self._small_batch_threshold,
                )
                async def _batched_embed(texts: list[str]) -> list[list[float]]:
                    return await self._embed_batch(texts)

                self._batched_fn = _batched_embed

            return self._batched_fn

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Uses cache when available. When batching is enabled, concurrent calls
        are batched together for efficiency.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        # Check cache first
        if self._embedding_cache:
            cached = await self._embedding_cache.get(text, "passage")
            if cached is not None:
                return cached
            record_embedding_cache_miss("passage")

        # Get embedding (batched or direct)
        vector: list[float]
        if self._batching_enabled:
            batcher = await self._get_or_create_batched_fn()
            if self._batching_mode == "token_budget":
                vector = await batcher.embed_single(text)
            else:
                results: list[list[float]] = await batcher([text])
                if not results:
                    raise LiteLLMEmbeddingError("Batched embedding returned empty results")
                vector = results[0]
        else:
            vector = (await self._embed_batch([text]))[0]

        # Store in cache
        if self._embedding_cache:
            await self._embedding_cache.set(text, "passage", vector)

        return vector

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a search query.

        Uses task='query' cache key to separate from passage embeddings.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        if self._embedding_cache:
            cached = await self._embedding_cache.get(query, "query")
            if cached is not None:
                return cached
            record_embedding_cache_miss("query")
            vector = (await self._embed_batch([query]))[0]
            await self._embedding_cache.set(query, "query", vector)
            return vector
        return (await self._embed_batch([query]))[0]

    async def close(self) -> None:
        """Close any resources (no-op for LiteLLM)."""
        pass

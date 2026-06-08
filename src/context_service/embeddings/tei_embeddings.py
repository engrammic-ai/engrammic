"""TEI (Text Embeddings Inference) embedding service."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

import httpx
from opentelemetry import trace

from context_service.config.logging import get_logger
from context_service.embeddings.base import EmbeddingService
from context_service.telemetry.metrics import record_embedding, record_embedding_cache_miss
from context_service.telemetry.tracing import traced

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class TEIEmbeddingError(Exception):
    """Raised when TEI embedding operations fail."""

    pass


class TEIEmbeddingService:
    """TEI embedding client for local/sidecar inference.

    Calls the TEI /embed endpoint. See:
    https://huggingface.github.io/text-embeddings-inference/
    """

    def __init__(
        self,
        base_url: str,
        dimensions: int = 768,
        timeout: float = 30.0,
        _embedding_cache: EmbeddingCache | None = None,
        max_retries: int = 3,
        retry_base_delay_seconds: float = 1.0,
        retry_max_delay_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dimensions = dimensions
        self._embedding_cache = _embedding_cache
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)
        self._max_retries = max_retries
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._retry_max_delay_seconds = retry_max_delay_seconds

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @traced(capture_args=["texts"])
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            TEIEmbeddingError: If embedding generation fails.
        """
        if not texts:
            return []

        task = "passage"

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

            for _ in uncached_texts:
                record_embedding_cache_miss(task)

            embeddings = await self._embed_batch(uncached_texts)

            for idx, (text, embedding) in enumerate(zip(uncached_texts, embeddings, strict=True)):
                await self._embedding_cache.set(text, task, embedding)
                cached_results[uncached_indices[idx]] = embedding

            result = [r for r in cached_results if r is not None]
            if len(result) != len(texts):
                raise AssertionError(f"Cache/batch length mismatch: {len(result)} vs {len(texts)}")
            return result

        return await self._embed_batch(texts)

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (transient HTTP or connection failure)."""
        if isinstance(error, httpx.HTTPStatusError):
            retryable_status_codes = {429, 500, 502, 503, 504}
            return error.response.status_code in retryable_status_codes
        if isinstance(
            error, (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)
        ):
            return True
        error_str = str(error).lower()
        retryable_patterns = [
            "timeout",
            "timed out",
            "connection",
            "temporarily unavailable",
            "503",
            "502",
            "504",
        ]
        return any(pattern in error_str for pattern in retryable_patterns)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via TEI with retry on transient errors.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            TEIEmbeddingError: If embedding generation fails after retries.
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            with tracer.start_as_current_span(
                "embedding.tei",
                attributes={"batch_size": len(texts), "attempt": attempt},
            ) as span:
                try:
                    start = time.perf_counter()
                    response = await self._client.post("/embed", json={"inputs": texts})
                    response.raise_for_status()
                    duration_ms = (time.perf_counter() - start) * 1000
                    span.set_attribute("duration_ms", duration_ms)
                    record_embedding("tei", duration_ms)
                    result: list[list[float]] = response.json()
                    return result
                except Exception as e:
                    last_error = e
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))

                    is_retryable = self._is_retryable_error(e)
                    if not is_retryable or attempt >= self._max_retries:
                        status = (
                            e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                        )
                        logger.error(
                            "tei_embedding_failed",
                            error=str(e),
                            attempt=attempt,
                            retryable=is_retryable,
                            status=status,
                        )
                        raise TEIEmbeddingError(f"TEI embedding failed: {e}") from e

                    delay = min(
                        self._retry_base_delay_seconds * (2**attempt) + random.uniform(0, 1),
                        self._retry_max_delay_seconds,
                    )
                    logger.warning(
                        "tei_embedding_retry",
                        error=str(e),
                        attempt=attempt,
                        delay_seconds=delay,
                    )
                    await asyncio.sleep(delay)

        raise TEIEmbeddingError(f"TEI embedding failed after retries: {last_error}")

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        results = await self.embed([text])
        return results[0]

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
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> TEIEmbeddingService:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class TEIWithFallbackEmbeddingService:
    """TEI embedding service with automatic fallback on failure.

    Wraps a primary TEI service and falls back to another service
    (typically LiteLLM) when TEI is unavailable or errors.
    """

    def __init__(
        self,
        primary: TEIEmbeddingService,
        fallback: EmbeddingService,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def dimensions(self) -> int:
        return self._primary.dimensions

    def _log_fallback(self, method: str, tei_error: Exception) -> None:
        """Log and trace fallback trigger."""
        span = trace.get_current_span()
        span.add_event(
            "tei_fallback_triggered",
            attributes={
                "method": method,
                "tei_error": str(tei_error),
                "fallback_provider": "litellm",
            },
        )
        span.set_attribute("embedding.fallback_used", True)
        span.set_attribute("embedding.tei_error", str(tei_error))
        logger.warning(
            "tei_fallback_triggered",
            method=method,
            tei_error=str(tei_error),
            fallback_provider="litellm",
        )

    def _log_fallback_result(
        self, method: str, success: bool, error: Exception | None = None
    ) -> None:
        """Log fallback outcome."""
        span = trace.get_current_span()
        span.set_attribute("embedding.fallback_success", success)
        if success:
            span.set_attribute("embedding.provider", "litellm")
            logger.info("tei_fallback_succeeded", method=method)
        else:
            span.set_attribute("embedding.fallback_error", str(error))
            logger.error("tei_fallback_failed", method=method, fallback_error=str(error))

    @traced(capture_args=["texts"])
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings, falling back on TEI error."""
        span = trace.get_current_span()
        try:
            result = await self._primary.embed(texts)
            span.set_attribute("embedding.provider", "tei")
            span.set_attribute("embedding.fallback_used", False)
            return result
        except TEIEmbeddingError as e:
            self._log_fallback("embed", e)
            try:
                result = await self._fallback.embed(texts)
                self._log_fallback_result("embed", success=True)
                return result
            except Exception as fallback_err:
                self._log_fallback_result("embed", success=False, error=fallback_err)
                raise

    async def embed_single(self, text: str) -> list[float]:
        """Generate single embedding, falling back on TEI error."""
        span = trace.get_current_span()
        try:
            result = await self._primary.embed_single(text)
            span.set_attribute("embedding.provider", "tei")
            span.set_attribute("embedding.fallback_used", False)
            return result
        except TEIEmbeddingError as e:
            self._log_fallback("embed_single", e)
            try:
                result = await self._fallback.embed_single(text)
                self._log_fallback_result("embed_single", success=True)
                return result
            except Exception as fallback_err:
                self._log_fallback_result("embed_single", success=False, error=fallback_err)
                raise

    async def embed_query(self, query: str) -> list[float]:
        """Generate query embedding, falling back on TEI error."""
        span = trace.get_current_span()
        try:
            result = await self._primary.embed_query(query)
            span.set_attribute("embedding.provider", "tei")
            span.set_attribute("embedding.fallback_used", False)
            return result
        except TEIEmbeddingError as e:
            self._log_fallback("embed_query", e)
            try:
                result = await self._fallback.embed_query(query)
                self._log_fallback_result("embed_query", success=True)
                return result
            except Exception as fallback_err:
                self._log_fallback_result("embed_query", success=False, error=fallback_err)
                raise

    async def close(self) -> None:
        """Close both primary and fallback services."""
        await self._primary.close()
        await self._fallback.close()

    async def __aenter__(self) -> TEIWithFallbackEmbeddingService:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

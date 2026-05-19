"""TEI (Text Embeddings Inference) embedding service."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
from opentelemetry import trace

from context_service.config.logging import get_logger
from context_service.embeddings.base import EmbeddingService
from context_service.telemetry.metrics import record_embedding

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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dimensions = dimensions
        self._embedding_cache = _embedding_cache
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    @property
    def dimensions(self) -> int:
        return self._dimensions

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
                assert len(result) == len(texts), "Cache/batch length mismatch"
                return result

            embeddings = await self._embed_batch(uncached_texts)

            for idx, (text, embedding) in enumerate(
                zip(uncached_texts, embeddings, strict=True)
            ):
                await self._embedding_cache.set(text, task, embedding)
                cached_results[uncached_indices[idx]] = embedding

            result = [r for r in cached_results if r is not None]
            assert len(result) == len(texts), "Cache/batch length mismatch"
            return result

        return await self._embed_batch(texts)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via TEI.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            TEIEmbeddingError: If embedding generation fails.
        """
        with tracer.start_as_current_span(
            "embedding.tei",
            attributes={"batch_size": len(texts)},
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
            except httpx.HTTPStatusError as e:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(e))
                logger.error("TEI embedding failed", error=str(e), status=e.response.status_code)
                raise TEIEmbeddingError(f"TEI embedding failed: {e}") from e
            except Exception as e:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(e))
                logger.error("TEI embedding failed", error=str(e))
                raise TEIEmbeddingError(f"TEI embedding failed: {e}") from e

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
            vector = (await self._embed_batch([query]))[0]
            await self._embedding_cache.set(query, "query", vector)
            return vector
        return (await self._embed_batch([query]))[0]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings, falling back on TEI error."""
        try:
            return await self._primary.embed(texts)
        except TEIEmbeddingError:
            logger.warning("tei_fallback_triggered", method="embed")
            return await self._fallback.embed(texts)

    async def embed_single(self, text: str) -> list[float]:
        """Generate single embedding, falling back on TEI error."""
        try:
            return await self._primary.embed_single(text)
        except TEIEmbeddingError:
            logger.warning("tei_fallback_triggered", method="embed_single")
            return await self._fallback.embed_single(text)

    async def embed_query(self, query: str) -> list[float]:
        """Generate query embedding, falling back on TEI error."""
        try:
            return await self._primary.embed_query(query)
        except TEIEmbeddingError:
            logger.warning("tei_fallback_triggered", method="embed_query")
            return await self._fallback.embed_query(query)

    async def close(self) -> None:
        """Close both primary and fallback services."""
        await self._primary.close()
        await self._fallback.close()

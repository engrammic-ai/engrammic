"""LiteLLM-based embedding service for unified provider access."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import litellm
from opentelemetry import trace

from context_service.config.config_loader import load_config
from context_service.config.logging import get_logger
from context_service.telemetry.metrics import record_embedding, record_embedding_cache_miss

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class LiteLLMEmbeddingError(Exception):
    """Raised when LiteLLM embedding operations fail."""

    pass


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
        _embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        """Initialize the LiteLLM embedding service.

        Args:
            model: LiteLLM model identifier (e.g., "openai/text-embedding-3-small").
            dimensions: Output embedding dimensions.
            _embedding_cache: Optional Redis-backed embedding cache.
        """
        self._model = model
        self._dimensions = dimensions
        self._embedding_cache = _embedding_cache

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
        return cls(
            model=config["model"],
            dimensions=config["dimensions"],
            _embedding_cache=_embedding_cache,
        )

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
        """Embed a batch of texts via LiteLLM.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            LiteLLMEmbeddingError: If embedding generation fails.
        """
        with tracer.start_as_current_span(
            "embedding.litellm",
            attributes={"model": self._model, "batch_size": len(texts)},
        ) as span:
            try:
                from context_service.config.settings import get_settings

                start = time.perf_counter()
                timeout = get_settings().llm.default_timeout_seconds
                response = await litellm.aembedding(
                    model=self._model, input=texts, dimensions=self._dimensions, timeout=timeout
                )
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("duration_ms", duration_ms)
                record_embedding(self._model, duration_ms)
                return [item["embedding"] for item in response.data]
            except Exception as e:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(e))
                logger.error("LiteLLM embedding failed", error=str(e), model=self._model)
                raise LiteLLMEmbeddingError(f"Embedding failed: {e}") from e

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
        """Close any resources (no-op for LiteLLM)."""
        pass

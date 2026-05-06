"""LiteLLM-based embedding service for unified provider access."""

from __future__ import annotations

from typing import TYPE_CHECKING

import litellm

from context_service.config.config_loader import load_config
from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache

logger = get_logger(__name__)


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
                return [r for r in cached_results if r is not None]

            # Embed uncached texts
            embeddings = await self._embed_batch(uncached_texts)

            # Store in cache and merge results
            for idx, (text, embedding) in enumerate(zip(uncached_texts, embeddings, strict=True)):
                await self._embedding_cache.set(text, task, embedding)
                cached_results[uncached_indices[idx]] = embedding

            return [r for r in cached_results if r is not None]

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
        try:
            response = await litellm.aembedding(
                model=self._model, input=texts, dimensions=self._dimensions
            )
            return [item["embedding"] for item in response.data]
        except Exception as e:
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

        LiteLLM doesn't distinguish between passage and query embeddings,
        so this simply delegates to embed_single.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        return await self.embed_single(query)

    async def close(self) -> None:
        """Close any resources (no-op for LiteLLM)."""
        pass

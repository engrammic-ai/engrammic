"""Embedding integrations."""

from typing import TYPE_CHECKING

from context_service.embeddings.base import EmbeddingService

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache
    from context_service.config.settings import Settings
from context_service.embeddings.jina import JinaEmbeddingError, JinaEmbeddingService
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
from context_service.embeddings.vertex import (
    VertexAIEmbeddingError,
    VertexAIEmbeddingService,
)


def build_embedding_service(
    provider: str,
    settings: "Settings | None" = None,
    embedding_cache: "EmbeddingCache | None" = None,
) -> EmbeddingService:
    """Factory for embedding services by provider name.

    Args:
        provider: One of "jina", "vertex".
        settings: Optional settings instance (uses get_settings() if None).
        embedding_cache: Optional Redis-backed embedding cache.

    Returns:
        Configured EmbeddingService instance.
    """
    from context_service.config.settings import get_settings

    if settings is None:
        settings = get_settings()
    if provider == "vertex":
        return VertexAIEmbeddingService.from_settings(settings, _embedding_cache=embedding_cache)
    return JinaEmbeddingService.from_settings(settings, _embedding_cache=embedding_cache)


__all__ = [
    "EmbeddingService",
    "build_embedding_service",
    "JinaEmbeddingError",
    "JinaEmbeddingService",
    "SpladeEncoder",
    "SpladeEncoderError",
    "VertexAIEmbeddingError",
    "VertexAIEmbeddingService",
]

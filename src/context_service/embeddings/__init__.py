"""Embedding integrations."""

from context_service.embeddings.base import EmbeddingService
from context_service.embeddings.jina import JinaEmbeddingError, JinaEmbeddingService
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
from context_service.embeddings.vertex import (
    VertexAIEmbeddingError,
    VertexAIEmbeddingService,
)


def build_embedding_service(provider: str) -> EmbeddingService:
    """Factory for embedding services by provider name.

    Args:
        provider: One of "jina", "vertex".

    Returns:
        Configured EmbeddingService instance.
    """
    from context_service.config.settings import get_settings

    settings = get_settings()
    if provider == "vertex":
        return VertexAIEmbeddingService.from_settings(settings)
    return JinaEmbeddingService.from_settings(settings)


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

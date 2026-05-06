"""Embedding integrations."""

from typing import TYPE_CHECKING

from context_service.embeddings.base import EmbeddingService
from context_service.embeddings.litellm_embeddings import (
    LiteLLMEmbeddingError,
    LiteLLMEmbeddingService,
)
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache
    from context_service.config.settings import Settings

# Backward-compat aliases
JinaEmbeddingService = LiteLLMEmbeddingService
JinaEmbeddingError = LiteLLMEmbeddingError
VertexAIEmbeddingService = LiteLLMEmbeddingService
VertexAIEmbeddingError = LiteLLMEmbeddingError


def build_embedding_service(
    provider: str,
    settings: "Settings | None" = None,
    embedding_cache: "EmbeddingCache | None" = None,
) -> EmbeddingService:
    """Factory for embedding services by provider name.

    Args:
        provider: Provider name (all route to LiteLLM now).
        settings: Optional settings instance (uses get_settings() if None).
        embedding_cache: Optional Redis-backed embedding cache.

    Returns:
        Configured EmbeddingService instance.
    """
    from context_service.config.settings import get_settings

    if settings is None:
        settings = get_settings()
    return LiteLLMEmbeddingService.from_settings(settings, _embedding_cache=embedding_cache)


__all__ = [
    "EmbeddingService",
    "build_embedding_service",
    "JinaEmbeddingError",
    "JinaEmbeddingService",
    "LiteLLMEmbeddingError",
    "LiteLLMEmbeddingService",
    "SpladeEncoder",
    "SpladeEncoderError",
    "VertexAIEmbeddingError",
    "VertexAIEmbeddingService",
]

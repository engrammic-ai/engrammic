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

# Backward-compat aliases
JinaEmbeddingService = LiteLLMEmbeddingService
JinaEmbeddingError = LiteLLMEmbeddingError
VertexAIEmbeddingService = LiteLLMEmbeddingService
VertexAIEmbeddingError = LiteLLMEmbeddingError


def build_embedding_service(
    embedding_cache: "EmbeddingCache | None" = None,
) -> EmbeddingService:
    """Factory for embedding services from config/embeddings.yaml.

    Args:
        embedding_cache: Optional Redis-backed embedding cache.

    Returns:
        Configured EmbeddingService instance.
    """
    return LiteLLMEmbeddingService.from_config(_embedding_cache=embedding_cache)


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

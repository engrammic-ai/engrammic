"""Embedding integrations."""

from context_service.embeddings.base import EmbeddingService
from context_service.embeddings.jina import JinaEmbeddingError, JinaEmbeddingService
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
from context_service.embeddings.vertex import (
    VertexAIEmbeddingError,
    VertexAIEmbeddingService,
)

__all__ = [
    "EmbeddingService",
    "JinaEmbeddingError",
    "JinaEmbeddingService",
    "SpladeEncoder",
    "SpladeEncoderError",
    "VertexAIEmbeddingError",
    "VertexAIEmbeddingService",
]

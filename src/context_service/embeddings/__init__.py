"""Embedding integrations."""

from typing import TYPE_CHECKING

from context_service.config.settings import get_settings
from context_service.embeddings.base import EmbeddingService
from context_service.embeddings.litellm_embeddings import (
    LiteLLMEmbeddingError,
    LiteLLMEmbeddingService,
)
from context_service.embeddings.rate_limit import (
    EmbeddingRateLimiter,
    EmbeddingRateLimitExceeded,
    get_embedding_rate_limiter,
    set_embedding_rate_limiter,
)

# SPLADE is optional (requires torch) - only available when splade group is installed
try:
    from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
except ImportError:
    SpladeEncoder = None
    SpladeEncoderError = None
from context_service.embeddings.tei_embeddings import (
    TEIEmbeddingError,
    TEIEmbeddingService,
    TEIWithFallbackEmbeddingService,
)

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache


def build_embedding_service(
    embedding_cache: "EmbeddingCache | None" = None,
) -> EmbeddingService:
    """Factory for embedding services based on active tier in models.yaml.

    Args:
        embedding_cache: Optional Redis-backed embedding cache.

    Returns:
        Configured EmbeddingService instance.

    Raises:
        RuntimeError: If provider=tei but TEI_URL is not configured.
    """
    settings = get_settings()
    models = settings.models
    embed_spec = models.get_embedding_model()

    if embed_spec.provider == "tei":
        if not settings.tei_url:
            raise RuntimeError("Tier uses TEI embeddings but TEI_URL is not configured.")
        tei_service = TEIEmbeddingService(
            base_url=settings.tei_url,
            dimensions=models.embedding_dimensions,
            _embedding_cache=embedding_cache,
        )
        fallback_service = LiteLLMEmbeddingService.from_settings(_embedding_cache=embedding_cache)
        return TEIWithFallbackEmbeddingService(primary=tei_service, fallback=fallback_service)

    return LiteLLMEmbeddingService.from_settings(_embedding_cache=embedding_cache)


__all__ = [
    "EmbeddingService",
    "EmbeddingRateLimitExceeded",
    "EmbeddingRateLimiter",
    "build_embedding_service",
    "get_embedding_rate_limiter",
    "set_embedding_rate_limiter",
    "LiteLLMEmbeddingError",
    "LiteLLMEmbeddingService",
    "SpladeEncoder",
    "SpladeEncoderError",
    "TEIEmbeddingError",
    "TEIEmbeddingService",
    "TEIWithFallbackEmbeddingService",
]

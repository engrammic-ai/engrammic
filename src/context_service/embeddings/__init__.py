"""Embedding integrations."""

from typing import TYPE_CHECKING

from context_service.config.config_loader import load_config
from context_service.config.settings import get_settings
from context_service.embeddings.base import EmbeddingService
from context_service.embeddings.litellm_embeddings import (
    LiteLLMEmbeddingError,
    LiteLLMEmbeddingService,
)
from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError
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
    """Factory for embedding services from config/embeddings.yaml.

    Args:
        embedding_cache: Optional Redis-backed embedding cache.

    Returns:
        Configured EmbeddingService instance.

    Raises:
        RuntimeError: If provider=tei but TEI_URL is not configured.
    """
    config = load_config("embeddings")
    provider = config.get("provider", "litellm")

    if provider == "tei":
        settings = get_settings()
        if not settings.tei_url:
            raise RuntimeError(
                "embeddings.yaml sets provider=tei but TEI_URL is not configured."
            )
        tei_service = TEIEmbeddingService(
            base_url=settings.tei_url,
            dimensions=config.get("dimensions", 768),
            _embedding_cache=embedding_cache,
        )
        fallback_service = LiteLLMEmbeddingService.from_config(
            _embedding_cache=embedding_cache
        )
        return TEIWithFallbackEmbeddingService(
            primary=tei_service, fallback=fallback_service
        )

    return LiteLLMEmbeddingService.from_config(_embedding_cache=embedding_cache)


__all__ = [
    "EmbeddingService",
    "build_embedding_service",
    "LiteLLMEmbeddingError",
    "LiteLLMEmbeddingService",
    "SpladeEncoder",
    "SpladeEncoderError",
    "TEIEmbeddingError",
    "TEIEmbeddingService",
    "TEIWithFallbackEmbeddingService",
]

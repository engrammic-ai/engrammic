"""Reranker factory - selects implementation based on config."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.config import get_settings
from context_service.reranking.reranker import LiteLLMReranker
from context_service.reranking.tei_reranker import TEIReranker

if TYPE_CHECKING:
    from context_service.config.models import ModelsConfig


def get_reranker(
    config: ModelsConfig,
    timeout_seconds: float = 10.0,
) -> LiteLLMReranker | TEIReranker | None:
    """Create appropriate reranker based on models config.

    Args:
        config: Models configuration with tier and reranker spec.
        timeout_seconds: Timeout for reranker requests.

    Returns:
        LiteLLMReranker for cloud providers (vertex_ai, cohere, jina).
        TEIReranker for local TEI deployment.
        None if no reranker is configured for the tier.
    """
    spec = config.get_reranker_model()
    if spec is None:
        return None

    if spec.provider == "tei":
        settings = get_settings()
        url = spec.url or settings.reranker_url or settings.tei_reranker_url
        if not url:
            raise ValueError(
                "TEI reranker requires 'url' in ModelSpec or RERANKER_URL/TEI_RERANKER_URL env var"
            )
        return TEIReranker(
            base_url=url,
            timeout_seconds=timeout_seconds,
        )

    # LiteLLM providers (vertex_ai, cohere, jina, etc.)
    return LiteLLMReranker(
        model=f"{spec.provider}/{spec.model}",
        timeout_seconds=timeout_seconds,
        vertex_project=config.vertex_project or None,
    )

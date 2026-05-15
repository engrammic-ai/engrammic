"""Tests for reranker model configuration."""

from __future__ import annotations

from context_service.config.models import ModelSpec, TierConfig


class TestRerankerModelConfig:
    def test_tier_config_accepts_reranker(self) -> None:
        tier = TierConfig(
            embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-005", dimensions=768),
            reasoning=ModelSpec(provider="vertex", model="gemini-2.5-pro"),
            fast=ModelSpec(provider="vertex", model="gemini-2.5-flash"),
            reranker=ModelSpec(provider="vertex_ai", model="semantic-ranker-default@latest"),
            query_expander=ModelSpec(provider="vertex", model="gemini-2.5-flash"),
        )
        assert tier.reranker is not None
        assert tier.reranker.model == "semantic-ranker-default@latest"
        assert tier.query_expander is not None

    def test_tier_config_reranker_optional(self) -> None:
        tier = TierConfig(
            embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-005", dimensions=768),
            reasoning=ModelSpec(provider="vertex", model="gemini-2.5-pro"),
            fast=ModelSpec(provider="vertex", model="gemini-2.5-flash"),
        )
        assert tier.reranker is None
        assert tier.query_expander is None

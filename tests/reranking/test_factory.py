"""Tests for reranker factory."""

from __future__ import annotations

import pytest

from context_service.config.models import ModelsConfig, ModelSpec, TierConfig
from context_service.reranking.factory import get_reranker
from context_service.reranking.reranker import LiteLLMReranker
from context_service.reranking.tei_reranker import TEIReranker


def _make_config(reranker: ModelSpec | None = None) -> ModelsConfig:
    """Build a minimal ModelsConfig for testing."""
    tier = TierConfig(
        embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-004", dimensions=768),
        reasoning=ModelSpec(provider="vertex_ai", model="gemini-2.0-flash"),
        fast=ModelSpec(provider="vertex_ai", model="gemini-2.0-flash"),
        reranker=reranker,
    )
    return ModelsConfig(
        tier="balanced",
        vertex_project="test-project",
        tiers={"balanced": tier},
    )


class TestGetReranker:
    def test_returns_none_when_no_reranker_configured(self) -> None:
        config = _make_config(reranker=None)
        result = get_reranker(config)
        assert result is None

    def test_returns_tei_reranker_for_tei_provider(self) -> None:
        spec = ModelSpec(
            provider="tei", model="BAAI/bge-reranker-v2-m3", url="http://localhost:8082"
        )
        config = _make_config(reranker=spec)
        result = get_reranker(config)
        assert isinstance(result, TEIReranker)
        assert result.base_url == "http://localhost:8082"

    def test_tei_reranker_raises_when_url_missing(self) -> None:
        spec = ModelSpec(provider="tei", model="BAAI/bge-reranker-v2-m3")
        config = _make_config(reranker=spec)
        with pytest.raises(ValueError, match="url"):
            get_reranker(config)

    def test_returns_litellm_reranker_for_vertex_provider(self) -> None:
        spec = ModelSpec(provider="vertex_ai", model="semantic-ranker-default@latest")
        config = _make_config(reranker=spec)
        result = get_reranker(config)
        assert isinstance(result, LiteLLMReranker)
        assert result._model == "vertex_ai/semantic-ranker-default@latest"

    def test_returns_litellm_reranker_for_cohere_provider(self) -> None:
        spec = ModelSpec(provider="cohere", model="rerank-english-v3.0")
        config = _make_config(reranker=spec)
        result = get_reranker(config)
        assert isinstance(result, LiteLLMReranker)
        assert result._model == "cohere/rerank-english-v3.0"

    def test_litellm_reranker_uses_vertex_project(self) -> None:
        spec = ModelSpec(provider="vertex_ai", model="semantic-ranker-default@latest")
        config = _make_config(reranker=spec)
        result = get_reranker(config)
        assert isinstance(result, LiteLLMReranker)
        assert result._vertex_project == "test-project"

    def test_timeout_propagated_to_tei_reranker(self) -> None:
        spec = ModelSpec(
            provider="tei", model="BAAI/bge-reranker-v2-m3", url="http://localhost:8082"
        )
        config = _make_config(reranker=spec)
        result = get_reranker(config, timeout_seconds=5.0)
        assert isinstance(result, TEIReranker)
        assert result.timeout_seconds == 5.0

    def test_timeout_propagated_to_litellm_reranker(self) -> None:
        spec = ModelSpec(provider="vertex_ai", model="semantic-ranker-default@latest")
        config = _make_config(reranker=spec)
        result = get_reranker(config, timeout_seconds=15.0)
        assert isinstance(result, LiteLLMReranker)
        assert result._timeout == 15.0

    def test_empty_vertex_project_becomes_none(self) -> None:
        spec = ModelSpec(provider="vertex_ai", model="semantic-ranker-default@latest")
        tier = TierConfig(
            embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-004", dimensions=768),
            reasoning=ModelSpec(provider="vertex_ai", model="gemini-2.0-flash"),
            fast=ModelSpec(provider="vertex_ai", model="gemini-2.0-flash"),
            reranker=spec,
        )
        config = ModelsConfig(
            tier="balanced",
            vertex_project="",
            tiers={"balanced": tier},
        )
        result = get_reranker(config)
        assert isinstance(result, LiteLLMReranker)
        assert result._vertex_project is None

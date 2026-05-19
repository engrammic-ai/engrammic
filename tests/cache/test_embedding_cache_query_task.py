"""Tests for embed_query using 'query' task key."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.embeddings.litellm_embeddings import LiteLLMEmbeddingService


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


@pytest.fixture
def embedding_service(mock_cache: AsyncMock) -> LiteLLMEmbeddingService:
    svc = LiteLLMEmbeddingService(
        model="test/model",
        dimensions=768,
        _embedding_cache=mock_cache,
    )
    svc._embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return svc


@pytest.mark.asyncio
async def test_embed_query_uses_query_task_key(
    embedding_service: LiteLLMEmbeddingService,
    mock_cache: AsyncMock,
) -> None:
    """embed_query should use task='query' not 'passage'."""
    await embedding_service.embed_query("test query")

    # Should check cache with task="query"
    mock_cache.get.assert_called_once_with("test query", "query")
    # Should set cache with task="query"
    mock_cache.set.assert_called_once_with("test query", "query", [0.1, 0.2, 0.3])


@pytest.mark.asyncio
async def test_embed_query_cache_hit_skips_batch(
    embedding_service: LiteLLMEmbeddingService,
    mock_cache: AsyncMock,
) -> None:
    """Cache hit should skip _embed_batch call."""
    mock_cache.get.return_value = [0.9, 0.8, 0.7]

    result = await embedding_service.embed_query("cached query")

    assert result == [0.9, 0.8, 0.7]
    embedding_service._embed_batch.assert_not_called()


@pytest.mark.asyncio
async def test_embed_query_cache_miss_populates_cache(
    embedding_service: LiteLLMEmbeddingService,
    mock_cache: AsyncMock,
) -> None:
    """Cache miss should call _embed_batch and populate cache."""
    mock_cache.get.return_value = None

    result = await embedding_service.embed_query("new query")

    assert result == [0.1, 0.2, 0.3]
    embedding_service._embed_batch.assert_called_once_with(["new query"])
    mock_cache.set.assert_called_once_with("new query", "query", [0.1, 0.2, 0.3])

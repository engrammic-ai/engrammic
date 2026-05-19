"""Integration smoke tests for embedding cache behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.embeddings.litellm_embeddings import LiteLLMEmbeddingService


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(side_effect=[None, [0.1, 0.2, 0.3]])
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
async def test_second_query_hits_cache(
    embedding_service: LiteLLMEmbeddingService,
    mock_cache: AsyncMock,
) -> None:
    """Second identical query should hit cache and skip _embed_batch."""
    await embedding_service.embed_query("what is the revenue target?")
    await embedding_service.embed_query("what is the revenue target?")

    embedding_service._embed_batch.assert_called_once()


@pytest.mark.asyncio
async def test_query_and_passage_cache_keys_do_not_collide() -> None:
    """embed_query and embed use different task keys, both call _embed_batch."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()

    svc = LiteLLMEmbeddingService(
        model="test/model",
        dimensions=768,
        _embedding_cache=cache,
    )
    svc._embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    await svc.embed_query("same text")
    await svc.embed(["same text"])

    assert svc._embed_batch.call_count == 2

    get_calls = cache.get.call_args_list
    assert ("same text", "query") in [(c.args[0], c.args[1]) for c in get_calls]
    assert ("same text", "passage") in [(c.args[0], c.args[1]) for c in get_calls]

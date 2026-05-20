"""Tests for embedding cache hit/miss metrics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.cache.embedding_cache import EmbeddingCache


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_cache_hit_records_hit_metric(mock_redis: AsyncMock) -> None:
    """Cache hit should record hit metric."""
    mock_redis.get.return_value = b"[0.1, 0.2, 0.3]"
    cache = EmbeddingCache(mock_redis, ttl=3600)

    with patch("context_service.cache.embedding_cache.record_embedding_cache_hit") as mock_hit:
        result = await cache.get("test text", "query")

        assert result == [0.1, 0.2, 0.3]
        mock_hit.assert_called_once_with("query")


@pytest.mark.asyncio
async def test_cache_miss_does_not_record_hit(mock_redis: AsyncMock) -> None:
    """Cache miss should not record hit metric."""
    mock_redis.get.return_value = None
    cache = EmbeddingCache(mock_redis, ttl=3600)

    with patch("context_service.cache.embedding_cache.record_embedding_cache_hit") as mock_hit:
        result = await cache.get("test text", "query")

        assert result is None
        mock_hit.assert_not_called()

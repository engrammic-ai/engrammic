"""Tests for TEIEmbeddingService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from context_service.embeddings.tei_embeddings import (
    TEIEmbeddingError,
    TEIEmbeddingService,
)


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


@pytest.fixture
def tei_service(mock_cache: AsyncMock) -> TEIEmbeddingService:
    return TEIEmbeddingService(
        base_url="http://localhost:8080",
        dimensions=768,
        _embedding_cache=mock_cache,
    )


@pytest.mark.asyncio
async def test_tei_embed_calls_endpoint(tei_service: TEIEmbeddingService) -> None:
    """TEI embed should POST to /embed with correct payload."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [[0.1, 0.2, 0.3]]

    with patch.object(tei_service._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await tei_service.embed(["test text"])

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/embed"
        assert call_args[1]["json"] == {"inputs": ["test text"]}


@pytest.mark.asyncio
async def test_tei_embed_returns_vectors(tei_service: TEIEmbeddingService) -> None:
    """TEI embed should return vectors from response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    with patch.object(tei_service._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await tei_service.embed(["text1", "text2"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.asyncio
async def test_tei_embed_query_uses_query_task_key(
    tei_service: TEIEmbeddingService,
    mock_cache: AsyncMock,
) -> None:
    """embed_query should use task='query' cache key."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [[0.1, 0.2, 0.3]]

    with patch.object(tei_service._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await tei_service.embed_query("test query")

        mock_cache.get.assert_called_once_with("test query", "query")
        mock_cache.set.assert_called_once_with("test query", "query", [0.1, 0.2, 0.3])


@pytest.mark.asyncio
async def test_tei_embed_raises_on_http_error(tei_service: TEIEmbeddingService) -> None:
    """HTTP errors should raise TEIEmbeddingError."""
    with patch.object(tei_service._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with pytest.raises(TEIEmbeddingError):
            await tei_service.embed(["test"])


@pytest.mark.asyncio
async def test_tei_embed_cache_hit_skips_http(
    tei_service: TEIEmbeddingService,
    mock_cache: AsyncMock,
) -> None:
    """Cache hit should skip HTTP call."""
    mock_cache.get.return_value = [0.9, 0.8, 0.7]

    with patch.object(tei_service._client, "post", new_callable=AsyncMock) as mock_post:
        result = await tei_service.embed_query("cached query")

        assert result == [0.9, 0.8, 0.7]
        mock_post.assert_not_called()

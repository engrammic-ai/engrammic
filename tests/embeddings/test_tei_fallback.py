"""Tests for TEIWithFallbackEmbeddingService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.embeddings.tei_embeddings import (
    TEIEmbeddingError,
    TEIWithFallbackEmbeddingService,
)


@pytest.fixture
def mock_primary() -> AsyncMock:
    primary = AsyncMock()
    primary.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    primary.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])
    primary.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    primary.close = AsyncMock()
    primary.dimensions = 768
    return primary


@pytest.fixture
def mock_fallback() -> AsyncMock:
    fallback = AsyncMock()
    fallback.embed = AsyncMock(return_value=[[0.4, 0.5, 0.6]])
    fallback.embed_single = AsyncMock(return_value=[0.4, 0.5, 0.6])
    fallback.embed_query = AsyncMock(return_value=[0.4, 0.5, 0.6])
    fallback.close = AsyncMock()
    fallback.dimensions = 768
    return fallback


@pytest.fixture
def wrapper_service(
    mock_primary: AsyncMock, mock_fallback: AsyncMock
) -> TEIWithFallbackEmbeddingService:
    return TEIWithFallbackEmbeddingService(primary=mock_primary, fallback=mock_fallback)


@pytest.mark.asyncio
async def test_fallback_triggered_on_tei_error_embed(
    wrapper_service: TEIWithFallbackEmbeddingService,
    mock_primary: AsyncMock,
    mock_fallback: AsyncMock,
) -> None:
    """Fallback should be triggered when primary raises TEIEmbeddingError."""
    mock_primary.embed.side_effect = TEIEmbeddingError("Connection refused")

    result = await wrapper_service.embed(["test text"])

    assert result == [[0.4, 0.5, 0.6]]
    mock_fallback.embed.assert_called_once_with(["test text"])


@pytest.mark.asyncio
async def test_fallback_triggered_on_tei_error_embed_single(
    wrapper_service: TEIWithFallbackEmbeddingService,
    mock_primary: AsyncMock,
    mock_fallback: AsyncMock,
) -> None:
    """Fallback should be triggered for embed_single."""
    mock_primary.embed_single.side_effect = TEIEmbeddingError("Connection refused")

    result = await wrapper_service.embed_single("test text")

    assert result == [0.4, 0.5, 0.6]
    mock_fallback.embed_single.assert_called_once_with("test text")


@pytest.mark.asyncio
async def test_fallback_triggered_on_tei_error_embed_query(
    wrapper_service: TEIWithFallbackEmbeddingService,
    mock_primary: AsyncMock,
    mock_fallback: AsyncMock,
) -> None:
    """Fallback should be triggered for embed_query."""
    mock_primary.embed_query.side_effect = TEIEmbeddingError("Connection refused")

    result = await wrapper_service.embed_query("test query")

    assert result == [0.4, 0.5, 0.6]
    mock_fallback.embed_query.assert_called_once_with("test query")


@pytest.mark.asyncio
async def test_no_fallback_on_success(
    wrapper_service: TEIWithFallbackEmbeddingService,
    mock_primary: AsyncMock,
    mock_fallback: AsyncMock,
) -> None:
    """Fallback should not be called when primary succeeds."""
    result = await wrapper_service.embed(["test text"])

    assert result == [[0.1, 0.2, 0.3]]
    mock_fallback.embed.assert_not_called()


@pytest.mark.asyncio
async def test_close_closes_both(
    wrapper_service: TEIWithFallbackEmbeddingService,
    mock_primary: AsyncMock,
    mock_fallback: AsyncMock,
) -> None:
    """Close should close both primary and fallback."""
    await wrapper_service.close()

    mock_primary.close.assert_called_once()
    mock_fallback.close.assert_called_once()

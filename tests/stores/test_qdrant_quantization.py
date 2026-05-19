"""Unit tests for Qdrant quantization config settings — no live Qdrant required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.models import ScalarQuantization, ScalarType

from context_service.config.settings import QdrantConfig, Settings
from context_service.stores.qdrant import QdrantClient


def test_quantization_settings_defaults() -> None:
    config = QdrantConfig()
    assert config.scalar_quantization_enabled is False
    assert config.quantization_always_ram is True


def test_quantization_settings_enabled() -> None:
    config = QdrantConfig(scalar_quantization_enabled=True, quantization_always_ram=False)
    assert config.scalar_quantization_enabled is True
    assert config.quantization_always_ram is False


def test_settings_flat_shims_defaults() -> None:
    settings = Settings()
    assert settings.qdrant_scalar_quantization_enabled is False
    assert settings.qdrant_quantization_always_ram is True


@pytest.mark.asyncio
async def test_create_collection_with_quantization() -> None:
    """ensure_collection passes INT8 ScalarQuantization when scalar_quantization=True."""
    client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="test_quant",
        scalar_quantization=True,
        always_ram=True,
    )

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()

    with patch.object(client, "_get_client", return_value=mock_async_client):
        await client.ensure_collection(hybrid=False)

    mock_async_client.create_collection.assert_called_once()
    call_kwargs = mock_async_client.create_collection.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_quant"

    quant = call_kwargs["quantization_config"]
    assert isinstance(quant, ScalarQuantization)
    assert quant.scalar.type == ScalarType.INT8
    assert quant.scalar.always_ram is True


@pytest.mark.asyncio
async def test_create_collection_without_quantization() -> None:
    """ensure_collection passes quantization_config=None when scalar_quantization=False."""
    client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="test_no_quant",
        scalar_quantization=False,
    )

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()

    with patch.object(client, "_get_client", return_value=mock_async_client):
        await client.ensure_collection(hybrid=False)

    call_kwargs = mock_async_client.create_collection.call_args.kwargs
    assert call_kwargs["quantization_config"] is None


@pytest.mark.asyncio
async def test_create_collection_hybrid_with_quantization() -> None:
    """ensure_collection passes quantization config for hybrid collections too."""
    client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="test_hybrid_quant",
        scalar_quantization=True,
        always_ram=False,
    )

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()

    with patch.object(client, "_get_client", return_value=mock_async_client):
        await client.ensure_collection(hybrid=True)

    call_kwargs = mock_async_client.create_collection.call_args.kwargs
    quant = call_kwargs["quantization_config"]
    assert isinstance(quant, ScalarQuantization)
    assert quant.scalar.type == ScalarType.INT8
    assert quant.scalar.always_ram is False

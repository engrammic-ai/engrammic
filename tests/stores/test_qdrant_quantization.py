"""Unit tests for Qdrant quantization config settings — no live Qdrant required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.models import ScalarQuantization, ScalarQuantizationConfig, ScalarType

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


@pytest.mark.asyncio
async def test_matryoshka_dimension_mismatch_is_detected() -> None:
    """ensure_collection logs a warning when configured dimensions differ from existing collection."""
    client = QdrantClient(
        vector_size=512,
        url="http://localhost:6333",
        collection_name="test_dim_mismatch",
        scalar_quantization=False,
    )

    mock_async_client = AsyncMock()

    # Collection already exists (non-empty list).
    mock_collection_entry = MagicMock()
    mock_collection_entry.name = "test_dim_mismatch"
    mock_collections = MagicMock()
    mock_collections.collections = [mock_collection_entry]
    mock_async_client.get_collections.return_value = mock_collections

    # Existing collection was created with 768 dimensions.
    mock_vector_params = MagicMock()
    mock_vector_params.size = 768
    mock_params = MagicMock()
    mock_params.vectors = mock_vector_params
    mock_config = MagicMock()
    mock_config.params = mock_params
    mock_collection_info = MagicMock()
    mock_collection_info.config = mock_config
    mock_async_client.get_collection = AsyncMock(return_value=mock_collection_info)

    with (
        patch.object(client, "_get_client", return_value=mock_async_client),
        patch("context_service.stores.qdrant.logger") as mock_logger,
    ):
        await client.ensure_collection(hybrid=False)

    # Warning must have been issued with the correct keys.
    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if call.args and call.args[0] == "qdrant_dimension_mismatch"
    ]
    assert len(warning_calls) == 1, "Expected exactly one qdrant_dimension_mismatch warning"
    kwargs = warning_calls[0].kwargs
    assert kwargs["configured"] == 512
    assert kwargs["existing"] == 768


@pytest.mark.asyncio
async def test_matryoshka_dimension_mismatch_not_logged_when_matching() -> None:
    """ensure_collection does NOT warn when configured dimensions match existing collection."""
    client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="test_dim_match",
        scalar_quantization=False,
    )

    mock_async_client = AsyncMock()

    mock_collection_entry = MagicMock()
    mock_collection_entry.name = "test_dim_match"
    mock_collections = MagicMock()
    mock_collections.collections = [mock_collection_entry]
    mock_async_client.get_collections.return_value = mock_collections

    # Existing collection has the same 768 dimensions.
    mock_vector_params = MagicMock()
    mock_vector_params.size = 768
    mock_params = MagicMock()
    mock_params.vectors = mock_vector_params
    mock_config = MagicMock()
    mock_config.params = mock_params
    mock_collection_info = MagicMock()
    mock_collection_info.config = mock_config
    mock_async_client.get_collection = AsyncMock(return_value=mock_collection_info)

    with (
        patch.object(client, "_get_client", return_value=mock_async_client),
        patch("context_service.stores.qdrant.logger") as mock_logger,
    ):
        await client.ensure_collection(hybrid=False)

    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if call.args and call.args[0] == "qdrant_dimension_mismatch"
    ]
    assert len(warning_calls) == 0, "No dimension mismatch warning expected when sizes match"


@pytest.mark.asyncio
async def test_hybrid_search_with_quantization() -> None:
    """ensure_collection passes both sparse_vectors_config and quantization_config when hybrid=True and scalar_quantization=True."""
    client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="test_hybrid_search_quant",
        scalar_quantization=True,
        always_ram=True,
    )

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()

    with patch.object(client, "_get_client", return_value=mock_async_client):
        await client.ensure_collection(hybrid=True)

    mock_async_client.create_collection.assert_called_once()
    call_kwargs = mock_async_client.create_collection.call_args.kwargs

    # Verify sparse_vectors_config is present and contains the sparse vector name.
    assert "sparse_vectors_config" in call_kwargs, (
        "sparse_vectors_config must be present for hybrid collections"
    )
    sparse_config = call_kwargs["sparse_vectors_config"]
    assert sparse_config is not None
    assert "sparse" in sparse_config, "sparse_vectors_config must contain 'sparse' key"

    # Verify quantization_config is INT8 scalar quantization.
    quant = call_kwargs["quantization_config"]
    assert isinstance(quant, ScalarQuantization), "quantization_config must be ScalarQuantization"
    assert quant.scalar.type == ScalarType.INT8
    assert quant.scalar.always_ram is True


@pytest.mark.asyncio
async def test_engine_qdrant_store_applies_quantization() -> None:
    """EngineQdrantStore passes quantization config from QdrantClient on collection creation."""
    from context_service.engine.qdrant_store import EngineQdrantStore

    qdrant_client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="unused",
        scalar_quantization=True,
        always_ram=True,
    )

    store = EngineQdrantStore(qdrant_client, hybrid=False)

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()
    mock_async_client.create_payload_index = AsyncMock()

    with patch.object(qdrant_client, "_get_client", return_value=mock_async_client):
        await store._ensure_collection("test-silo")

    mock_async_client.create_collection.assert_called_once()
    call_kwargs = mock_async_client.create_collection.call_args.kwargs
    quant = call_kwargs["quantization_config"]
    assert isinstance(quant, ScalarQuantization)
    assert quant.scalar.type == ScalarType.INT8
    assert quant.scalar.always_ram is True


@pytest.mark.asyncio
async def test_engine_qdrant_store_no_quantization_when_disabled() -> None:
    """EngineQdrantStore passes quantization_config=None when scalar_quantization is False."""
    from context_service.engine.qdrant_store import EngineQdrantStore

    qdrant_client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="unused",
        scalar_quantization=False,
    )

    store = EngineQdrantStore(qdrant_client, hybrid=False)

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()
    mock_async_client.create_payload_index = AsyncMock()

    with patch.object(qdrant_client, "_get_client", return_value=mock_async_client):
        await store._ensure_collection("test-silo-no-quant")

    call_kwargs = mock_async_client.create_collection.call_args.kwargs
    assert call_kwargs["quantization_config"] is None


@pytest.mark.asyncio
async def test_engine_qdrant_store_cluster_collection_applies_quantization() -> None:
    """ensure_cluster_collection also passes quantization config from QdrantClient."""
    from context_service.engine.qdrant_store import EngineQdrantStore

    qdrant_client = QdrantClient(
        vector_size=768,
        url="http://localhost:6333",
        collection_name="unused",
        scalar_quantization=True,
        always_ram=False,
    )

    store = EngineQdrantStore(qdrant_client, hybrid=False)

    mock_async_client = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    mock_async_client.get_collections.return_value = mock_collections
    mock_async_client.create_collection = AsyncMock()

    with patch.object(qdrant_client, "_get_client", return_value=mock_async_client):
        await store.ensure_cluster_collection("test-silo-clusters")

    mock_async_client.create_collection.assert_called_once()
    call_kwargs = mock_async_client.create_collection.call_args.kwargs
    quant = call_kwargs["quantization_config"]
    assert isinstance(quant, ScalarQuantization)
    assert quant.scalar.type == ScalarType.INT8
    assert quant.scalar.always_ram is False


@pytest.mark.asyncio
async def test_migration_script_skips_already_quantized() -> None:
    """Migration skips collections that already have INT8 scalar quantization."""
    from scripts.migrate_qdrant_quantization import run_migration

    # Build a mock collection info that already has INT8 quantization.
    existing_quant = ScalarQuantization(
        scalar=ScalarQuantizationConfig(type=ScalarType.INT8, always_ram=True)
    )
    mock_config = MagicMock()
    mock_config.quantization_config = existing_quant

    mock_collection_info = MagicMock()
    mock_collection_info.config = mock_config

    # Build a mock collection list entry.
    mock_collection_entry = MagicMock()
    mock_collection_entry.name = "ctx_test_silo"

    mock_collections_response = MagicMock()
    mock_collections_response.collections = [mock_collection_entry]

    mock_client = AsyncMock()
    mock_client.get_collections.return_value = mock_collections_response
    mock_client.get_collection.return_value = mock_collection_info
    mock_client.update_collection = AsyncMock()

    with patch("scripts.migrate_qdrant_quantization.AsyncQdrantClient", return_value=mock_client):
        result = await run_migration(dry_run=False)

    # Should return 0 (no updates needed) and never call update_collection.
    assert result == 0
    mock_client.update_collection.assert_not_called()

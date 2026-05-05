"""Tests for weak link creation wired into the embedding asset."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_embedding_asset_creates_weak_links_when_enabled() -> None:
    """Verify embedding asset calls create_weak_links_for_node when enabled."""
    with patch(
        "context_service.pipelines.assets.embedding.create_weak_links_for_node",
        new_callable=AsyncMock,
    ) as mock_create:
        with patch(
            "context_service.pipelines.assets.embedding.get_settings"
        ) as mock_settings:
            mock_settings.return_value.weak_links.enabled = True
            mock_settings.return_value.weak_links.similarity_threshold = 0.75
            mock_settings.return_value.weak_links.max_links_per_node = 5
            mock_settings.return_value.weak_links.top_k_candidates = 10
            mock_settings.return_value.weak_links.initial_weight_multiplier = 0.5
            mock_settings.return_value.weak_links.embedding_model_version = "jina-v3"

            from context_service.pipelines.assets.embedding import _post_embed_hook

            await _post_embed_hook(
                memgraph=AsyncMock(),
                qdrant=AsyncMock(),
                node_id="node-123",
                embedding=[0.1] * 768,
                silo_id="silo-abc",
            )

            mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_embedding_asset_skips_weak_links_when_disabled() -> None:
    """Verify embedding asset skips create_weak_links_for_node when disabled."""
    with patch(
        "context_service.pipelines.assets.embedding.create_weak_links_for_node",
        new_callable=AsyncMock,
    ) as mock_create:
        with patch(
            "context_service.pipelines.assets.embedding.get_settings"
        ) as mock_settings:
            mock_settings.return_value.weak_links.enabled = False

            from context_service.pipelines.assets.embedding import _post_embed_hook

            await _post_embed_hook(
                memgraph=AsyncMock(),
                qdrant=AsyncMock(),
                node_id="node-123",
                embedding=[0.1] * 768,
                silo_id="silo-abc",
            )

            mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_post_embed_hook_passes_correct_params() -> None:
    """Verify hook passes settings values to create_weak_links_for_node."""
    with patch(
        "context_service.pipelines.assets.embedding.create_weak_links_for_node",
        new_callable=AsyncMock,
    ) as mock_create:
        with patch(
            "context_service.pipelines.assets.embedding.get_settings"
        ) as mock_settings:
            mock_settings.return_value.weak_links.enabled = True
            mock_settings.return_value.weak_links.similarity_threshold = 0.8
            mock_settings.return_value.weak_links.max_links_per_node = 3
            mock_settings.return_value.weak_links.top_k_candidates = 7
            mock_settings.return_value.weak_links.initial_weight_multiplier = 0.4
            mock_settings.return_value.weak_links.embedding_model_version = "jina-v3"

            from context_service.pipelines.assets.embedding import _post_embed_hook

            mock_memgraph = AsyncMock()
            mock_qdrant = AsyncMock()
            test_embedding = [0.2] * 768

            await _post_embed_hook(
                memgraph=mock_memgraph,
                qdrant=mock_qdrant,
                node_id="node-456",
                embedding=test_embedding,
                silo_id="silo-xyz",
            )

            mock_create.assert_called_once_with(
                memgraph=mock_memgraph,
                qdrant=mock_qdrant,
                node_id="node-456",
                embedding=test_embedding,
                silo_id="silo-xyz",
                max_links_per_node=3,
                similarity_threshold=0.8,
                top_k_candidates=7,
                initial_weight_multiplier=0.4,
                embedding_model="jina-v3",
            )

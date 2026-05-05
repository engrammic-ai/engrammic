"""Tests for weak link creation asset."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.pipelines.assets.weak_link_creation import (
    MERGE_WEAK_LINK_CYPHER,
    create_weak_links_for_node,
)


def test_merge_cypher_has_required_params():
    assert "$from_id" in MERGE_WEAK_LINK_CYPHER
    assert "$to_id" in MERGE_WEAK_LINK_CYPHER
    assert "$link_id" in MERGE_WEAK_LINK_CYPHER
    assert "$silo_id" in MERGE_WEAK_LINK_CYPHER
    assert "WeakLink" in MERGE_WEAK_LINK_CYPHER
    assert "MERGE" in MERGE_WEAK_LINK_CYPHER


@pytest.mark.asyncio
async def test_create_weak_links_skips_when_at_cap():
    memgraph = AsyncMock()
    qdrant = AsyncMock()

    # Already at cap
    memgraph.execute.return_value = [{"degree": 5}]

    result = await create_weak_links_for_node(
        memgraph=memgraph,
        qdrant=qdrant,
        node_id="node-123",
        embedding=[0.1] * 768,
        silo_id="silo-abc",
        max_links_per_node=5,
        similarity_threshold=0.75,
        top_k_candidates=10,
        initial_weight_multiplier=0.5,
        embedding_model="jina-v3",
    )

    assert result == 0
    qdrant.search.assert_not_called()


@pytest.mark.asyncio
async def test_create_weak_links_filters_by_threshold():
    memgraph = AsyncMock()
    qdrant = AsyncMock()

    memgraph.execute.return_value = [{"degree": 0}]
    qdrant.search.return_value = [
        MagicMock(id="node-a", score=0.9),
        MagicMock(id="node-b", score=0.6),  # Below threshold
    ]

    result = await create_weak_links_for_node(
        memgraph=memgraph,
        qdrant=qdrant,
        node_id="node-123",
        embedding=[0.1] * 768,
        silo_id="silo-abc",
        max_links_per_node=5,
        similarity_threshold=0.75,
        top_k_candidates=10,
        initial_weight_multiplier=0.5,
        embedding_model="jina-v3",
    )

    assert result == 1  # Only node-a passes threshold

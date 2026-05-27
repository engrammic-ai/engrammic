import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from context_service.engine.affinity import AffinityEdge, compute_affinities

NODE_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
NODE_B = uuid.UUID("00000000-0000-0000-0000-000000000002")
NODE_C = uuid.UUID("00000000-0000-0000-0000-000000000003")
NODE_D = uuid.UUID("00000000-0000-0000-0000-000000000004")


def test_affinity_edge_schema():
    edge = AffinityEdge(
        source_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        similarity=0.87,
        source_embedding_model="text-embedding-3-small",
    )
    assert edge.similarity >= 0.85
    assert edge.source_embedding_model == "text-embedding-3-small"
    assert edge.created_at is not None


def test_affinity_edge_rejects_low_similarity():
    with pytest.raises(ValidationError):
        AffinityEdge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            similarity=0.84,  # Below threshold
            source_embedding_model="text-embedding-3-small",
        )


@pytest.mark.asyncio
async def test_compute_affinities_finds_similar_nodes():
    mock_qdrant = MagicMock()
    mock_qdrant.query_points = AsyncMock(return_value=MagicMock(points=[
        MagicMock(id=str(NODE_B), score=0.92),
        MagicMock(id=str(NODE_C), score=0.88),
        MagicMock(id=str(NODE_D), score=0.75),  # Below threshold
    ]))

    embedding = [0.1] * 1536

    edges = await compute_affinities(
        qdrant=mock_qdrant,
        source_id=NODE_A,
        embedding=embedding,
        silo_id="test_silo",
        collection_name="knowledge",
        embedding_model="text-embedding-3-small",
    )

    assert len(edges) == 2  # Only NODE_B and NODE_C above threshold
    assert edges[0].target_id == NODE_B
    assert edges[0].similarity == 0.92
    assert edges[1].target_id == NODE_C


@pytest.mark.asyncio
async def test_compute_affinities_excludes_self():
    mock_qdrant = MagicMock()
    mock_qdrant.query_points = AsyncMock(return_value=MagicMock(points=[
        MagicMock(id=str(NODE_A), score=1.0),  # Self - should be excluded
        MagicMock(id=str(NODE_B), score=0.90),
    ]))

    embedding = [0.1] * 1536

    edges = await compute_affinities(
        qdrant=mock_qdrant,
        source_id=NODE_A,
        embedding=embedding,
        silo_id="test_silo",
        collection_name="knowledge",
        embedding_model="text-embedding-3-small",
    )

    assert len(edges) == 1
    assert edges[0].target_id == NODE_B

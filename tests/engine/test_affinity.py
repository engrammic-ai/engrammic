import pytest
from context_service.engine.affinity import AffinityEdge, compute_affinities


def test_affinity_edge_schema():
    edge = AffinityEdge(
        source_id="node_a",
        target_id="node_b",
        similarity=0.87,
        source_embedding_model="text-embedding-3-small",
    )
    assert edge.similarity >= 0.85
    assert edge.source_embedding_model == "text-embedding-3-small"
    assert edge.created_at is not None

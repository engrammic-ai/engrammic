"""Write-time affinity computation for Knowledge nodes.

Computes k-NN similarity at store time and creates AFFINITY edges
for fast lookup during tick().
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

AFFINITY_THRESHOLD = 0.85
AFFINITY_K = 3


class AffinityEdge(BaseModel):
    """Edge representing semantic affinity between Knowledge nodes."""

    source_id: uuid.UUID
    target_id: uuid.UUID
    similarity: float = Field(ge=0.85, le=1.0)
    source_embedding_model: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


async def compute_affinities(
    qdrant: AsyncQdrantClient,
    source_id: uuid.UUID,
    embedding: list[float],
    silo_id: str,
    collection_name: str,
    embedding_model: str,
    k: int = AFFINITY_K,
    threshold: float = AFFINITY_THRESHOLD,
) -> list[AffinityEdge]:
    """Compute affinity edges for a node against existing embeddings.

    Queries Qdrant for the k nearest neighbours above the threshold and
    returns AffinityEdge instances ready for persistence.

    Args:
        qdrant: AsyncQdrantClient instance.
        source_id: UUID of the node being stored (excluded from results).
        embedding: Embedding vector for the node.
        silo_id: Tenant silo identifier for filtering.
        collection_name: Qdrant collection name.
        embedding_model: Name of the embedding model used.
        k: Maximum number of neighbours to return.
        threshold: Minimum similarity score to include.

    Returns:
        List of AffinityEdge instances, one per qualifying neighbour.
    """
    results = await qdrant.query_points(
        collection_name=collection_name,
        query=embedding,
        limit=k + 1,
        query_filter=Filter(
            must=[FieldCondition(key="silo_id", match=MatchValue(value=silo_id))]
        ),
    )

    edges: list[AffinityEdge] = []
    for point in results.points:
        if str(point.id) == str(source_id):
            continue
        if point.score < threshold:
            continue
        if len(edges) >= k:
            break

        edges.append(
            AffinityEdge(
                source_id=source_id,
                target_id=uuid.UUID(str(point.id)),
                similarity=point.score,
                source_embedding_model=embedding_model,
            )
        )

    return edges


STORE_AFFINITY_QUERY = """
MATCH (a {id: $source_id, silo_id: $silo_id})
MATCH (b {id: $target_id, silo_id: $silo_id})
MERGE (a)-[r:AFFINITY]->(b)
SET r.similarity = $similarity,
    r.created_at = $created_at,
    r.source_embedding_model = $embedding_model
RETURN r
"""


async def store_affinity_edges(
    store: HyperGraphStore,
    edges: list[AffinityEdge],
    silo_id: str,
) -> None:
    """Store affinity edges in the graph.

    Creates AFFINITY relationships between Knowledge nodes using Cypher MERGE,
    so repeated calls are idempotent.
    """
    for edge in edges:
        await store.execute_write(
            STORE_AFFINITY_QUERY,
            {
                "source_id": str(edge.source_id),
                "target_id": str(edge.target_id),
                "silo_id": silo_id,
                "similarity": edge.similarity,
                "created_at": edge.created_at.isoformat(),
                "embedding_model": edge.source_embedding_model,
            },
        )

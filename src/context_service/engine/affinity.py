"""Write-time affinity computation for Knowledge nodes.

Computes k-NN similarity at store time and creates AFFINITY edges
for fast lookup during tick().
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

AFFINITY_THRESHOLD = 0.85
AFFINITY_K = 3


class AffinityEdge(BaseModel):
    """Edge representing semantic affinity between Knowledge nodes."""

    source_id: uuid.UUID
    target_id: uuid.UUID
    similarity: float = Field(ge=0.85, le=1.0)
    source_embedding_model: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compute_affinities(
    node_id: str,
    embedding: list[float],
    model: str,
    collection: str,
    k: int = AFFINITY_K,
    threshold: float = AFFINITY_THRESHOLD,
) -> list[AffinityEdge]:
    """Compute affinity edges for a node against existing embeddings.

    Queries Qdrant for the k nearest neighbours above the threshold and
    returns AffinityEdge instances ready for persistence.

    This function is a stub; full implementation is in a subsequent task
    once the async store integration layer is in place.

    Args:
        node_id: ID of the node being stored.
        embedding: Embedding vector for the node.
        model: Name of the embedding model used.
        collection: Qdrant collection name.
        k: Maximum number of neighbours to return.
        threshold: Minimum similarity score to include.

    Returns:
        List of AffinityEdge instances, one per qualifying neighbour.
    """
    raise NotImplementedError("compute_affinities requires async store integration")

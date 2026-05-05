"""Weak link creation after embedding.

Creates speculative RELATED_TO edges (reified as WeakLink nodes) between
semantically similar nodes based on embedding cosine similarity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from context_service.signals.edge_access_events import edge_id

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore, VectorStore

logger = structlog.get_logger(__name__)

DEGREE_CHECK_CYPHER = """
MATCH (n {id: $node_id, silo_id: $silo_id})-[:SOURCE_OF]->(:WeakLink)
RETURN count(*) AS degree
"""

MERGE_WEAK_LINK_CYPHER = """
MATCH (a {id: $from_id, silo_id: $silo_id})
MATCH (b {id: $to_id, silo_id: $silo_id})
MERGE (w:WeakLink {id: $link_id, silo_id: $silo_id})
ON CREATE SET
    w.weight = $weight,
    w.speculative = true,
    w.created_at = datetime(),
    w.source = 'embedding_similarity',
    w.embedding_model = $embedding_model,
    w.edge_heat = 0.0,
    w.from_node = $from_id,
    w.to_node = $to_id
MERGE (a)-[:SOURCE_OF]->(w)
MERGE (w)-[:TARGETS]->(b)
RETURN w.id AS created
"""


async def create_weak_links_for_node(
    memgraph: HyperGraphStore,
    qdrant: VectorStore,
    node_id: str,
    embedding: list[float],
    silo_id: str,
    max_links_per_node: int,
    similarity_threshold: float,
    top_k_candidates: int,
    initial_weight_multiplier: float,
    embedding_model: str,
) -> int:
    """Create weak links for a newly embedded node. Returns count created."""
    # Check existing degree
    result = await memgraph.execute(
        DEGREE_CHECK_CYPHER,
        {"node_id": node_id, "silo_id": silo_id},
    )
    existing_degree = result[0]["degree"] if result else 0
    budget = max(0, max_links_per_node - existing_degree)

    if budget == 0:
        return 0

    # Search for similar nodes
    similar = await qdrant.search(
        vector=embedding,
        limit=top_k_candidates,
        filter_conditions={"silo_id": silo_id},
    )

    # Filter by threshold and cap to budget
    candidates = [c for c in similar if c.score >= similarity_threshold and c.id != node_id]
    candidates = candidates[:budget]

    created = 0
    for candidate in candidates:
        # Sort IDs for deterministic edge direction
        a, b = sorted([node_id, candidate.id])
        link_id = edge_id(a, b, "RELATED_TO")

        await memgraph.execute(
            MERGE_WEAK_LINK_CYPHER,
            {
                "from_id": a,
                "to_id": b,
                "link_id": link_id,
                "silo_id": silo_id,
                "weight": candidate.score * initial_weight_multiplier,
                "embedding_model": embedding_model,
            },
        )
        created += 1

    if created > 0:
        logger.info(
            "weak_links_created",
            node_id=node_id,
            silo_id=silo_id,
            count=created,
        )

    return created

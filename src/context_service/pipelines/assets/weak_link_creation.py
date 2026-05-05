"""Weak link creation after embedding.

Creates speculative RELATED_TO edges (reified as WeakLink nodes) between
semantically similar nodes based on embedding cosine similarity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from context_service.signals.edge_access_events import edge_id

if TYPE_CHECKING:
    from context_service.engine.qdrant_store import EngineQdrantStore
    from context_service.stores import MemgraphClient

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
    memgraph: MemgraphClient,
    qdrant: EngineQdrantStore,
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
    result = await memgraph.execute_query(
        DEGREE_CHECK_CYPHER,
        {"node_id": node_id, "silo_id": silo_id},
    )
    existing_degree = result[0]["degree"] if result else 0
    budget = max(0, max_links_per_node - existing_degree)

    if budget == 0:
        return 0

    # Search for similar nodes (dense-only mode for weak link discovery)
    similar = await qdrant.query(
        vector=embedding,
        silo_id=silo_id,
        limit=top_k_candidates,
        search_mode="dense",
        score_threshold=similarity_threshold,
    )

    # Filter self and cap to budget (threshold already applied by query)
    candidates = [c for c in similar if c.node_id != node_id]
    candidates = candidates[:budget]

    created = 0
    for candidate in candidates:
        # Sort IDs for deterministic edge direction
        a, b = sorted([node_id, candidate.node_id])
        link_id = edge_id(a, b, "RELATED_TO")

        await memgraph.execute_write(
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

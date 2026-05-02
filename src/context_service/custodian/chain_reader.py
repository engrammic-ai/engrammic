"""Stitch-phase tool: read_reasoning_chains and read_commitments_in_cluster."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore


READ_REASONING_CHAINS = """
MATCH (c:ReasoningChain)-[:CRYSTALLIZED_INTO]->(:Claim)-[:IN_CLUSTER]->(:Cluster {id: $cluster_id})
WHERE $include_drafts OR c.status IN ['published', 'superseded']
RETURN c, labels(c) AS labels
ORDER BY c.heat_score DESC
LIMIT $limit
"""

READ_COMMITMENTS_IN_CLUSTER = """
MATCH (c:Claim:Commitment)-[:IN_CLUSTER]->(:Cluster {id: $cluster_id})
WHERE $include_drafts OR c.status IN ['published', 'superseded']
RETURN c, labels(c) AS labels
ORDER BY c.distinct_agent_count DESC
LIMIT $limit
"""


async def read_reasoning_chains(
    *,
    memgraph: HyperGraphStore,
    cluster_id: str,
    include_drafts: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read reasoning chains crystallized into claims within a cluster.

    Used by Custodian stitch phase to seed deep-pass with pre-computed reasoning.
    """
    rows = await memgraph.execute_query(
        READ_REASONING_CHAINS,
        {"cluster_id": cluster_id, "include_drafts": include_drafts, "limit": limit},
    )
    return [dict(r["c"]) for r in rows]


async def read_commitments_in_cluster(
    *,
    memgraph: HyperGraphStore,
    cluster_id: str,
    include_drafts: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read commitments within a cluster."""
    rows = await memgraph.execute_query(
        READ_COMMITMENTS_IN_CLUSTER,
        {"cluster_id": cluster_id, "include_drafts": include_drafts, "limit": limit},
    )
    return [dict(r["c"]) for r in rows]


__all__ = ["read_commitments_in_cluster", "read_reasoning_chains"]

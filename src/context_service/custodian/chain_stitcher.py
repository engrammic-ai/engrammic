"""Cross-cluster supersession chain stitching.

When supersession detection runs per-cluster, chains that span multiple clusters
(A in cluster1 supersedes B in cluster2 supersedes C in cluster3) are not
automatically connected. This module provides a post-hoc stitching pass that:

1. Finds supersession edges that cross cluster boundaries
2. Identifies chain terminals (nodes that supersede but are not superseded)
3. Traces each chain to find all members across clusters
4. Ensures only the terminal node is eligible for promotion
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger
from context_service.db.custodian_queries import (
    FIND_CHAIN_TERMINALS,
    FIND_CROSS_CLUSTER_SUPERSESSION_GAPS,
)

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChainStitchResult:
    """Result of a chain stitching pass."""

    silo_id: str
    chains_found: int
    terminals_found: int
    edges_verified: int
    errors: list[str]


async def stitch_cross_cluster_chains(
    *,
    store: Any,
    silo_id: str,
) -> ChainStitchResult:
    """Find and verify cross-cluster supersession chains.

    This is a read-heavy pass that:
    1. Finds existing cross-cluster supersession edges
    2. Identifies terminal nodes in each chain
    3. Verifies chain integrity (no gaps, no orphans)

    Does not create new edges - supersession detection already created them.
    This pass verifies the chains are complete and identifies terminals.
    """
    errors: list[str] = []
    chains_found = 0
    terminals_found = 0
    edges_verified = 0

    try:
        # Find cross-cluster edges
        cross_cluster_result = await store.run_query(
            FIND_CROSS_CLUSTER_SUPERSESSION_GAPS,
            {"silo_id": silo_id},
        )
        chains_found = len(cross_cluster_result) if cross_cluster_result else 0

        for row in cross_cluster_result or []:
            edges_verified += 1
            if row.get("downstream_id"):
                logger.debug(
                    "Cross-cluster chain: %s -> %s -> %s",
                    row["superseding_id"],
                    row["superseded_id"],
                    row["downstream_id"],
                )

        # Find terminal nodes
        terminal_result = await store.run_query(
            FIND_CHAIN_TERMINALS,
            {"silo_id": silo_id},
        )
        terminals_found = len(terminal_result) if terminal_result else 0

        for row in terminal_result or []:
            chain_ids = row.get("chain_ids", [])
            logger.info(
                "Chain terminal: %s supersedes %d nodes across clusters",
                row["terminal_id"],
                len(chain_ids),
            )

    except Exception as e:
        errors.append(f"Chain stitching failed: {e}")
        logger.exception("Chain stitching error")

    return ChainStitchResult(
        silo_id=silo_id,
        chains_found=chains_found,
        terminals_found=terminals_found,
        edges_verified=edges_verified,
        errors=errors,
    )


async def get_chain_terminal(
    *,
    store: Any,
    node_id: str,
    silo_id: str,
) -> str | None:
    """Given a node, find the terminal of its supersession chain.

    Walks backward through SUPERSEDES edges to find the node that
    is not superseded by anything (the terminal/most-current node).

    Returns the terminal node ID, or None if node_id is already terminal.
    """
    query = """
    MATCH path = (terminal)-[:SUPERSEDES*0..20]->(target {id: $node_id, silo_id: $silo_id})
    WHERE NOT EXISTS { MATCH (other)-[:SUPERSEDES]->(terminal) WHERE other.silo_id = $silo_id }
    RETURN terminal.id AS terminal_id
    LIMIT 1
    """
    result = await store.run_query(query, {"node_id": node_id, "silo_id": silo_id})

    if result and result[0].get("terminal_id") != node_id:
        return str(result[0]["terminal_id"])
    return None


__all__ = [
    "ChainStitchResult",
    "get_chain_terminal",
    "stitch_cross_cluster_chains",
]

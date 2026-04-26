"""Sensor for consensus-on-chains task type."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_service.stores.memgraph import MemgraphClient


FIND_CONSENSUS_CANDIDATES = """
MATCH (chain:ReasoningChain)-[:CRYSTALLIZED_INTO]->(target)
WHERE (target:Claim OR target:Commitment)
  AND chain.silo_id = $silo_id
  AND chain.status IN ['draft', 'published']
WITH target, count(DISTINCT chain) AS chain_count,
     count(DISTINCT chain.produced_by_agent_id) AS distinct_agents
WHERE chain_count >= $min_chain_count
  AND distinct_agents >= $min_distinct_agents
RETURN target.id AS commitment_id, chain_count, distinct_agents
ORDER BY distinct_agents DESC, chain_count DESC
LIMIT $limit
"""


async def find_consensus_candidates(
    *,
    memgraph: MemgraphClient,
    silo_id: str,
    min_chain_count: int = 2,
    min_distinct_agents: int = 2,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find commitments/claims with multi-agent chain consensus."""
    rows = await memgraph.execute_query(
        FIND_CONSENSUS_CANDIDATES,
        {
            "silo_id": silo_id,
            "min_chain_count": min_chain_count,
            "min_distinct_agents": min_distinct_agents,
            "limit": limit,
        },
    )
    return [
        {
            "commitment_id": r["commitment_id"],
            "chain_count": r["chain_count"],
            "distinct_agents": r["distinct_agents"],
        }
        for r in rows
        if r["distinct_agents"] >= min_distinct_agents
    ]


__all__ = ["find_consensus_candidates"]

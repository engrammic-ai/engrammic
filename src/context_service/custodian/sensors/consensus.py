"""Sensor for the consensus_on_chains custodian task type.

Returns candidates ranked by ``compute_consensus_priority`` (confidence gap *
heat * agent diversity), not by raw `(distinct_agents, chain_count)`. This
keeps the custodian focused on hot, contested, multi-agent chains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.signals import compute_consensus_priority, get_heat

if TYPE_CHECKING:
    from context_service.stores.memgraph import MemgraphClient


FIND_CONSENSUS_CANDIDATES = """
MATCH (chain:ReasoningChain)-[:CRYSTALLIZED_INTO]->(target)
WHERE (target:Claim OR target:Commitment)
  AND chain.silo_id = $silo_id
  AND chain.status IN ['draft', 'published']
WITH target,
     count(DISTINCT chain) AS chain_count,
     count(DISTINCT chain.produced_by_agent_id) AS distinct_agents,
     avg(coalesce(chain.confidence, 0.5)) AS avg_chain_confidence
WHERE chain_count >= $min_chain_count
  AND distinct_agents >= $min_distinct_agents
RETURN target.id AS commitment_id,
       chain_count,
       distinct_agents,
       avg_chain_confidence
"""


async def find_consensus_candidates(
    *,
    memgraph: MemgraphClient,
    silo_id: str,
    min_chain_count: int = 2,
    min_distinct_agents: int = 2,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find commitments / claims with multi-agent chain consensus.

    Returns up to ``limit`` candidates ranked DESC by ``compute_consensus_priority``.
    Heat is fetched per-candidate via ``signals.heat.get_heat`` (Phase 1: stub
    returns 0.5; Phase 2: real Memgraph read with a batched UNWIND query — see
    the v1c plan for the migration step).
    """
    rows = await memgraph.execute_query(
        FIND_CONSENSUS_CANDIDATES,
        {
            "silo_id": silo_id,
            "min_chain_count": min_chain_count,
            "min_distinct_agents": min_distinct_agents,
        },
    )

    candidates: list[dict[str, Any]] = []
    for r in rows:
        if r["distinct_agents"] < min_distinct_agents:
            continue
        target_id = r["commitment_id"]
        heat = await get_heat(memgraph, target_id, silo_id)
        priority = compute_consensus_priority(
            avg_chain_confidence=float(r["avg_chain_confidence"]),
            avg_heat=heat,
            distinct_agent_count=int(r["distinct_agents"]),
        )
        candidates.append(
            {
                "commitment_id": target_id,
                "chain_count": int(r["chain_count"]),
                "distinct_agents": int(r["distinct_agents"]),
                "avg_chain_confidence": float(r["avg_chain_confidence"]),
                "heat": heat,
                "priority": priority,
            }
        )

    candidates.sort(key=lambda c: c["priority"], reverse=True)
    return candidates[:limit]


__all__ = ["FIND_CONSENSUS_CANDIDATES", "find_consensus_candidates"]

"""Sensor for the consensus_on_chains custodian task type.

Returns candidates ranked by ``compute_consensus_priority`` (confidence gap *
heat * agent diversity), not by raw `(distinct_agents, chain_count)`. This
keeps the custodian focused on hot, contested, multi-agent chains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.db.queries import GET_SEED_HEAT_BATCH
from context_service.signals import compute_consensus_priority

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore


# Prefetch cap: Cypher returns up to PREFETCH_MULTIPLIER * limit rows so the
# Python-side priority sort sees enough candidates to rank meaningfully without
# pulling unbounded result sets from Memgraph.
PREFETCH_MULTIPLIER = 10

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
LIMIT $prefetch_limit
"""


async def find_consensus_candidates(
    *,
    memgraph: HyperGraphStore,
    silo_id: str,
    min_chain_count: int = 2,
    min_distinct_agents: int = 2,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find commitments / claims with multi-agent chain consensus.

    Returns up to ``limit`` candidates ranked DESC by ``compute_consensus_priority``.
    Heat is fetched for all qualifying candidates in a single batch query using
    ``GET_SEED_HEAT_BATCH``.
    """
    rows = await memgraph.execute_query(
        FIND_CONSENSUS_CANDIDATES,
        {
            "silo_id": silo_id,
            "min_chain_count": min_chain_count,
            "min_distinct_agents": min_distinct_agents,
            "prefetch_limit": limit * PREFETCH_MULTIPLIER,
        },
    )

    # Collect qualifying target_ids, then fetch all heats in one batch query.
    qualifying = [r for r in rows if r["distinct_agents"] >= min_distinct_agents]
    seed_ids = [r["commitment_id"] for r in qualifying]

    heat_map: dict[str, float] = {}
    if seed_ids:
        heat_rows = await memgraph.execute_query(
            GET_SEED_HEAT_BATCH,
            {"seed_ids": seed_ids, "silo_id": silo_id},
        )
        heat_map = {hr["node_id"]: float(hr["heat"]) for hr in heat_rows}

    candidates: list[dict[str, Any]] = []
    for r in qualifying:
        target_id = r["commitment_id"]
        heat = heat_map.get(target_id, 0.0)
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


__all__ = ["FIND_CONSENSUS_CANDIDATES", "PREFETCH_MULTIPLIER", "find_consensus_candidates"]

"""Handler for consensus_on_chains task type."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from context_service.custodian.consensus_promotion import promote_consensus_to_finding

if TYPE_CHECKING:
    from context_service.stores.memgraph import MemgraphClient


class ConsensusResult(TypedDict, total=False):
    promoted: bool
    reason: str
    finding_id: str
    distinct_agents: int
    avg_confidence: float
    chains_superseded: int


GET_CHAINS_FOR_COMMITMENT = """
MATCH (chain:ReasoningChain)-[:CRYSTALLIZED_INTO]->(c {id: $commitment_id})
WHERE chain.status = 'published'
RETURN chain.id AS id, chain.produced_by_agent_id AS produced_by_agent_id,
       COALESCE(chain.confidence, 0.5) AS confidence
"""


async def handle_consensus_task(
    *,
    memgraph: MemgraphClient,
    commitment_id: str,
    silo_id: str,
    min_distinct_agents: int = 2,
    min_avg_confidence: float = 0.7,
) -> ConsensusResult:
    """Handle a consensus_on_chains task for a commitment.

    Checks if chains meet promotion threshold and promotes if so.
    """
    chains = await memgraph.execute_query(
        GET_CHAINS_FOR_COMMITMENT,
        {"commitment_id": commitment_id},
    )

    if not chains:
        return {"promoted": False, "reason": "no_chains"}

    distinct_agents = len({c["produced_by_agent_id"] for c in chains})
    avg_confidence = sum(c["confidence"] for c in chains) / len(chains)

    if distinct_agents < min_distinct_agents:
        return {
            "promoted": False,
            "reason": "insufficient_agent_diversity",
            "distinct_agents": distinct_agents,
        }

    if avg_confidence < min_avg_confidence:
        return {
            "promoted": False,
            "reason": "low_confidence",
            "avg_confidence": avg_confidence,
        }

    chain_ids = [c["id"] for c in chains]
    finding_id = await promote_consensus_to_finding(
        memgraph=memgraph,
        commitment_id=commitment_id,
        contributing_chain_ids=chain_ids,
        silo_id=silo_id,
    )

    return {
        "promoted": True,
        "finding_id": finding_id,
        "distinct_agents": distinct_agents,
        "avg_confidence": avg_confidence,
        "chains_superseded": len(chain_ids),
    }


__all__ = ["handle_consensus_task"]

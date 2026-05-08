"""Proposal Worker: creates ProposedBelief nodes for weak synthesis candidates.

Detects clusters where synthesis confidence falls between proposal_threshold and
auto_synthesis_threshold, and creates ProposedBelief nodes awaiting validation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from primitives.eag import noisy_or_aggregate
from pydantic_ai import Agent

from context_service.config.settings import get_settings
from context_service.custodian.agents import proposal_synthesis_limits
from context_service.custodian.prompt_loader import load_prompt
from context_service.db.queries import (
    CREATE_PROPOSED_BELIEF,
    GET_PENDING_PROPOSAL_COUNT_FOR_SILO,
    LIST_DENSE_CLUSTERS_WITHOUT_BELIEF_OR_PROPOSAL,
)
from context_service.llm.sanitize import escape_for_prompt

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.models.silo import ResolvedSiloConfig

PROPOSAL_TTL_DAYS = 7
MAX_PENDING_PER_SILO = 20

PROPOSAL_SYNTHESIS_SYSTEM_PROMPT = load_prompt("prompts/custodian/proposal_synthesis.yaml")


async def estimate_cluster_confidence(
    graph_store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
) -> float:
    """Estimate synthesis confidence for a cluster using noisy-or aggregation.

    Fetches confidences of all facts in the cluster and aggregates them.
    """
    query = """
    MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
    RETURN f.confidence AS confidence
    """
    rows = await graph_store.execute_query(query, {"cluster_id": cluster_id, "silo_id": silo_id})

    confidences = [float(r["confidence"]) for r in rows if r.get("confidence") is not None]
    if not confidences:
        return 0.0

    return noisy_or_aggregate(confidences)


async def get_cluster_facts(
    graph_store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
) -> list[dict[str, Any]]:
    """Fetch facts belonging to a cluster."""
    query = """
    MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
    RETURN f.id AS fact_id, f.content AS content, f.confidence AS confidence
    """
    rows = await graph_store.execute_query(query, {"cluster_id": cluster_id, "silo_id": silo_id})
    return [dict(r) for r in rows]


async def get_proposal_candidates(
    graph_store: HyperGraphStore,
    silo_id: str,
    config: ResolvedSiloConfig,
) -> list[dict[str, Any]]:
    """Find clusters that qualify for ProposedBelief creation.

    Returns clusters where:
    - fact count >= belief_density_threshold
    - no existing Belief or pending ProposedBelief
    - estimated confidence in [proposal_threshold, auto_synthesis_threshold)
    """
    rows = await graph_store.execute_query(
        LIST_DENSE_CLUSTERS_WITHOUT_BELIEF_OR_PROPOSAL,
        {"silo_id": silo_id, "min_facts": config.belief_density_threshold},
    )

    candidates = []
    for row in rows:
        cluster_id = str(row["cluster_id"])
        confidence = await estimate_cluster_confidence(graph_store, cluster_id, silo_id)

        if config.proposal_threshold <= confidence < config.auto_synthesis_threshold:
            candidates.append(
                {
                    "cluster_id": cluster_id,
                    "fact_count": int(row["fact_count"]),
                    "confidence": confidence,
                }
            )

    return candidates


async def synthesize_proposal_content(fact_contents: list[str]) -> str:
    """Generate belief content from fact contents using LLM."""
    settings = get_settings()

    agent = Agent(
        model=settings.custodian.flash_model,
        system_prompt=PROPOSAL_SYNTHESIS_SYSTEM_PROMPT,
    )

    user_prompt = "Given these facts:\n" + "\n".join(
        f"- {escape_for_prompt(c)}" for c in fact_contents
    )
    user_prompt += "\n\nSynthesize a belief statement that captures the pattern."

    result = await agent.run(user_prompt)
    return str(result.output).strip()


async def create_proposal(
    graph_store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    confidence: float,
) -> str | None:
    """Create a ProposedBelief for a cluster if under per-silo limit.

    Returns the proposal ID if created, None if limit reached.
    """
    count_result = await graph_store.execute_query(
        GET_PENDING_PROPOSAL_COUNT_FOR_SILO,
        {"silo_id": silo_id},
    )
    pending_count = int(count_result[0]["pending_count"]) if count_result else 0

    if pending_count >= MAX_PENDING_PER_SILO:
        return None

    facts = await get_cluster_facts(graph_store, cluster_id, silo_id)
    if not facts:
        return None

    fact_contents = [f["content"] for f in facts if f.get("content")]
    fact_ids = [f["fact_id"] for f in facts]

    content = await synthesize_proposal_content(fact_contents)

    now = datetime.now(UTC)
    proposal_id = str(uuid.uuid4())

    await graph_store.execute_query(
        CREATE_PROPOSED_BELIEF,
        {
            "id": proposal_id,
            "silo_id": silo_id,
            "content": content,
            "confidence": confidence,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=PROPOSAL_TTL_DAYS)).isoformat(),
            "synthesized_from_ids": fact_ids,
        },
    )

    return proposal_id


async def run_proposal_detection(
    graph_store: HyperGraphStore,
    silo_id: str,
    config: ResolvedSiloConfig,
) -> list[str]:
    """Run proposal detection for a silo.

    Returns list of created proposal IDs.
    """
    candidates = await get_proposal_candidates(graph_store, silo_id, config)
    created_ids: list[str] = []

    for candidate in candidates:
        proposal_id = await create_proposal(
            graph_store,
            cluster_id=candidate["cluster_id"],
            silo_id=silo_id,
            confidence=candidate["confidence"],
        )
        if proposal_id:
            created_ids.append(proposal_id)

    return created_ids

"""Proposal Worker: creates ProposedBelief nodes for weak synthesis candidates.

Detects clusters where synthesis confidence falls between proposal_threshold and
auto_synthesis_threshold, and creates ProposedBelief nodes awaiting validation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent

from context_service.config.settings import get_settings
from context_service.custodian.agents import proposal_synthesis_limits
from context_service.custodian.prompt_loader import load_prompt
from context_service.db.queries import (
    CREATE_PROPOSED_BELIEF,
    GET_PENDING_PROPOSAL_COUNT_FOR_SILO,
    GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER,
)
from context_service.llm.sanitize import escape_for_prompt

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.models.silo import ResolvedSiloConfig

PROPOSAL_TTL_DAYS = 7

PROPOSAL_SYNTHESIS_SYSTEM_PROMPT = load_prompt("prompts/custodian/proposal_synthesis.yaml")


async def estimate_cluster_confidence(
    graph_store: HyperGraphStore,  # noqa: ARG001
    cluster_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> float:
    """DEPRECATED (CITE v2): Clustering removed. Returns 0.0."""
    # TODO: Remove function after all callers are updated to v2 APIs.
    return 0.0


async def get_cluster_facts(
    graph_store: HyperGraphStore,  # noqa: ARG001
    cluster_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """DEPRECATED (CITE v2): Clustering removed. Returns empty list."""
    # TODO: Remove function after all callers are updated to v2 APIs.
    return []


async def get_proposal_candidates(
    graph_store: HyperGraphStore,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
    config: ResolvedSiloConfig,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """DEPRECATED (CITE v2): Clustering removed. Returns empty list."""
    # TODO: Remove function after all callers are updated to v2 APIs.
    return []


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

    result = await asyncio.wait_for(
        agent.run(user_prompt, usage_limits=proposal_synthesis_limits()),
        timeout=20.0,
    )
    return str(result.output).strip()


async def was_recently_rejected(
    graph_store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    cooldown_hours: int,
) -> bool:
    """Return True if a ProposedBelief for this cluster was rejected within the cooldown window."""
    cutoff = (datetime.now(UTC) - timedelta(hours=cooldown_hours)).isoformat()
    rows = await graph_store.execute_query(
        GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER,
        {"silo_id": silo_id, "cluster_id": cluster_id, "cutoff": cutoff},
    )
    rejected_count = int(rows[0]["rejected_count"]) if rows else 0
    return rejected_count > 0


async def create_proposal(
    graph_store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    confidence: float,
    max_pending: int,
    cooldown_hours: int,
) -> str | None:
    """Create a ProposedBelief for a cluster if under per-silo limit and not in cooldown.

    Returns the proposal ID if created, None if limit reached or cooldown active.
    """
    count_result = await graph_store.execute_query(
        GET_PENDING_PROPOSAL_COUNT_FOR_SILO,
        {"silo_id": silo_id},
    )
    pending_count = int(count_result[0]["pending_count"]) if count_result else 0

    if pending_count >= max_pending:
        return None

    if await was_recently_rejected(graph_store, cluster_id, silo_id, cooldown_hours):
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
    settings = get_settings()
    max_pending = settings.max_proposals_per_silo
    cooldown_hours = settings.proposal_cooldown_hours

    candidates = await get_proposal_candidates(graph_store, silo_id, config)
    created_ids: list[str] = []

    for candidate in candidates:
        proposal_id = await create_proposal(
            graph_store,
            cluster_id=candidate["cluster_id"],
            silo_id=silo_id,
            confidence=candidate["confidence"],
            max_pending=max_pending,
            cooldown_hours=cooldown_hours,
        )
        if proposal_id:
            created_ids.append(proposal_id)

    return created_ids

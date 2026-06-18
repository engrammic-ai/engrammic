# src/context_service/mcp/tools/decide.py
"""MCP tool: decide - Declare a decision/commitment directly.

DEPRECATED (CITE v2): Wisdom writes are now passive (system-synthesized).
This tool is kept for backward compatibility only. Use learn() for new work;
SAGE promotes Claims to Facts and synthesizes Beliefs/Commitments automatically.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

import structlog

from context_service.db import queries as q
from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_postgres_store,
    track_tool_usage,
)
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation
from context_service.sage.transactions import commit as tx_commit
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_belief_confidence, record_mcp_tool

logger = structlog.get_logger()


@rate_limited("decide")
async def _decide_impl(
    decision: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Implementation for decide tool."""
    from context_service.mcp.tools.context_store import (
        create_supersession,
        validate_supersession_target,
    )

    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "decide")

    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    silo_uuid = derive_silo_id(auth.org_id)
    silo_id = str(silo_uuid)
    ctx_svc = get_context_service()
    agent_id = auth.agent_id or auth.org_id

    if supersedes:
        validation_error = await validate_supersession_target(silo_id, supersedes)
        if validation_error:
            return validation_error

    try:
        result, events = await tx_commit(
            store=ctx_svc.graph_store,
            content=decision,
            about_refs=about,
            silo_id=silo_id,
            agent_id=agent_id,
            confidence=confidence,
            metadata={"reasoning": reasoning} if reasoning else None,
            emit=False,
        )

        if supersedes:
            await create_supersession(result.commitment_id, supersedes, silo_id)

        for event in events:
            await emit_reaction(event)

        record_belief_confidence(confidence, silo_id=silo_id)

        # Auto-create ReasoningChain when reasoning is provided (supplementary).
        # Commitment is always the primary artifact - chain failure does not block.
        chain_id: uuid.UUID | None = None
        if reasoning:
            from context_service.engine.chain_saga import ChainSagaWriter
            from context_service.models.inference import ChainStep

            chain_id = uuid.uuid4()
            saga = ChainSagaWriter(get_postgres_store(), ctx_svc.graph_store)

            try:
                await saga.write_chain(
                    chain_id=chain_id,
                    silo_id=silo_uuid,
                    steps=[
                        ChainStep(
                            step_index=0,
                            operation="decide",
                            conclusion=reasoning,
                            confidence=confidence,
                            premise_refs=about,
                        )
                    ],
                    produced_by_model="agent",
                    produced_by_agent_id=agent_id,
                    status="committed",
                    source="decide_reasoning",
                    conclusion=decision,
                    evidence_used=about,
                )

                # Link chain to commitment in the graph.
                await ctx_svc.graph_store.execute_write(
                    q.LINK_CHAIN_TO_COMMITMENT,
                    {
                        "chain_id": str(chain_id),
                        "commitment_id": str(result.commitment_id),
                        "silo_id": silo_id,
                    },
                )

                # Embed chain conclusion for recall-time surfacing.
                from context_service.mcp.tools.context_store import (
                    _upsert_chain_embedding,
                    embed,
                )

                try:
                    conclusion_embedding = await embed(decision)
                    await _upsert_chain_embedding(
                        chain_id,
                        silo_id,
                        conclusion_embedding,
                        evidence_used=about,
                    )
                except Exception:
                    logger.warning("decide_chain_embedding_failed", chain_id=str(chain_id))

            except Exception as exc:
                logger.warning("decide_chain_write_failed", error=str(exc))
                chain_id = None

        response: dict[str, Any] = {
            "commitment_id": str(result.commitment_id),
            "created_at": result.created_at.isoformat(),
            "confidence": result.confidence,
        }
        if supersedes:
            response["supersedes"] = supersedes
        if chain_id:
            response["chain_id"] = str(chain_id)
        return response

    except InvariantViolation as e:
        return {
            "error": e.code,
            "message": e.message,
        }


def register(mcp: FastMCP) -> None:
    """Register the decide tool."""

    @mcp.tool(
        name="decide",
        description=get_tool_description("decide"),
    )
    @mcp_error_boundary
    async def decide(
        decision: str,
        about: list[str] | str,
        confidence: float = 0.8,
        reasoning: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        """Declare a decision or commitment directly.

        Use this when you have made a decision that should be recorded.
        For tentative beliefs during reasoning, use hypothesize + commit instead.

        Args:
            decision: The decision or commitment being made.
            about: REQUIRED. Node IDs this decision references/concerns.
            confidence: 0.0-1.0 (default 0.8).
            reasoning: Optional rationale for the decision.
            supersedes: Node ID this decision replaces. Creates version chain.

        Returns:
            {commitment_id, created_at, confidence, supersedes?, chain_id?}
        """
        start = time.perf_counter()
        success = True
        about_list = coerce_list(about)
        try:
            return await _decide_impl(decision, about_list, confidence, reasoning, supersedes)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("decide", (time.perf_counter() - start) * 1000, success=success)

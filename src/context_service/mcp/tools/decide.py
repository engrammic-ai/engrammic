# src/context_service/mcp/tools/decide.py
"""MCP tool: decide - Declare a decision/commitment directly."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation
from context_service.sage.transactions import commit as tx_commit
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_belief_confidence, record_mcp_tool


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

    silo_id = str(derive_silo_id(auth.org_id))
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

        response: dict[str, Any] = {
            "commitment_id": str(result.commitment_id),
            "created_at": result.created_at.isoformat(),
            "confidence": result.confidence,
        }
        if supersedes:
            response["supersedes"] = supersedes
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
            {commitment_id, created_at, confidence, supersedes?}
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

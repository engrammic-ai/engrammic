# src/context_service/mcp/tools/commit.py
"""MCP tool: commit - Crystallize hypotheses to commitments."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation, crystallize
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_belief_confidence, record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("commit")
async def _commit_impl(
    belief_ids: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    """Implementation for commit tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "commit")
    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()

    committed: list[str] = []
    confidences: list[float] = []
    errors: list[dict[str, Any]] = []
    all_events: list[Any] = []

    for belief_id in belief_ids:
        try:
            result, events = await crystallize(
                store=ctx_svc.graph_store,
                hypothesis_id=belief_id,
                silo_id=silo_id,
                agent_id=auth.agent_id,
                session_id=auth.session_id,
            )
            committed.append(str(result.commitment_id))
            confidences.append(result.confidence)
            all_events.extend(events)
        except InvariantViolation as e:
            errors.append({
                "belief_id": belief_id,
                "error": e.code,
                "message": e.message,
            })

    for event in all_events:
        await emit_reaction(event)

    for confidence in confidences:
        record_belief_confidence(float(confidence), silo_id=silo_id)

    response: dict[str, Any] = {
        "committed": committed,
        "confidences": confidences,
    }
    if errors:
        response["errors"] = errors

    return response


def register(mcp: FastMCP) -> None:
    """Register the commit tool."""

    @mcp.tool(
        name="commit",
        description=get_tool_description("commit"),
    )
    @mcp_error_boundary
    async def commit(
        belief_ids: list[str] | str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Promote tentative hypotheses to permanent commitments.

        Args:
            belief_ids: Hypotheses to commit.
            reason: Why committing now.

        Returns:
            {committed: [...], superseded: [...]}
        """
        start = time.perf_counter()
        success = True
        belief_ids_list = coerce_list(belief_ids)
        try:
            return await _commit_impl(belief_ids_list, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("commit", (time.perf_counter() - start) * 1000, success=success)

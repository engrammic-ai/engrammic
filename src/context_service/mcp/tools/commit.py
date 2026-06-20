# src/context_service/mcp/tools/commit.py
"""MCP tool: commit - Crystallize hypotheses to commitments.

DEPRECATED (CITE v2): The hypothesize/commit flow is killed with Intelligence
writes in CITE v2. This tool is kept for backward compatibility only. Use
learn() for claims; SAGE handles synthesis automatically.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation, crystallize
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_belief_confidence, record_mcp_tool

logger = structlog.get_logger()

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("commit")
async def _commit_impl(
    belief_ids: list[str],
    _reason: str | None = None,
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

    agent_id = auth.agent_id or auth.org_id

    from context_service.db import queries as q
    from context_service.mcp.tools.context_store import embed

    for belief_id in belief_ids:
        try:
            hypothesis_content: str | None = None
            try:
                hypothesis_rows = await ctx_svc.graph_store.execute_query(
                    q.GET_HYPOTHESIS_BY_ID,
                    {"hypothesis_id": belief_id, "silo_id": silo_id},
                )
                hypothesis_content = hypothesis_rows[0].get("content") if hypothesis_rows else None
            except Exception:
                pass  # Content lookup failed; skip sync embedding

            result, events = await crystallize(
                store=ctx_svc.graph_store,
                hypothesis_id=belief_id,
                silo_id=silo_id,
                agent_id=agent_id,
                session_id=auth.session_id,
            )
            committed.append(str(result.commitment_id))
            confidences.append(result.confidence)
            all_events.extend(events)

            if hypothesis_content:
                try:
                    vector = await embed(hypothesis_content)
                    await ctx_svc.vector_store.upsert(
                        node_id=str(result.commitment_id),
                        vector=vector,
                        payload={"type": "Commitment", "layer": "wisdom"},
                        silo_id=silo_id,
                    )
                except Exception:
                    logger.warning(
                        "sync_embed_failed", node_id=str(result.commitment_id), exc_info=True
                    )
        except InvariantViolation as e:
            errors.append(
                {
                    "belief_id": belief_id,
                    "error": e.code,
                    "message": e.message,
                }
            )

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
            {committed: [...], confidences: [...]} and optionally {errors: [...]}
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

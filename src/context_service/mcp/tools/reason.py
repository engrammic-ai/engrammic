# src/context_service/mcp/tools/reason.py
"""MCP tool: reason - Create ephemeral reasoning chain."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.context_store import _context_reason
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("reason")
async def _reason_impl(
    steps: list[dict[str, Any]],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
    crystallizations: list[dict[str, Any]] | None = None,
    parent_chain_id: str | None = None,
) -> dict[str, Any]:
    """Implementation for reason tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "reason")
    return await _context_reason(
        silo_id=None,  # auto-derived from auth
        steps=steps,
        conclusion=conclusion,
        evidence_used=evidence_used,
        crystallizations=crystallizations,
        session_id=auth.session_id,
        parent_chain_id=parent_chain_id,
    )


def register(mcp: FastMCP) -> None:
    """Register the reason tool."""

    @mcp.tool(
        name="reason",
        description=get_tool_description("reason"),
    )
    @mcp_error_boundary
    async def reason(
        steps: list[dict[str, Any]],
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
        crystallizations: list[dict[str, Any]] | None = None,
        parent_chain_id: str | None = None,
    ) -> dict[str, Any]:
        """Create ephemeral reasoning chain for multi-step inference.

        Args:
            steps: List of reasoning steps. Each step has:
                - step: int (1-indexed step number)
                - reasoning: str (the reasoning text)
                - confidence: float (0.0-1.0, optional)
            conclusion: Final conclusion from the reasoning chain.
            evidence_used: Node IDs of knowledge used as evidence.
            crystallizations: Optional beliefs to commit. Each has:
                - claim: str or {subject, predicate, object}
                - confidence: float (0.0-1.0)
            parent_chain_id: Chain ID this reasoning continues from.

        Returns:
            {chain_id, layer, steps_count, crystallized_claim_ids, session_id}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _reason_impl(
                steps=steps,
                conclusion=conclusion,
                evidence_used=evidence_used,
                crystallizations=crystallizations,
                parent_chain_id=parent_chain_id,
            )
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("reason", (time.perf_counter() - start) * 1000, success=success)

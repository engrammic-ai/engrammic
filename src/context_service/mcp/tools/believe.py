# src/context_service/mcp/tools/believe.py
"""MCP tool: believe - Declare a commitment."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.context_store import _context_commit
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_belief_confidence, record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("believe")
async def _believe_impl(
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Implementation for believe tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "believe")
    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    result = await _context_commit(
        silo_id=None,  # auto-derived from auth
        belief=belief,
        about=about,
        confidence=confidence,
        reasoning=reasoning,
        supersedes=supersedes,
    )
    if "error" not in result:
        record_belief_confidence(confidence, silo_id=None)
    return result


def register(mcp: FastMCP) -> None:
    """Register the believe tool."""

    @mcp.tool(
        name="believe",
        description=get_tool_description("believe"),
    )
    @mcp_error_boundary
    async def believe(
        belief: str,
        about: list[str],
        confidence: float = 0.8,
        reasoning: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        """Declare a belief as a commitment.

        Args:
            belief: What you believe.
            about: REQUIRED. Node IDs this belief concerns.
            confidence: 0.0-1.0 (default 0.8).
            reasoning: Why you believe this.
            supersedes: Node ID this belief replaces. Use recall first to find existing beliefs.

        Returns:
            {node_id, created_at, supersedes?}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _believe_impl(belief, about, confidence, reasoning, supersedes)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("believe", (time.perf_counter() - start) * 1000, success=success)

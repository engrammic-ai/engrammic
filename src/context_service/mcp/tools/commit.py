# src/context_service/mcp/tools/commit.py
"""MCP tool: commit - Crystallize hypotheses to commitments."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.context_crystallize import _context_crystallize
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _commit_impl(
    belief_ids: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    """Implementation for commit tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "commit")
    silo_id = str(derive_silo_id(auth.org_id))
    return await _context_crystallize(
        silo_id=silo_id,
        belief_ids=belief_ids,
        reason=reason,
    )


def register(mcp: FastMCP) -> None:
    """Register the commit tool."""

    @mcp.tool(
        name="commit",
        description=get_tool_description("commit"),
    )
    @mcp_error_boundary
    async def commit(
        belief_ids: list[str],
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
        try:
            return await _commit_impl(belief_ids, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("commit", (time.perf_counter() - start) * 1000, success=success)

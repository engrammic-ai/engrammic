# src/context_service/mcp/tools/revise.py
"""MCP tool: revise - Update a tentative belief."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_mcp_auth_context
from context_service.mcp.tools.context_update_belief import _context_update_belief
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _revise_impl(
    belief_id: str,
    confidence: float,
    content: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Implementation for revise tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    return await _context_update_belief(
        silo_id=silo_id,
        belief_id=belief_id,
        confidence=confidence,
        content=content,
        reason=reason,
    )


def register(mcp: FastMCP) -> None:
    """Register the revise tool."""

    @mcp.tool(
        name="revise",
        description=get_tool_description("revise"),
    )
    async def revise(
        belief_id: str,
        confidence: float,
        reason: str,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Update a tentative hypothesis.

        Args:
            belief_id: Hypothesis to update.
            confidence: New confidence 0.0-1.0.
            reason: REQUIRED. Why revising.
            content: New content (optional).

        Returns:
            {updated_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _revise_impl(belief_id, confidence, content, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("revise", (time.perf_counter() - start) * 1000, success=success)

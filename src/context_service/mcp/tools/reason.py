# src/context_service/mcp/tools/reason.py
"""MCP tool: reason - Record a reasoning chain."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_store import _context_reason
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _reason_impl(
    steps: list[dict[str, Any]],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for reason tool."""
    return await _context_reason(
        silo_id=None,
        steps=steps,
        conclusion=conclusion,
        evidence_used=evidence_used,
    )


def register(mcp: FastMCP) -> None:
    """Register the reason tool."""

    @mcp.tool(
        name="reason",
        description=get_tool_description("reason"),
    )
    async def reason(
        steps: list[dict[str, Any]],
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record explicit reasoning steps.

        Args:
            steps: List of {step, reasoning, confidence?}.
            conclusion: Final conclusion.
            evidence_used: Node IDs referenced.

        Returns:
            {chain_id, session_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _reason_impl(steps, conclusion, evidence_used)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("reason", (time.perf_counter() - start) * 1000, success=success)

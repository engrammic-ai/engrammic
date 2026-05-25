# src/context_service/mcp/tools/reflect.py
"""MCP tool: reflect - Record a meta-observation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.coerce import coerce_list
from context_service.mcp.tools.context_store import _context_reflect
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("reflect")
async def _reflect_impl(
    observation: str,
    type: str,
    about: list[str],
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Implementation for reflect tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "reflect")
    return await _context_reflect(
        silo_id=None,
        observation=observation,
        observation_type=type,
        about=about,
        confidence=confidence,
    )


def register(mcp: FastMCP) -> None:
    """Register the reflect tool."""

    @mcp.tool(
        name="reflect",
        description=get_tool_description("reflect"),
    )
    @mcp_error_boundary
    async def reflect(
        observation: str,
        type: str,
        about: list[str] | str,
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        """Record a meta-observation about your knowledge.

        Args:
            observation: What you noticed.
            type: Type: pattern|contradiction|uncertainty|drift.
            about: REQUIRED. Node IDs this concerns.
            confidence: 0.0-1.0 (default 0.8).

        Returns:
            {node_id, created_at}
        """
        start = time.perf_counter()
        success = True
        about_list = coerce_list(about)
        try:
            return await _reflect_impl(observation, type, about_list, confidence)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("reflect", (time.perf_counter() - start) * 1000, success=success)

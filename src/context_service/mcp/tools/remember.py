# src/context_service/mcp/tools/remember.py
"""MCP tool: remember - Store an observation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.context_store import _context_remember
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import (
    record_mcp_tool,
    record_node_confidence,
    record_supersession_used,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("remember")
async def _remember_impl(
    content: str,
    tags: list[str] | None = None,
    decay: str = "standard",
    supersedes: str | None = None,
    memory_type: str | None = None,
    about: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for remember tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "remember")
    silo_id = str(derive_silo_id(auth.org_id))
    result = await _context_remember(
        silo_id=None,  # auto-derived from auth
        content=content,
        tags=tags,
        decay_class=decay,
        supersedes=supersedes,
        memory_type=memory_type,
        about=about,
    )
    if "error" not in result:
        record_node_confidence(1.0, layer="memory", silo_id=silo_id)
        if supersedes:
            record_supersession_used("remember", silo_id=silo_id)
    return result


def register(mcp: FastMCP) -> None:
    """Register the remember tool."""

    @mcp.tool(
        name="remember",
        description=get_tool_description("remember"),
    )
    @mcp_error_boundary
    async def remember(
        content: str,
        tags: list[str] | None = None,
        decay: str = "standard",
        supersedes: str | None = None,
        memory_type: str | None = None,
        about: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store an observation.

        Args:
            content: What to remember.
            tags: Optional categorization tags.
            decay: How long to keep: ephemeral|standard|durable|permanent.
            supersedes: Node ID this observation replaces. Use recall first to find existing nodes.
            memory_type: Type of memory: observation|reflection|event|document.
                Use "reflection" for metacognitive observations (these don't decay).
            about: Node IDs this memory is about. Creates ABOUT edges.
                Required when memory_type="reflection".

        Returns:
            {node_id, created_at, supersedes?}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _remember_impl(content, tags, decay, supersedes, memory_type, about)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("remember", (time.perf_counter() - start) * 1000, success=success)

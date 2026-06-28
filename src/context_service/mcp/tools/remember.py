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
    summary: str | None = None,
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
        summary=summary,
    )
    if "error" not in result:
        record_node_confidence(1.0, layer="memory", silo_id=silo_id)
        if supersedes:
            record_supersession_used("remember", silo_id=silo_id)
        # Track write for stuck detection
        import asyncio

        asyncio.create_task(
            _track_write_and_resolve_stuck(silo_id, auth.session_id, "remember", result.get("node_id"))
        )
    return result


async def _track_write_and_resolve_stuck(
    silo_id: str, session_id: str | None, action: str, node_id: str | None
) -> None:
    """Track write in session state and resolve any stuck indicator."""
    import structlog

    from context_service.mcp.server import get_context_service, get_redis

    log = structlog.get_logger(__name__)
    if not session_id:
        return

    try:
        redis = get_redis()
        if redis is None:
            return

        from context_service.engine.session_state import get_or_create_session, save_session

        session = await get_or_create_session(redis._redis, session_id, silo_id)
        session.record_write()
        await save_session(redis._redis, session, silo_id)

        # Resolve any active stuck indicator
        from context_service.engine.intelligence import (
            get_active_stuck_indicator,
            resolve_stuck_indicator,
        )

        ctx = get_context_service()
        stuck = await get_active_stuck_indicator(ctx._memgraph, silo_id, session_id)
        if stuck:
            await resolve_stuck_indicator(ctx._memgraph, stuck["id"], silo_id, action, node_id)
    except Exception as e:
        log.debug("write_tracking_failed", error=str(e))


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
        summary: str | None = None,
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
            summary: Key fact for semantic search (max 128 chars). Recommended for
                content longer than 200 chars. Embedded instead of full content for
                improved recall precision.

        Returns:
            {node_id, created_at, supersedes?}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _remember_impl(content, tags, decay, supersedes, memory_type, about, summary)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("remember", (time.perf_counter() - start) * 1000, success=success)

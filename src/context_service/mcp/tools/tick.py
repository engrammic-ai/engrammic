"""MCP tool: tick - Lightweight engagement check without full recall."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _tick(
    about_hint: list[str] | None,
    silo_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.engine.engagement import (
        get_engagement_for_about_set,
        get_engagement_for_silo,
    )
    from context_service.mcp.server import get_context_service, get_redis

    ctx = get_context_service()
    store = ctx.graph_store
    redis_client = get_redis()
    if redis_client is None:
        return {
            "error": "service_unavailable",
            "message": "Redis is not configured",
        }
    redis = redis_client._redis

    if about_hint:
        engagement = await get_engagement_for_about_set(
            redis=redis,
            store=store,
            silo_id=silo_id,
            about_ids=about_hint,
            session_id=session_id,
        )
    else:
        # No hint: surface all pending markers and ProposedBeliefs for the silo
        engagement = await get_engagement_for_silo(
            redis=redis,
            store=store,
            silo_id=silo_id,
        )

    return {"engagement": engagement}


def register(mcp: FastMCP) -> None:
    """Register the tick tool."""

    @mcp.tool(
        name="tick",
        description=get_tool_description("tick"),
    )
    @mcp_error_boundary
    async def tick(
        about_hint: list[str] | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Check for pending engagement markers without a full recall operation.

        Safe to call frequently; reads the precomputed marker index only and
        has zero side effects. Returns the same engagement shape as recall.

        Args:
            about_hint: Optional list of node IDs to scope the check. When
                provided, only markers touching those nodes are returned.
                When omitted, all pending silo-level markers are returned.
            silo_id: UUID of the silo. Optional; defaults to the org's primary
                silo derived from auth.

        Returns:
            {"engagement": {"mode": "soft", "markers": [...]} | null}
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "tick")
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            result = await _tick(
                about_hint=about_hint,
                silo_id=resolved_silo_id,
                session_id=auth.session_id,
            )
            if "error" in result:
                success = False
            return result
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "tick",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

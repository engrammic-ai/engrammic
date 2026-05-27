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
    recent_context: str | None = None,  # noqa: ARG001 - reserved for embedding search (future)
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.engine.engagement import (
        get_engagement_for_about_set,
        get_engagement_for_silo,
        run_parallel_checks,
    )
    from context_service.engine.nudges import (
        Nudge,
        NudgeType,
        format_nudge,
        prioritize_nudges,
    )
    from context_service.engine.session_state import (
        get_or_create_session,
        increment_turn,
        save_session,
    )
    from context_service.mcp.server import get_context_service, get_redis

    start_time = time.perf_counter()

    ctx = get_context_service()
    store = ctx.graph_store
    redis_client = get_redis()
    if redis_client is None:
        return {
            "status": "error",
            "error": "service_unavailable",
            "message": "Redis is not configured",
        }
    redis = redis_client._redis

    # Get or create session and increment turn counter
    session = await get_or_create_session(redis, session_id, silo_id)
    session = await increment_turn(redis, session, silo_id)

    # Define parallel checks
    async def check_markers() -> dict[str, Any] | None:
        if about_hint:
            return await get_engagement_for_about_set(
                redis=redis,
                store=store,
                silo_id=silo_id,
                about_ids=about_hint,
                session_id=session.session_id,
            )
        return await get_engagement_for_silo(
            redis=redis,
            store=store,
            silo_id=silo_id,
        )

    async def check_storage_gap() -> dict[str, Any]:
        gap = session.turn_count - session.last_store_turn
        return {"storage_gap": gap if gap > 10 else 0}

    checks: dict[str, Any] = {
        "markers": check_markers(),
        "storage_gap": check_storage_gap(),
    }

    results, completed, skipped = await run_parallel_checks(checks)

    # Build nudges from check results
    nudges: list[Nudge] = []

    engagement_result = results.get("markers")
    markers: list[dict[str, Any]] = []
    if engagement_result is not None:
        markers = engagement_result.get("markers", [])
    if markers and session.should_show_nudge(NudgeType.PENDING_MARKERS):
        nudges.append(format_nudge(NudgeType.PENDING_MARKERS, count=len(markers)))
        session.record_nudge_shown(NudgeType.PENDING_MARKERS)

    gap_result = results.get("storage_gap", {})
    gap = gap_result.get("storage_gap", 0) if isinstance(gap_result, dict) else 0
    if gap > 10 and session.should_show_nudge(NudgeType.STORAGE_GAP):
        nudges.append(format_nudge(NudgeType.STORAGE_GAP, turns=gap))
        session.record_nudge_shown(NudgeType.STORAGE_GAP)

    nudges = prioritize_nudges(nudges)

    # Persist updated session state
    await save_session(redis, session, silo_id)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 1)

    # Determine response status
    if skipped:
        status = "partial"
    elif nudges or markers:
        status = "ok"
    else:
        status = "current"

    return {
        "status": status,
        "session_id": session.session_id,
        # Preserve legacy engagement key for backward compatibility
        "engagement": engagement_result,
        "markers": markers,
        "context": [],
        "nudges": [n.model_dump() for n in nudges],
        "meta": {
            "checks_completed": completed,
            "checks_skipped": skipped,
            "latency_ms": latency_ms,
        },
    }


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
        session_id: str | None = None,
        recent_context: str | None = None,
    ) -> dict[str, Any]:
        """Check for pending engagement markers without a full recall operation.

        Safe to call frequently; reads the precomputed marker index only and
        has near-zero side effects (session state update only). Returns
        engagement markers, contextual nudges, and session state.

        Args:
            about_hint: Optional list of node IDs to scope the check. When
                provided, only markers touching those nodes are returned.
                When omitted, all pending silo-level markers are returned.
            silo_id: UUID of the silo. Optional; defaults to the org's primary
                silo derived from auth.
            session_id: Session ID returned from a previous tick() call. Pass
                this back to maintain session continuity and enable debouncing.
                When omitted, a new session is created and its ID is returned.
            recent_context: Brief description of what the agent is currently
                working on. Used for future context-aware nudge matching.

        Returns:
            Dict with status, session_id, engagement, markers, nudges, and meta.
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

        # Prefer caller-supplied session_id; fall back to auth session
        resolved_session_id = session_id or auth.session_id

        start = time.perf_counter()
        success = True
        try:
            result = await _tick(
                about_hint=about_hint,
                silo_id=resolved_silo_id,
                session_id=resolved_session_id,
                recent_context=recent_context,
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

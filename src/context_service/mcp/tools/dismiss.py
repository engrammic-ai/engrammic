"""MCP tool: dismiss - Dismiss a Contradiction/StaleCommitment marker or reject a ProposedBelief."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _dismiss_marker(
    marker_id: str,
    reason: str,
    silo_id: str,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.engine.markers import dismiss_marker, get_marker_details
    from context_service.mcp.server import get_context_service, get_redis

    ctx = get_context_service()
    store = ctx.graph_store

    # Check if this is a ProposedBelief first (no Redis required for rejection)
    proposal_check = await store.execute_query(
        "MATCH (pb:ProposedBelief {id: $id, silo_id: $silo_id}) RETURN pb.status AS status",
        {"id": marker_id, "silo_id": silo_id},
    )

    if proposal_check:
        pb_status = proposal_check[0].get("status")
        if pb_status != "pending":
            return {
                "error": "invalid_status",
                "message": f"ProposedBelief has status {pb_status!r}, expected 'pending'",
            }

        now = datetime.now(UTC)
        reject_result = await store.execute_write(
            q.REJECT_PROPOSED_BELIEF,
            {
                "proposed_belief_id": marker_id,
                "silo_id": silo_id,
                "rejected_at": now.isoformat(),
                "reason": reason,
            },
        )

        if not reject_result:
            return {
                "error": "reject_failed",
                "message": "Failed to reject ProposedBelief",
            }

        return {
            "proposal_id": marker_id,
            "status": "rejected",
            "reason": reason,
            "rejected_at": now.isoformat(),
        }

    # Not a ProposedBelief - handle as regular marker
    redis_client = get_redis()
    if redis_client is None:
        return {
            "error": "service_unavailable",
            "message": "Redis is not configured",
        }
    redis = redis_client._redis

    # Fetch marker to validate it exists and check type/status
    details = await get_marker_details(store, silo_id, [marker_id])
    if not details:
        return {
            "error": "not_found",
            "message": f"Marker {marker_id!r} not found",
        }

    marker = details[0]
    status = marker.get("status")

    # Only pending markers can be dismissed
    if status != "pending":
        return {
            "error": "invalid_status",
            "message": f"Marker {marker_id!r} has status {status!r}, expected 'pending'",
        }

    result = await dismiss_marker(
        store=store,
        redis=redis,
        silo_id=silo_id,
        marker_id=marker_id,
        reason=reason,
    )

    # Clear touch counter so the agent can recall normally again.
    # Fire-and-forget: non-fatal if Redis is unavailable.
    import contextlib

    from context_service.engine.touch_counter import clear_touches

    with contextlib.suppress(Exception):
        await clear_touches(redis, silo_id, marker_id)

    return {
        "marker_id": result["marker_id"],
        "status": "dismissed",
        "reason": result.get("resolution"),
        "resolved_at": result.get("resolved_at"),
    }


def register(mcp: FastMCP) -> None:
    """Register the dismiss tool."""

    @mcp.tool(
        name="dismiss",
        description=get_tool_description("dismiss"),
    )
    @mcp_error_boundary
    async def dismiss(
        marker_id: str,
        reason: str,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Dismiss a Contradiction or StaleCommitment marker, or reject a ProposedBelief.

        Use this to acknowledge a marker that does not require action (e.g., false
        positive, already handled externally, or intentionally accepted contradiction).
        When given a ProposedBelief ID, rejects the proposal instead of dismissing.

        Args:
            marker_id: ID of the marker or ProposedBelief to dismiss/reject.
            reason: Reason for dismissal or rejection (stored for audit trail).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            For markers: {marker_id, status, reason, resolved_at}
            For ProposedBeliefs: {proposal_id, status, reason, rejected_at}
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "dismiss")
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            result = await _dismiss_marker(
                marker_id=marker_id,
                reason=reason,
                silo_id=resolved_silo_id,
            )
            if "error" in result:
                success = False
            return result
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "dismiss",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

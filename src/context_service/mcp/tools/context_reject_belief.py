"""MCP tool: context_reject_belief - Reject a ProposedBelief with optional reason."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_reject_belief(
    proposed_belief_id: str,
    silo_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    store = get_context_service().graph_store
    rejected_at = datetime.now(UTC).isoformat()

    rows = await store.execute_write(
        q.REJECT_PROPOSED_BELIEF,
        {
            "proposed_belief_id": proposed_belief_id,
            "silo_id": silo_id,
            "reason": reason,
            "rejected_at": rejected_at,
        },
    )

    if not rows:
        return {
            "error": "not_found",
            "message": f"ProposedBelief {proposed_belief_id!r} not found or not pending",
        }

    return {
        "proposed_belief_id": proposed_belief_id,
        "status": "rejected",
        "reason": reason,
        "rejected_at": rejected_at,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_reject_belief tool."""

    @mcp.tool(
        name="reject",
        description=get_tool_description("reject"),
    )
    async def reject(
        belief_id: str,
        reason: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Reject a ProposedBelief.

        Args:
            belief_id: ID of the ProposedBelief to reject.
            reason: Optional reason for rejection (stored for audit trail).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {proposed_belief_id, status: "rejected", reason, rejected_at}
        """
        from context_service.mcp.server import get_mcp_auth_context, get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        start = time.perf_counter()
        success = True
        try:
            result = await _context_reject_belief(
                proposed_belief_id=belief_id,
                silo_id=resolved_silo_id,
                reason=reason,
            )
            if "error" in result:
                success = False
            return result
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "reject",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

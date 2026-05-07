"""MCP tool: context_update_belief - In-place mutation of a WorkingBelief."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.errors import error_response, success_response
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_update_belief(
    belief_id: str,
    confidence: float,
    reason: str,
    silo_id: str,
    content: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    if not 0.0 <= confidence <= 1.0:
        return error_response(
            "VALIDATION_ERROR",
            "confidence must be between 0.0 and 1.0",
            details={"field": "confidence"},
        )

    store = get_context_service().graph_store
    updated_at = datetime.now(UTC).isoformat()

    rows = await store.execute_write(
        q.UPDATE_WORKING_BELIEF,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "confidence": confidence,
            "content": content,
            "updated_at": updated_at,
        },
    )

    if not rows:
        return error_response(
            "NOT_FOUND",
            f"WorkingBelief {belief_id!r} not found in silo",
            details={"belief_id": belief_id},
        )

    return success_response({
        "belief_id": belief_id,
        "confidence": confidence,
        "content": content,
        "updated_at": updated_at,
        "reason": reason,
    })


def register(mcp: FastMCP) -> None:
    """Register the context_update_belief tool."""

    @mcp.tool(
        name="context_update_belief",
        description=(
            "Mutate a WorkingBelief in-place: update confidence and optionally revise content. "
            "Use this to reflect changed certainty mid-session without superseding a Commitment."
        ),
    )
    async def context_update_belief(
        belief_id: str,
        confidence: float,
        reason: str,
        content: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Update a WorkingBelief's confidence and optionally its content.

        Args:
            belief_id: ID of the WorkingBelief to update.
            confidence: New confidence score (0.0-1.0). Guidelines:
                0.95+ = near certain, verified from multiple sources
                0.8-0.95 = confident, single reliable source or strong reasoning
                0.6-0.8 = probable, reasonable inference with some uncertainty
                0.4-0.6 = uncertain, plausible but unverified
                <0.4 = speculative, weak evidence or tentative hypothesis
            reason: Human-readable reason for the update (audit trail only, not persisted).
            content: If provided, replaces the belief's content text.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {belief_id, confidence, content, updated_at, reason}
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_update_belief(
            belief_id=belief_id,
            confidence=confidence,
            reason=reason,
            silo_id=resolved_silo_id,
            content=content,
        )

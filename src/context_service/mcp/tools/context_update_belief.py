"""MCP tool: context_update_belief - In-place mutation of a WorkingHypothesis."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

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
        return {"error": "invalid_confidence", "message": "confidence must be between 0.0 and 1.0"}

    store = get_context_service().graph_store
    updated_at = datetime.now(UTC).isoformat()

    rows = await store.execute_write(
        q.UPDATE_WORKING_HYPOTHESIS,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "confidence": confidence,
            "content": content,
            "updated_at": updated_at,
        },
    )

    if not rows:
        return {
            "error": "not_found",
            "message": f"WorkingHypothesis {belief_id!r} not found in silo",
        }

    return {
        "belief_id": belief_id,
        "confidence": confidence,
        "content": content,
        "updated_at": updated_at,
        "reason": reason,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_update_belief tool."""

    @mcp.tool(
        name="context_update_belief",
        description=(
            "Mutate a WorkingHypothesis in-place: update confidence and optionally revise content. "
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
        """Update a WorkingHypothesis's confidence and optionally its content.

        Args:
            belief_id: ID of the WorkingHypothesis to update.
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
            result = await _context_update_belief(
                belief_id=belief_id,
                confidence=confidence,
                reason=reason,
                silo_id=resolved_silo_id,
                content=content,
            )
            return result
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("context_update_belief", (time.perf_counter() - start) * 1000, success=success)

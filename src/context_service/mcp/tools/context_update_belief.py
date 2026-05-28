"""MCP tool: context_update_belief - In-place mutation of a WorkingHypothesis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


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

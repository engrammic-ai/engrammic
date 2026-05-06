"""MCP tool: context_crystallize - Promote WorkingBeliefs to durable Commitments."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _crystallize_one(
    store: Any,
    belief_id: str,
    silo_id: str,
    reason: str,
    created_at: str,
) -> str | None:
    """Crystallize a single WorkingBelief; returns commitment_id or None on miss."""
    from context_service.db import queries as q

    commitment_id = str(uuid.uuid4())
    rows = await store.execute_write(
        q.CRYSTALLIZE_TO_COMMITMENT,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "commitment_id": commitment_id,
            "reason": reason,
            "created_at": created_at,
            "valid_from": created_at,
        },
    )
    if not rows:
        return None
    return commitment_id


async def _context_crystallize(
    belief_ids: list[str],
    silo_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.mcp.server import get_context_service

    if not belief_ids:
        return {"error": "missing_belief_ids", "message": "belief_ids must be non-empty"}

    store = get_context_service().graph_store
    now = datetime.now(UTC).isoformat()
    effective_reason = reason or "crystallized"

    results = await asyncio.gather(
        *[
            _crystallize_one(store, bid, silo_id, effective_reason, now)
            for bid in belief_ids
        ]
    )

    commitment_ids = [r for r in results if r is not None]
    superseded = [bid for bid, r in zip(belief_ids, results, strict=True) if r is not None]
    not_found = [bid for bid, r in zip(belief_ids, results, strict=True) if r is None]

    response: dict[str, Any] = {
        "commitment_ids": commitment_ids,
        "superseded": superseded,
    }
    if not_found:
        response["not_found"] = not_found
    return response


def register(mcp: FastMCP) -> None:
    """Register the context_crystallize tool."""

    @mcp.tool(
        name="context_crystallize",
        description=(
            "Promote one or more WorkingBeliefs to durable Commitments. "
            "Each crystallized belief creates a Commitment node with SUPERSEDES edges "
            "to any prior active Commitments about the same nodes."
        ),
    )
    async def context_crystallize(
        belief_ids: list[str],
        reason: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Crystallize WorkingBeliefs into Commitments.

        Args:
            belief_ids: List of WorkingBelief IDs to promote.
            reason: Optional reason stored on SUPERSEDES edges.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {commitment_ids: list[str], superseded: list[str], not_found?: list[str]}
            where superseded lists the belief_ids that were successfully promoted
            and not_found lists any IDs that did not match a WorkingBelief in the silo.
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_crystallize(
            belief_ids=belief_ids,
            silo_id=resolved_silo_id,
            reason=reason,
        )

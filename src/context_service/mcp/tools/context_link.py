"""MCP tool: context_link - Create relationships between nodes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.config.settings import get_settings
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_redis,
    get_silo_service,
)
from context_service.models.mcp import RelationshipType
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_link(
    silo_id: str,
    from_node: str,
    to_node: str,
    relationship: str,
    weight: float = 1.0,
    note: str | None = None,
) -> dict[str, Any]:
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    try:
        rel_type = RelationshipType(relationship)
    except ValueError:
        return {
            "error": "invalid_relationship",
            "valid": [e.value for e in RelationshipType],
        }

    if not 0.0 <= weight <= 10.0:
        return {"error": "invalid_weight", "message": "weight must be between 0.0 and 10.0"}

    edge_id = await ctx_svc.link(
        silo_id=str(expected_silo_id),
        from_node=from_node,
        to_node=to_node,
        relationship=rel_type.value,
        weight=weight,
        note=note,
    )

    return {
        "edge_id": edge_id,
        "from_node": from_node,
        "to_node": to_node,
        "relationship": rel_type.value,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_link tool."""

    @mcp.tool(
        name="context_link",
        description=(
            "Create a typed relationship between two context nodes. "
            "Relationship types: REFERENCES, SUPPORTS, CONTRADICTS, DERIVED_FROM, RELATED_TO, "
            "CAUSES, CORROBORATES, PREVENTS, SUPERSEDES. "
            "SUPERSEDES also closes the old node (sets valid_to and superseded_by)."
        ),
    )
    async def context_link(
        from_node: str,
        to_node: str,
        relationship: str,
        weight: float = 1.0,
        note: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a relationship between nodes.

        Args:
            from_node: Source node ID. For SUPERSEDES, this is the new/replacement node.
            to_node: Target node ID. For SUPERSEDES, this is the old node being superseded.
            relationship: REFERENCES|SUPPORTS|CONTRADICTS|DERIVED_FROM|RELATED_TO|CAUSES|CORROBORATES|PREVENTS|SUPERSEDES.
            weight: Edge weight 0.0-10.0 (default 1.0).
            note: Optional annotation on the edge.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {edge_id, from_node, to_node, relationship, created_at}
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        result = await _context_link(
            silo_id=resolved_silo_id,
            from_node=from_node,
            to_node=to_node,
            relationship=relationship,
            weight=weight,
            note=note,
        )

        if "error" not in result and get_settings().write_events_enabled:
            redis = get_redis()
            if redis is not None:
                await emit_access_event(redis, resolved_silo_id, to_node, event_type="write")

        return result

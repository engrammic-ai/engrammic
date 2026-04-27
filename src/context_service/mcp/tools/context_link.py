"""MCP tool: context_link - Create relationships between nodes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.auth import get_mcp_auth
from context_service.mcp.server import get_context_service
from context_service.models.mcp import RelationshipType
from context_service.services.models import derive_silo_id

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
    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

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
            "Relationship types: REFERENCES, SUPPORTS, CONTRADICTS, DERIVED_FROM, RELATED_TO."
        ),
    )
    async def context_link(
        silo_id: str,
        from_node: str,
        to_node: str,
        relationship: str,
        weight: float = 1.0,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create a relationship between nodes.

        Args:
            silo_id: UUID of the silo.
            from_node: Source node ID.
            to_node: Target node ID.
            relationship: REFERENCES|SUPPORTS|CONTRADICTS|DERIVED_FROM|RELATED_TO.
            weight: Edge weight 0.0-10.0 (default 1.0).
            note: Optional annotation on the edge.

        Returns:
            {edge_id, from_node, to_node, relationship, created_at}
        """
        return await _context_link(
            silo_id=silo_id,
            from_node=from_node,
            to_node=to_node,
            relationship=relationship,
            weight=weight,
            note=note,
        )

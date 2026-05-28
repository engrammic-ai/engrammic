"""MCP tool: context_link - Create relationships between nodes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_silo_service,
)
from context_service.models.mcp import RelationshipType
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership


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

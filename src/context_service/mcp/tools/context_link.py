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
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import (
    BrainError,
    CrossSiloViolation,
    CycleError,
    LinkType,
)
from context_service.sage.transactions import (
    link as brain_link,
)
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership

# Maps public RelationshipType values to internal LinkType values.
# CORROBORATES has no distinct LinkType; it maps to SUPPORTS.
_REL_TO_LINK_TYPE: dict[str, LinkType] = {
    RelationshipType.RELATED_TO: LinkType.RELATED_TO,
    RelationshipType.CONTRADICTS: LinkType.CONTRADICTS,
    RelationshipType.SUPPORTS: LinkType.SUPPORTS,
    RelationshipType.CORROBORATES: LinkType.SUPPORTS,
    RelationshipType.REFERENCES: LinkType.REFERENCES,
    RelationshipType.DERIVED_FROM: LinkType.DERIVED_FROM,
    RelationshipType.CAUSES: LinkType.CAUSES,
    RelationshipType.PREVENTS: LinkType.PREVENTS,
    RelationshipType.SUPERSEDES: LinkType.SUPERSEDES,
}


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
    agent_id = auth.agent_id or auth.org_id

    try:
        rel_type = RelationshipType(relationship)
    except ValueError:
        return {
            "error": "invalid_relationship",
            "valid": [e.value for e in RelationshipType],
        }

    link_type = _REL_TO_LINK_TYPE[rel_type]

    if not 0.0 <= weight <= 10.0:
        return {"error": "invalid_weight", "message": "weight must be between 0.0 and 10.0"}

    metadata = {"note": note} if note else None

    try:
        result, events = await brain_link(
            store=ctx_svc.graph_store,
            source_id=from_node,
            target_id=to_node,
            edge_type=link_type,
            silo_id=str(expected_silo_id),
            agent_id=agent_id,
            weight=weight,
            metadata=metadata,
        )
    except CrossSiloViolation as exc:
        return {"error": "cross_silo_violation", "message": exc.message}
    except CycleError as exc:
        return {"error": "cycle_detected", "message": exc.message}
    except BrainError as exc:
        if exc.code == "DUPLICATE_EDGE":
            return {"error": "duplicate_edge", "message": exc.message}
        return {"error": exc.code, "message": exc.message}

    for event in events:
        await emit_reaction(event)

    return {
        "edge_id": str(result.edge_id),
        "from_node": from_node,
        "to_node": to_node,
        "relationship": rel_type.value,
        "created_at": datetime.now(UTC).isoformat(),
    }

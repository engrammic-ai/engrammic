"""MCP tools: conflicts, dismiss_conflict, escalate_conflict, resolve_conflict."""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_mcp_identity_context,
    track_tool_usage,
)
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@dataclass
class Conflict:
    id: str
    node_a_id: str
    node_a_content: str
    agent_a: str
    node_b_id: str
    node_b_content: str
    agent_b: str
    detected_at: str
    detected_by: str
    resolution_status: str


_LIST_CONFLICTS_QUERY = """
MATCH (a)-[r:CONTRADICTS]->(b)
WHERE a.silo_id = $silo_id AND b.silo_id = $silo_id
  AND r.resolution_status = $status
RETURN
    r.id AS id,
    a.id AS node_a_id,
    COALESCE(a.content, a.text, '') AS node_a_content,
    COALESCE(a.agent_id, '') AS agent_a,
    b.id AS node_b_id,
    COALESCE(b.content, b.text, '') AS node_b_content,
    COALESCE(b.agent_id, '') AS agent_b,
    r.detected_at AS detected_at,
    r.detected_by AS detected_by,
    r.resolution_status AS resolution_status
ORDER BY r.detected_at DESC
LIMIT $limit
"""

_LIST_CONFLICTS_BY_AGENT_QUERY = """
MATCH (a)-[r:CONTRADICTS]->(b)
WHERE a.silo_id = $silo_id AND b.silo_id = $silo_id
  AND r.resolution_status = $status
  AND (a.agent_id = $agent_id OR b.agent_id = $agent_id)
RETURN
    r.id AS id,
    a.id AS node_a_id,
    COALESCE(a.content, a.text, '') AS node_a_content,
    COALESCE(a.agent_id, '') AS agent_a,
    b.id AS node_b_id,
    COALESCE(b.content, b.text, '') AS node_b_content,
    COALESCE(b.agent_id, '') AS agent_b,
    r.detected_at AS detected_at,
    r.detected_by AS detected_by,
    r.resolution_status AS resolution_status
ORDER BY r.detected_at DESC
LIMIT $limit
"""

_GET_CONFLICT_QUERY = """
MATCH (a)-[r:CONTRADICTS {id: $conflict_id}]->(b)
WHERE a.silo_id = $silo_id AND b.silo_id = $silo_id
RETURN r.resolution_status AS resolution_status
"""

_UPDATE_CONFLICT_STATUS_QUERY = """
MATCH ()-[r:CONTRADICTS {id: $conflict_id}]->()
SET r.resolution_status = $resolution_status,
    r.resolved_by = $resolved_by,
    r.resolved_at = $resolved_at
RETURN r.id AS id
"""


async def _get_conflicts(
    silo_id: str,
    agent_id: str | None,
    status: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Query CONTRADICTS edges from the graph store."""
    ctx_svc = get_context_service()
    store = ctx_svc.graph_store

    params: dict[str, Any] = {
        "silo_id": silo_id,
        "status": status,
        "limit": limit,
    }

    if agent_id is not None:
        params["agent_id"] = agent_id
        query = _LIST_CONFLICTS_BY_AGENT_QUERY
    else:
        query = _LIST_CONFLICTS_QUERY

    rows = await store.execute_query(query, params)

    conflicts = []
    for row in rows:
        detected_at = row.get("detected_at") or ""
        if hasattr(detected_at, "isoformat"):
            detected_at = detected_at.isoformat()
        c = Conflict(
            id=row["id"],
            node_a_id=row["node_a_id"],
            node_a_content=row["node_a_content"],
            agent_a=row["agent_a"],
            node_b_id=row["node_b_id"],
            node_b_content=row["node_b_content"],
            agent_b=row["agent_b"],
            detected_at=detected_at,
            detected_by=row.get("detected_by") or "",
            resolution_status=row["resolution_status"],
        )
        conflicts.append(dataclasses.asdict(c))
    return conflicts


async def _update_conflict_status(
    conflict_id: str,
    silo_id: str,
    resolution_status: str,
    resolved_by: str,
) -> bool:
    """Update resolution_status on a CONTRADICTS edge."""
    ctx_svc = get_context_service()
    store = ctx_svc.graph_store

    # Verify edge exists and belongs to this silo
    check = await store.execute_query(
        _GET_CONFLICT_QUERY,
        {"conflict_id": conflict_id, "silo_id": silo_id},
    )
    if not check:
        return False

    resolved_at = datetime.now(UTC).isoformat()
    result = await store.execute_write(
        _UPDATE_CONFLICT_STATUS_QUERY,
        {
            "conflict_id": conflict_id,
            "resolution_status": resolution_status,
            "resolved_by": resolved_by,
            "resolved_at": resolved_at,
        },
    )
    return bool(result)


def register(mcp: FastMCP) -> None:
    """Register conflict management tools."""

    @mcp.tool(
        name="conflicts",
        description=get_tool_description("conflicts"),
    )
    @mcp_error_boundary
    async def conflicts(
        silo_id: str | None = None,
        agent_id: str | None = None,
        status: str = "unresolved",
        topic: str | None = None,  # noqa: ARG001 - reserved for future
        limit: int = 50,
    ) -> dict[str, Any]:
        """List conflicts between agents.

        Args:
            silo_id: UUID of the silo. Optional; defaults to org's primary silo.
            agent_id: Filter to conflicts involving a specific agent.
            status: Filter by resolution_status (default: "unresolved").
            topic: Reserved for future semantic topic filter.
            limit: Maximum number of conflicts to return (default: 50).

        Returns:
            Dict with conflicts list and count.
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "conflicts")

        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err

        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            conflict_list = await _get_conflicts(
                silo_id=resolved_silo_id,
                agent_id=agent_id,
                status=status,
                limit=limit,
            )
            return {"conflicts": conflict_list, "count": len(conflict_list)}
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "conflicts",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

    @mcp.tool(
        name="dismiss_conflict",
        description=get_tool_description("dismiss_conflict"),
    )
    @mcp_error_boundary
    async def dismiss_conflict(
        conflict_id: str,
        reason: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark a conflict as not-a-real-conflict.

        Args:
            conflict_id: ID of the CONTRADICTS edge to dismiss.
            reason: Optional explanation stored for audit trail.
            silo_id: UUID of the silo. Optional; defaults to org's primary silo.

        Returns:
            Dict with conflict_id and updated status, or error.
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "dismiss_conflict")
        identity = await get_mcp_identity_context()

        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err

        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            ok = await _update_conflict_status(
                conflict_id=conflict_id,
                silo_id=resolved_silo_id,
                resolution_status="dismissed",
                resolved_by=identity.agent_id,
            )
            if not ok:
                return {"error": "not_found", "conflict_id": conflict_id}
            return {
                "conflict_id": conflict_id,
                "status": "dismissed",
                "reason": reason,
            }
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "dismiss_conflict",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

    @mcp.tool(
        name="escalate_conflict",
        description=get_tool_description("escalate_conflict"),
    )
    @mcp_error_boundary
    async def escalate_conflict(
        conflict_id: str,
        message: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Flag a conflict for human review.

        Args:
            conflict_id: ID of the CONTRADICTS edge to escalate.
            message: Optional context for the human reviewer.
            silo_id: UUID of the silo. Optional; defaults to org's primary silo.

        Returns:
            Dict with conflict_id and updated status, or error.
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "escalate_conflict")
        identity = await get_mcp_identity_context()

        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err

        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            ok = await _update_conflict_status(
                conflict_id=conflict_id,
                silo_id=resolved_silo_id,
                resolution_status="escalated",
                resolved_by=identity.agent_id,
            )
            if not ok:
                return {"error": "not_found", "conflict_id": conflict_id}
            return {
                "conflict_id": conflict_id,
                "status": "escalated",
                "message": message,
            }
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "escalate_conflict",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

    @mcp.tool(
        name="resolve_conflict",
        description=get_tool_description("resolve_conflict"),
    )
    @mcp_error_boundary
    async def resolve_conflict(
        conflict_id: str,
        winner_id: str,
        supersede: bool = True,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Pick a winner for a conflict, optionally superseding the loser.

        Args:
            conflict_id: ID of the CONTRADICTS edge to resolve.
            winner_id: Node ID of the winning (authoritative) node.
            supersede: If True, the loser node is marked superseded by winner.
                       Sets resolution_status="superseded". If False, sets
                       resolution_status="resolved" without supersession.
            silo_id: UUID of the silo. Optional; defaults to org's primary silo.

        Returns:
            Dict with conflict_id, status, and winner_id, or error.
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "resolve_conflict")
        identity = await get_mcp_identity_context()

        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err

        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            resolution_status = "superseded" if supersede else "resolved"
            ok = await _update_conflict_status(
                conflict_id=conflict_id,
                silo_id=resolved_silo_id,
                resolution_status=resolution_status,
                resolved_by=identity.agent_id,
            )
            if not ok:
                return {"error": "not_found", "conflict_id": conflict_id}
            return {
                "conflict_id": conflict_id,
                "status": resolution_status,
                "winner_id": winner_id,
            }
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "resolve_conflict",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

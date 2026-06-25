"""MCP tool: agents - List agents in a silo."""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from context_service.db.postgres import get_session
from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@dataclass
class AgentSummary:
    agent_id: str
    role: str | None
    first_seen: str | None
    last_seen: str | None
    node_count: int
    trust_score: float


_AGENTS_QUERY = """
SELECT
    a.id,
    a.role,
    a.first_seen,
    a.last_seen,
    a.trust_score,
    COALESCE(n.node_count, 0) AS node_count
FROM agents a
LEFT JOIN (
    SELECT agent_id, COUNT(*) AS node_count
    FROM nodes
    WHERE silo_id = CAST(:silo_id_uuid AS uuid)
    GROUP BY agent_id
) n ON n.agent_id = a.id
WHERE a.silo_id = :silo_id
ORDER BY a.last_seen DESC
"""


async def _agents(silo_id: str) -> list[dict[str, Any]]:
    """Query agents table and join node counts for a silo."""
    from sqlalchemy import text

    async with get_session() as session:
        result = await session.execute(
            text(_AGENTS_QUERY), {"silo_id": silo_id, "silo_id_uuid": silo_id}
        )
        rows = result.mappings().all()

    summaries = [
        AgentSummary(
            agent_id=row["id"],
            role=row["role"],
            first_seen=row["first_seen"].isoformat() if row["first_seen"] else None,
            last_seen=row["last_seen"].isoformat() if row["last_seen"] else None,
            node_count=row["node_count"],
            trust_score=row["trust_score"] if row["trust_score"] is not None else 0.5,
        )
        for row in rows
    ]
    return [dataclasses.asdict(s) for s in summaries]


def register(mcp: FastMCP) -> None:
    """Register the agents tool."""

    @mcp.tool(
        name="agents",
        description=get_tool_description("agents"),
    )
    @mcp_error_boundary
    async def agents(
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """List agents registered in the silo.

        Args:
            silo_id: UUID of the silo. Optional; defaults to the org's primary
                silo derived from auth.

        Returns:
            Dict with agents list, each containing agent_id, role, first_seen,
            last_seen, node_count, and trust_score.
        """
        from context_service.mcp.server import get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "agents")

        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err

        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))

        start = time.perf_counter()
        success = True
        try:
            agent_list = await _agents(resolved_silo_id)
            return {"agents": agent_list, "count": len(agent_list)}
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "agents",
                (time.perf_counter() - start) * 1000,
                success=success,
                silo_id=resolved_silo_id,
            )

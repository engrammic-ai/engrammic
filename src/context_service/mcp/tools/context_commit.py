"""MCP tool: context_commit - Commit belief to Wisdom layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.auth import get_mcp_auth
from context_service.mcp.server import get_context_service
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_commit(
    silo_id: str,
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    if not about:
        return {"error": "missing_about", "message": "about must reference at least one node"}

    agent_id = getattr(auth, "agent_id", None) or auth.org_id

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.commit_belief(
        scope=scope,
        belief=belief,
        about=about,
        confidence=confidence,
        reasoning=reasoning,
        metadata=metadata,
        tags=tags,
        agent_id=agent_id,
    )

    return {
        "node_id": str(node.id),
        "layer": "wisdom",
        "declared_by": agent_id,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_commit tool."""

    @mcp.tool(
        name="context_commit",
        description=(
            "Commit a belief or stance to the Wisdom layer. "
            "Commitments are agent-scoped via DECLARED_BY edge. "
            "Use for: synthesized judgments, declared positions, team patterns."
        ),
    )
    async def context_commit(
        silo_id: str,
        belief: str,
        about: list[str],
        confidence: float = 0.8,
        reasoning: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Commit a belief.

        Args:
            silo_id: UUID of the silo.
            belief: The belief statement.
            about: Node IDs this belief concerns.
            confidence: 0.0-1.0.
            reasoning: Why agent holds this belief.
            metadata: Optional metadata.
            tags: Optional tags.

        Returns:
            {node_id, layer, declared_by, about_nodes, created_at}
        """
        return await _context_commit(
            silo_id=silo_id,
            belief=belief,
            about=about,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata,
            tags=tags,
        )

"""MCP tool: context_commit - Commit belief to Wisdom layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.mcp.server import get_context_service, get_mcp_auth_context, get_silo_service
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = structlog.get_logger(__name__)


async def _context_commit(
    silo_id: str,
    belief: str,
    about: list[str],
    confidence: float = 0.8,
    reasoning: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    chain_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

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

    result: dict[str, Any] = {
        "node_id": str(node.id),
        "layer": "wisdom",
        "declared_by": agent_id,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }

    # Compact the source reasoning chain (if provided) now that it has been committed.
    if chain_id is not None:
        try:
            from context_service.engine.compaction import compact_reasoning_chain

            event_id = await compact_reasoning_chain(
                ctx_svc.graph_store,
                chain_id=chain_id,
                silo_id=str(expected_silo_id),
                outcome="committed",
            )
            result["compacted_chain_id"] = chain_id
            result["compaction_event_id"] = event_id
        except ValueError as exc:
            # Chain not found or already compacted — not a fatal error.
            logger.warning(
                "context_commit_compaction_skip",
                chain_id=chain_id,
                reason=str(exc),
            )

    return result


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

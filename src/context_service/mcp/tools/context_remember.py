"""MCP tool: context_remember - Store to Memory layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.auth import get_mcp_auth
from context_service.mcp.server import get_context_service
from context_service.models.mcp import DecayClass
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_remember(
    silo_id: str,
    content: str,
    content_type: str = "text",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: str = "standard",
    observed_from: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    auth = get_mcp_auth()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {
            "error": "silo_not_found",
            "silo_id": silo_id,
            "message": "Silo does not exist or org_id mismatch.",
        }

    try:
        decay = DecayClass(decay_class)
    except ValueError:
        return {
            "error": "invalid_decay_class",
            "message": f"decay_class must be one of: {[e.value for e in DecayClass]}",
        }

    ctx_svc = get_context_service()
    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.remember(
        scope=scope,
        content=content,
        content_type=content_type,
        metadata=metadata,
        tags=tags,
        decay_class=decay,
        observed_from=observed_from,
        agent_id=getattr(auth, "agent_id", None),
    )

    return {
        "node_id": str(node.id),
        "layer": "memory",
        "decay_class": decay_class,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_remember tool."""

    @mcp.tool(
        name="context_remember",
        description=(
            "Store an experience or observation to the Memory layer. "
            "Memories decay over time based on decay_class. "
            "Use for: events, utterances, observations, raw experiences."
        ),
    )
    async def context_remember(
        silo_id: str,
        content: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        decay_class: str = "standard",
        observed_from: str | None = None,
    ) -> dict[str, Any]:
        """Store to Memory layer.

        Args:
            silo_id: UUID of the silo.
            content: The content to store.
            content_type: One of text, utterance, event.
            metadata: Optional metadata dict.
            tags: Optional tags for filtering.
            decay_class: ephemeral|standard|durable|permanent.
            observed_from: Attribution (user:<id>, agent:<id>).

        Returns:
            {node_id, layer, decay_class, created_at}
        """
        return await _context_remember(
            silo_id=silo_id,
            content=content,
            content_type=content_type,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
            observed_from=observed_from,
        )

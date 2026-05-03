"""MCP tool: context_remember - Store to Memory layer."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.api.metrics import CONTEXT_STORE_LATENCY
from context_service.mcp.server import get_context_service, get_mcp_auth_context, get_silo_service
from context_service.models.mcp import DecayClass
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership

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
    auth = await get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    # derive_silo_id is deterministic and validate_silo_ownership already
    # confirmed silo_id == derive_silo_id(org_id), so use silo_id directly.
    validated_silo_id = derive_silo_id(auth.org_id)

    try:
        decay = DecayClass(decay_class)
    except ValueError:
        return {
            "error": "invalid_decay_class",
            "message": f"decay_class must be one of: {[e.value for e in DecayClass]}",
        }

    ctx_svc = get_context_service()
    scope = ScopeContext(org_id=auth.org_id, silo_id=validated_silo_id)
    _start = time.perf_counter()
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
    CONTEXT_STORE_LATENCY.labels(tool="context_remember").observe(time.perf_counter() - _start)

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
        content: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        decay_class: str = "standard",
        observed_from: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Store to Memory layer.

        Args:
            content: The content to store.
            content_type: One of text, utterance, event.
            metadata: Optional metadata dict.
            tags: Optional tags for filtering.
            decay_class: ephemeral|standard|durable|permanent.
            observed_from: Attribution (user:<id>, agent:<id>).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {node_id, layer, decay_class, created_at}
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_remember(
            silo_id=resolved_silo_id,
            content=content,
            content_type=content_type,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
            observed_from=observed_from,
        )

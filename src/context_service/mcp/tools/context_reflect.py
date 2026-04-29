"""MCP tool: context_reflect - Store meta-observation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_context_service, get_mcp_auth_context, get_silo_service
from context_service.models.mcp import ObservationType
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_reflect(
    silo_id: str,
    observation: str,
    observation_type: str,
    about: list[str],
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    try:
        obs_type = ObservationType(observation_type)
    except ValueError:
        return {
            "error": "invalid_observation_type",
            "valid": [e.value for e in ObservationType],
        }

    agent_id = getattr(auth, "agent_id", None) or auth.org_id

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.reflect(
        scope=scope,
        observation=observation,
        observation_type=obs_type,
        about=about,
        confidence=confidence,
        metadata=metadata,
        agent_id=agent_id,
    )

    return {
        "node_id": str(node.id),
        "observation_type": observation_type,
        "about_nodes": about,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_reflect tool."""

    @mcp.tool(
        name="context_reflect",
        description=(
            "Store a meta-observation about your own cognition. "
            "Types: belief_change, confidence_shift, contradiction, uncertainty, correction, insight."
        ),
    )
    async def context_reflect(
        silo_id: str,
        observation: str,
        observation_type: str,
        about: list[str],
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a meta-observation.

        Args:
            silo_id: UUID of the silo.
            observation: The meta-observation text.
            observation_type: belief_change|confidence_shift|contradiction|uncertainty|correction|insight.
            about: Node IDs this observation concerns.
            confidence: 0.0-1.0.
            metadata: Optional metadata.

        Returns:
            {node_id, observation_type, about_nodes, created_at}
        """
        return await _context_reflect(
            silo_id=silo_id,
            observation=observation,
            observation_type=observation_type,
            about=about,
            confidence=confidence,
            metadata=metadata,
        )

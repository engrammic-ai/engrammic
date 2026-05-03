"""MCP tool: context_store - Unified write tool for all EAG layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from context_service.mcp.tools.context_assert import _context_assert
from context_service.mcp.tools.context_commit import _context_commit
from context_service.mcp.tools.context_reason import _context_reason
from context_service.mcp.tools.context_reflect import _context_reflect
from context_service.mcp.tools.context_remember import _context_remember
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_store(
    silo_id: str,
    content: str,
    layer: str,
    evidence: list[str] | None = None,
    source_type: str | None = None,
    confidence: float = 0.8,
    about: list[str] | None = None,
    reasoning: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    observation_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    decay_class: str = "standard",
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if layer == "memory":
        result = await _context_remember(
            silo_id=silo_id,
            content=content,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
        )
        return result

    if layer == "knowledge":
        if not evidence:
            return {
                "error": "missing_evidence",
                "message": "evidence required for knowledge layer",
            }
        if not source_type:
            return {
                "error": "missing_source_type",
                "message": "source_type required for knowledge layer",
            }
        result = await _context_assert(
            silo_id=silo_id,
            claim=content,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            metadata=metadata,
            tags=tags,
        )
        if "layer" not in result:
            result["layer"] = "knowledge"
        return result

    if layer == "wisdom":
        if not about:
            return {
                "error": "missing_about",
                "message": "about required for wisdom layer",
            }
        result = await _context_commit(
            silo_id=silo_id,
            belief=content,
            about=about,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata,
            tags=tags,
        )
        if "layer" not in result:
            result["layer"] = "wisdom"
        return result

    if layer == "intelligence":
        if not steps:
            return {
                "error": "missing_steps",
                "message": "steps required for intelligence layer",
            }
        result = await _context_reason(
            silo_id=silo_id,
            steps=steps,
            conclusion=content,
            evidence_used=evidence,
        )
        if "layer" not in result:
            result["layer"] = "intelligence"
        return result

    if layer == "meta":
        if not observation_type:
            return {
                "error": "missing_observation_type",
                "message": "observation_type required for meta layer",
            }
        if not about:
            return {
                "error": "missing_about",
                "message": "about required for meta layer",
            }
        result = await _context_reflect(
            silo_id=silo_id,
            observation=content,
            observation_type=observation_type,
            about=about,
            confidence=confidence,
            metadata=metadata,
        )
        if "layer" not in result:
            result["layer"] = "meta"
        return result

    return {
        "error": "invalid_layer",
        "valid": ["memory", "knowledge", "wisdom", "intelligence", "meta"],
    }


def register(mcp: FastMCP) -> None:
    """Register the context_store tool."""

    @mcp.tool(
        name="context_store",
        description=(
            "Unified write tool for all EAG layers. "
            "Routes to memory, knowledge, wisdom, intelligence, or meta based on layer. "
            "knowledge requires evidence + source_type. "
            "wisdom requires about. "
            "intelligence requires steps. "
            "meta requires observation_type + about."
        ),
    )
    async def context_store(
        content: str,
        layer: Literal["memory", "knowledge", "wisdom", "intelligence", "meta"],
        evidence: list[str] | None = None,
        source_type: str | None = None,
        confidence: float = 0.8,
        about: list[str] | None = None,
        reasoning: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        observation_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        decay_class: str = "standard",
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Store to any EAG layer.

        Args:
            content: The content to store. For intelligence layer, this is the conclusion.
            layer: Target layer: memory|knowledge|wisdom|intelligence|meta.
            evidence: Evidence refs (node:<uuid> or URI). Required for knowledge layer.
            source_type: Source type for knowledge layer: document|user|external|agent.
            confidence: 0.0-1.0, agent's confidence (default 0.8).
            about: Node IDs this content concerns. Required for wisdom and meta layers.
            reasoning: Reasoning behind a wisdom-layer belief.
            steps: Reasoning steps for intelligence layer. List of {step, reasoning, confidence?}.
            observation_type: Meta-observation type. Required for meta layer.
            metadata: Optional metadata dict.
            tags: Optional tags for filtering.
            decay_class: ephemeral|standard|durable|permanent (memory layer only).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            Layer-specific response dict with at minimum {node_id, layer, created_at}.
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_store(
            silo_id=resolved_silo_id,
            content=content,
            layer=layer,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            about=about,
            reasoning=reasoning,
            steps=steps,
            observation_type=observation_type,
            metadata=metadata,
            tags=tags,
            decay_class=decay_class,
        )

"""MCP tool: context_assert - Assert claim to Knowledge layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.auth import get_mcp_auth
from context_service.mcp.server import get_context_service, get_evidence_validator
from context_service.models.mcp import SourceType, SPOClaim
from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_assert(
    silo_id: str,
    claim: str | dict[str, Any],
    evidence: str | list[str],
    source_type: str,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    evidence_mode: str = "sync",
) -> dict[str, Any]:
    """Internal implementation."""
    auth = get_mcp_auth()
    ctx_svc = get_context_service()
    ev_validator = get_evidence_validator()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    try:
        src_type = SourceType(source_type)
    except ValueError:
        return {
            "error": "invalid_source_type",
            "message": f"Must be one of: {[e.value for e in SourceType]}",
        }

    if not 0.0 <= confidence <= 1.0:
        return {"error": "invalid_confidence", "message": "confidence must be between 0.0 and 1.0"}

    claim_type = "freeform"
    parsed_claim: str | SPOClaim
    if isinstance(claim, dict):
        try:
            parsed_claim = SPOClaim(**claim)
            claim_type = "structured"
        except Exception as e:
            return {"error": "invalid_claim", "message": str(e)}
    else:
        parsed_claim = claim

    evidence_list = [evidence] if isinstance(evidence, str) else list(evidence)

    evidence_nodes: list[str] = []
    if evidence_mode == "sync":
        for ev_ref in evidence_list:
            result = await ev_validator.validate(ev_ref, str(expected_silo_id))
            if result.status != "valid":
                return {
                    "error": "invalid_evidence",
                    "evidence": ev_ref,
                    "reason": result.reason,
                }
            if result.node_id:
                evidence_nodes.append(result.node_id)

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    node = await ctx_svc.assert_claim(
        scope=scope,
        claim=parsed_claim,
        evidence=evidence_list,
        source_type=src_type,
        confidence=confidence,
        metadata=metadata,
        tags=tags,
        agent_id=getattr(auth, "agent_id", None),
    )

    return {
        "node_id": str(node.id),
        "layer": "knowledge",
        "claim_type": claim_type,
        "evidence_status": "verified" if evidence_mode == "sync" else "pending",
        "evidence_nodes": evidence_nodes,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_assert tool."""

    @mcp.tool(
        name="context_assert",
        description=(
            "Assert a claim to the Knowledge layer. Requires evidence. "
            "Evidence must be node:<uuid> refs or URIs. "
            "Claims persist until contradicted (no decay)."
        ),
    )
    async def context_assert(
        silo_id: str,
        claim: str | dict[str, Any],
        evidence: str | list[str],
        source_type: str,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        evidence_mode: str = "sync",
    ) -> dict[str, Any]:
        """Assert a claim with evidence.

        Args:
            silo_id: UUID of the silo.
            claim: Free text or {subject, predicate, object} SPO.
            evidence: node:<uuid> or URI, or list thereof. Required.
            source_type: document|user|external|agent.
            confidence: 0.0-1.0, agent's confidence.
            metadata: Optional metadata.
            tags: Optional tags.
            evidence_mode: sync (validate first) or async (validate later).

        Returns:
            {node_id, layer, claim_type, evidence_status, evidence_nodes, created_at}
        """
        return await _context_assert(
            silo_id=silo_id,
            claim=claim,
            evidence=evidence,
            source_type=source_type,
            confidence=confidence,
            metadata=metadata,
            tags=tags,
            evidence_mode=evidence_mode,
        )

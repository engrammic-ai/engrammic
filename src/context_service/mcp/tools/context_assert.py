"""MCP tool: context_assert - Assert claim to Knowledge layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.mcp.server import (
    get_context_service,
    get_evidence_validator,
    get_mcp_auth_context,
    get_silo_service,
)
from context_service.models.mcp import SourceType, SPOClaim
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership

logger = structlog.get_logger(__name__)

# Minimum evidence count for R1 single-source promotion.
# R1 requires raw_confidence >= 0.7 + authoritative source_tier — but the
# evidence_count gate ensures we don't call the epistemology on zero-evidence claims.
_R1_THRESHOLD = 1

if TYPE_CHECKING:
    from fastmcp import FastMCP


_VALID_SOURCE_TIERS = ("authoritative", "validated", "community", "unknown")


async def _context_assert(
    silo_id: str,
    claim: str | dict[str, Any],
    evidence: str | list[str],
    source_type: str,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    evidence_mode: str = "sync",
    source_tier: str | None = None,
) -> dict[str, Any]:
    """Internal implementation."""
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()
    ev_validator = get_evidence_validator()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    try:
        src_type = SourceType(source_type)
    except ValueError:
        return {
            "error": "invalid_source_type",
            "message": f"Must be one of: {[e.value for e in SourceType]}",
        }

    if source_tier is not None and source_tier not in _VALID_SOURCE_TIERS:
        return {
            "error": "invalid_source_tier",
            "message": f"Must be one of: {list(_VALID_SOURCE_TIERS)}",
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
        source_tier=source_tier,
    )

    promoted = False
    if len(evidence_list) >= _R1_THRESHOLD:
        try:
            promotion_result = await ctx_svc.promote_claim_to_fact(
                silo_id=str(expected_silo_id),
                claim_id=str(node.id),
                evidence_count=len(evidence_list),
            )
            if promotion_result is not None:
                promoted = True
        except Exception:
            logger.warning(
                "claim_assert_promotion_failed",
                exc_info=True,
                claim_id=str(node.id),
            )

    return {
        "node_id": str(node.id),
        "layer": "knowledge",
        "claim_type": claim_type,
        "evidence_status": "verified" if evidence_mode == "sync" else "pending",
        "evidence_nodes": evidence_nodes,
        "promoted_to_fact": promoted,
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
        source_tier: str | None = None,
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
            source_tier: Source credibility tier — one of authoritative,
                validated, community, unknown. Persisted on the claim and
                consumed by Claim->Fact promotion. Defaults to unknown if
                omitted (which fails R1 single-source promotion).

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
            source_tier=source_tier,
        )

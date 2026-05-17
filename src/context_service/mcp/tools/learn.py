# src/context_service/mcp/tools/learn.py
"""MCP tool: learn - Assert a claim with evidence."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog
from primitives.eag.transitions import MissingEvidenceError, validate_evidence_non_empty

from context_service.config.settings import get_settings
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.context_store import _context_assert
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

log = structlog.get_logger(__name__)


async def _learn_impl(
    claim: str,
    evidence: list[str],
    source: str,
    confidence: float = 0.8,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for learn tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "learn")
    settings = get_settings()
    cfg = settings.evidence_enforcement

    if cfg.enabled and not validate_evidence_non_empty(evidence):
        log.warning(
            "evidence_violation",
            claim_preview=claim[:100] if claim else "",
            evidence_count=len(evidence) if evidence else 0,
            enforce_mode=cfg.enforce,
        )
        if cfg.enforce:
            raise MissingEvidenceError()
        return {
            "error": "missing_evidence",
            "message": "evidence must reference at least one node or URI",
        }

    return await _context_assert(
        silo_id=None,  # auto-derived from auth
        claim=claim,
        evidence=evidence,
        source_type=source,
        confidence=confidence,
        tags=tags,
    )


def register(mcp: FastMCP) -> None:
    """Register the learn tool."""

    @mcp.tool(
        name="learn",
        description=get_tool_description("learn"),
    )
    async def learn(
        claim: str,
        evidence: list[str],
        source: str,
        confidence: float = 0.8,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record something you learned with evidence.

        Args:
            claim: What you learned.
            evidence: REQUIRED. References: node:<uuid> or URI.
            source: Source type: document|user|external|agent.
            confidence: 0.0-1.0 (default 0.8).
            tags: Optional categorization.

        Returns:
            {node_id, evidence_status, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _learn_impl(claim, evidence, source, confidence, tags)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("learn", (time.perf_counter() - start) * 1000, success=success)

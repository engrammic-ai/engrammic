# src/context_service/mcp/tools/update.py
"""MCP tool: update - Explicit supersession with built-in semantic search."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_mcp_identity_context,
    track_tool_usage,
)
from context_service.mcp.tools.context_store import (
    _context_assert,
    embed,
    validate_supersession_target,
)
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool, record_supersession_used

if TYPE_CHECKING:
    from fastmcp import FastMCP

log = structlog.get_logger(__name__)

_SIMILARITY_THRESHOLD = 0.7
_MAX_CANDIDATES = 3
_CONTENT_SNIPPET_LEN = 200


async def _search_candidates(
    query: str,
    silo_id: str,
    limit: int = _MAX_CANDIDATES,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Search for similar nodes via vector similarity.

    Returns a list of candidate dicts with id, content, similarity, created_at.
    Only includes results above the threshold, ordered by similarity descending.
    """
    ctx_svc = get_context_service()
    vector = await embed(query)

    search_results = await ctx_svc.vector_store.search(
        vector=vector,
        limit=limit,
        score_threshold=threshold,
        silo_id=silo_id,
    )

    if not search_results:
        return []

    # Fetch node content from graph for snippet display
    from context_service.engine import queries as q

    candidates: list[dict[str, Any]] = []
    for sr in search_results:
        if sr.score < threshold:
            continue
        try:
            rows = await ctx_svc.graph_store.execute_query(
                q.GET_NODE_RETRIEVAL,
                {"id": sr.node_id, "silo_id": silo_id},
            )
        except Exception:
            log.warning("update_node_fetch_failed", node_id=sr.node_id)
            continue

        if not rows:
            continue

        node_labels: list[str] = rows[0].get("_labels", [])
        if "Claim" not in node_labels:
            log.debug("update_search_skipped_non_claim", node_id=sr.node_id, labels=node_labels)
            continue

        node_data = rows[0].get("n", {})
        content = node_data.get("content", "")
        created_at = node_data.get("created_at", "")
        candidates.append(
            {
                "id": sr.node_id,
                "content": content[:_CONTENT_SNIPPET_LEN],
                "similarity": round(sr.score, 4),
                "created_at": created_at if isinstance(created_at, str) else str(created_at),
            }
        )

    candidates.sort(key=lambda c: c["similarity"], reverse=True)
    return candidates


@rate_limited("update")
async def _update_impl(
    content: str,
    evidence: list[str],
    query: str | None = None,
    target: str | None = None,
    source_tier: str | None = None,
    confidence: float = 0.8,
    # REST overrides (bypass MCP context when provided)
    silo_id: str | None = None,
    _agent_id: str | None = None,  # noqa: ARG001 - reserved for audit
) -> dict[str, Any]:
    """Implementation for update tool."""
    if query is None and target is None:
        return {
            "status": "error",
            "error": "missing_target",
            "message": "must provide query or target",
        }

    # Use explicit params if provided (REST path), otherwise MCP context
    if silo_id is None:
        auth = await get_mcp_auth_context()
        await track_tool_usage(auth, "update")
        identity = await get_mcp_identity_context()
        silo_id = str(derive_silo_id(auth.org_id))
    else:
        identity = None  # REST path - no identity context

    supersedes_id: str

    if target is not None:
        # Direct supersession path: validate target is not already superseded
        err = await validate_supersession_target(silo_id, target)
        if err is not None:
            if err.get("error") == "already_superseded":
                return {
                    "status": "error",
                    "error": "already_superseded",
                    "message": "Cannot update already-superseded node. Use its successor.",
                    "head_id": err.get("head_id"),
                }
            return err

        # Enforce Knowledge-layer only: target must be a Claim
        from context_service.engine import queries as q

        ctx_svc = get_context_service()
        try:
            rows = await ctx_svc.graph_store.execute_query(
                q.GET_NODE_INTERNAL,
                {"id": target, "silo_id": silo_id},
            )
        except Exception:
            log.warning("update_layer_check_failed", target=target)
            rows = []

        if rows:
            node_labels: list[str] = rows[0].get("_labels", [])
            if "Claim" not in node_labels:
                actual = next(
                    (lbl for lbl in node_labels if lbl not in ("KnowledgeNode",)),
                    node_labels[0] if node_labels else "unknown",
                )
                return {
                    "status": "error",
                    "error": "wrong_layer",
                    "message": (
                        f"update is Knowledge-layer only (Claims). "
                        f"Target {target!r} is a {actual!r} node. "
                        "Use the appropriate tool for this layer."
                    ),
                    "actual_label": actual,
                }

        supersedes_id = target
    else:
        # query path: semantic search
        assert query is not None
        candidates = await _search_candidates(query, silo_id)

        if len(candidates) == 0:
            return {
                "status": "not_found",
                "message": "No existing knowledge matches query. Use learn() to create new.",
            }

        if len(candidates) > 1:
            return {
                "status": "ambiguous",
                "candidates": candidates,
            }

        # Exactly 1 match above threshold
        supersedes_id = candidates[0]["id"]

    # Store the new node, superseding the target
    result = await _context_assert(
        silo_id=None,
        claim=content,
        evidence=evidence,
        source_type="agent",
        confidence=confidence,
        source_tier=source_tier,
        supersedes=supersedes_id,
    )

    if "error" in result:
        return result

    record_supersession_used("update", silo_id=silo_id)

    # Log "superseded" event for the old node (only if identity context available)
    if identity is not None:
        from context_service.services.identity_service import fire_and_forget_identity_writes

        fire_and_forget_identity_writes(identity, action="superseded", target_node_id=supersedes_id)

    # Fetch snippet of the superseded node content for the response
    ctx_svc = get_context_service()
    superseded_content: str = ""
    try:
        from context_service.engine import queries as q

        rows = await ctx_svc.graph_store.execute_query(
            q.GET_NODE_INTERNAL,
            {"id": supersedes_id, "silo_id": silo_id},
        )
        if rows:
            node_data = rows[0].get("n", {})
            raw_content = node_data.get("content", "")
            superseded_content = raw_content[:_CONTENT_SNIPPET_LEN]
    except Exception:
        log.warning("update_superseded_content_fetch_failed", supersedes_id=supersedes_id)

    return {
        "status": "updated",
        "node_id": result["node_id"],
        "superseded_id": supersedes_id,
        "superseded_content": superseded_content,
    }


def register(mcp: FastMCP) -> None:
    """Register the update tool."""

    @mcp.tool(
        name="update",
        description=get_tool_description("update"),
    )
    @mcp_error_boundary
    async def update(
        content: str,
        evidence: list[str],
        query: str | None = None,
        target: str | None = None,
        source_tier: str | None = None,
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        """Update existing knowledge by superseding it with new content.

        Provide either query (semantic search for target) or target (explicit node_id).

        Args:
            content: The updated claim content.
            evidence: REQUIRED. References: node:<uuid> or URI.
            query: Semantic search query to find the node to supersede. Returns
                ambiguous if multiple matches found above threshold.
            target: Explicit node_id to supersede. Skips search.
            source_tier: Optional quality tier: authoritative|validated|community|unknown.
            confidence: 0.0-1.0 (default 0.8).

        Returns:
            {status: "updated", node_id, superseded_id, superseded_content} on success.
            {status: "ambiguous", candidates: [...]} if query matches multiple nodes.
            {status: "not_found", message} if query finds no matches.
        """
        start = time.perf_counter()
        success = True
        try:
            return await _update_impl(content, evidence, query, target, source_tier, confidence)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("update", (time.perf_counter() - start) * 1000, success=success)

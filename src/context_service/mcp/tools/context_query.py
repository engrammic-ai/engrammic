"""MCP tool: context_query - Semantic search with layer filtering."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Literal

import structlog

from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_redis,
    get_silo_service,
)
from context_service.models.mcp import Layer, QueryFilters
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event

if TYPE_CHECKING:
    from fastmcp import FastMCP


logger = structlog.get_logger(__name__)

_VALID_SEARCH_MODES = frozenset({"hybrid", "dense", "sparse"})


async def _context_query(
    silo_id: str,
    query: str,
    layers: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    top_k: int = 10,
    include_superseded: bool = False,
    as_of: str | None = None,
    search_mode: Literal["hybrid", "dense", "sparse"] = "hybrid",
) -> dict[str, Any]:
    """Internal implementation for testing."""

    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    valid_layers = None
    if layers:
        try:
            valid_layers = [Layer(layer) for layer in layers]
        except ValueError:
            return {"error": "invalid_layer", "valid": [e.value for e in Layer]}

    if as_of is not None:
        return {
            "error": "as_of_not_supported",
            "message": "Point-in-time retrieval is not yet implemented",
        }
    as_of_dt = None

    parsed_filters = None
    if filters:
        try:
            parsed_filters = QueryFilters(**filters)
        except Exception as exc:
            return {"error": "invalid_filters", "message": str(exc)}

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)

    start = time.perf_counter()
    results = await ctx_svc.query(
        scope=scope,
        query=query,
        layers=valid_layers,
        filters=parsed_filters,
        top_k=top_k,
        include_superseded=include_superseded,
        as_of=as_of_dt,
        search_mode=search_mode,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    redis = get_redis()
    if redis is not None and results:
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(emit_access_event(redis, silo_id, str(r.node_id)) for r in results)
                ),
                timeout=2.0,
            )
        except TimeoutError:
            logger.warning("access_event_emit_timeout", silo_id=silo_id, result_count=len(results))
        except Exception as exc:
            logger.warning("access_event_emit_failed", silo_id=silo_id, error=str(exc))

    return {
        "results": [
            {
                "node_id": str(r.node_id),
                "layer": r.layer,
                "content": r.content,
                "summary": r.summary,
                "confidence": r.confidence,
                "relevance_score": r.relevance_score,
                "tags": r.tags or [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ],
        "total_candidates": len(results),
        "search_time_ms": elapsed_ms,
        "search_mode": search_mode,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_query tool."""

    @mcp.tool(
        name="context_query",
        description=(
            "Semantic search across Memory, Knowledge, and Wisdom layers. "
            "Supports layer filtering, time-travel (as_of), and metadata filters. "
            "Replaces context_lookup with EAG-aware layer semantics."
        ),
    )
    async def context_query(
        silo_id: str,
        query: str,
        layers: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        include_superseded: bool = False,
        as_of: str | None = None,
        search_mode: str = "hybrid",
    ) -> dict[str, Any]:
        """Semantic search with layer filtering.

        Args:
            silo_id: UUID of the silo.
            query: Natural language search query.
            layers: Filter to layers: memory, knowledge, wisdom, intelligence.
            filters: QueryFilters: tags, source_type, min_confidence, created_after, created_before.
            top_k: Maximum results (default 10).
            include_superseded: Include superseded nodes (default False).
            as_of: ISO 8601 datetime for time-travel (not yet implemented at store level).
            search_mode: Retrieval mode — "hybrid" (dense+sparse RRF, default),
                "dense" (dense-only), or "sparse" (SPLADE-only).

        Returns:
            {results, total_candidates, search_time_ms, search_mode}
        """
        # Validate search_mode before passing to the typed internal function.
        if search_mode not in _VALID_SEARCH_MODES:
            return {
                "error": "invalid_search_mode",
                "valid": sorted(_VALID_SEARCH_MODES),
            }
        validated_mode: Literal["hybrid", "dense", "sparse"] = search_mode  # type: ignore[assignment]
        return await _context_query(
            silo_id=silo_id,
            query=query,
            layers=layers,
            filters=filters,
            top_k=top_k,
            include_superseded=include_superseded,
            as_of=as_of,
            search_mode=validated_mode,
        )

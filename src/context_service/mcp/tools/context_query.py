"""MCP tool: context_query - Semantic search with layer filtering."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from context_service.config.settings import get_settings
from context_service.engine.reflection_triggers import compute_reflection_suggested
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
from context_service.telemetry.metrics import record_mcp_tool

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

    as_of_dt: datetime | None = None
    if as_of is not None:
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            as_of_dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            return {
                "error": "invalid_as_of_format",
                "message": "as_of must be an ISO 8601 datetime string (e.g. 2026-04-01T00:00:00Z)",
            }

    parsed_filters = None
    if filters:
        try:
            parsed_filters = QueryFilters(**filters)
        except Exception as exc:
            return {"error": "invalid_filters", "message": str(exc)}

    scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
    silo_service = get_silo_service()

    start = time.perf_counter()

    if as_of_dt is not None:
        is_future = as_of_dt > datetime.now(UTC)
        temporal_results = await ctx_svc.temporal_query(
            silo_id=silo_id,
            as_of=as_of_dt,
            query=query,
            top_k=top_k,
        )
        elapsed_s = time.perf_counter() - start
        record_mcp_tool("context_query", elapsed_s * 1000)
        elapsed_ms = int(elapsed_s * 1000)
        response: dict[str, Any] = {
            "results": temporal_results,
            "total_candidates": len(temporal_results),
            "search_time_ms": elapsed_ms,
            "historical_query": True,
            "as_of": as_of,
        }
        if is_future:
            response["warning"] = "as_of is in the future; returning current state"
        return response

    results = await ctx_svc.query(
        scope=scope,
        query=query,
        layers=valid_layers,
        filters=parsed_filters,
        top_k=top_k,
        include_superseded=include_superseded,
        as_of=None,
        search_mode=search_mode,
    )
    elapsed_s = time.perf_counter() - start
    record_mcp_tool("context_query", elapsed_s * 1000)
    elapsed_ms = int(elapsed_s * 1000)

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

    settings = get_settings()
    metadata: dict[str, Any] = {
        "causal_edges_enabled": settings.causal.query_enabled,
    }
    if settings.causal.query_enabled:
        silo = await silo_service.get_by_id(scope)
        if silo is not None:
            coverage_from = silo.metadata.get("causal_coverage_from")
            if coverage_from is not None:
                metadata["causal_coverage_from"] = coverage_from

    result_dicts = [
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
    ]

    return {
        "results": result_dicts,
        "total_candidates": len(results),
        "search_time_ms": elapsed_ms,
        "search_mode": search_mode,
        "reflection_suggested": compute_reflection_suggested(result_dicts),
        "metadata": metadata,
    }

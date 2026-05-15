"""MCP tool: context_query - Semantic search with layer filtering."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from opentelemetry import trace

from context_service.config.models import load_models_config
from context_service.config.settings import get_settings
from context_service.engine.reflection_triggers import compute_reflection_suggested
from context_service.mcp.server import (
    get_context_service,
    get_mcp_auth_context,
    get_redis,
    get_silo_service,
)
from context_service.models.mcp import Layer, QueryFilters
from context_service.reranking import LiteLLMReranker, QueryExpander, is_hard_query
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event
from context_service.telemetry.metrics import (
    record_hard_query_detection,
    record_mcp_tool,
    record_query_expansion,
    record_reranking,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_VALID_SEARCH_MODES = frozenset({"hybrid", "dense", "sparse"})


async def _apply_reranking(
    query: str,
    results: list[Any],
    settings: Any,
) -> list[Any]:
    """Apply reranking to search results if enabled."""
    if not settings.reranking.enabled or len(results) <= 1:
        return results

    models_config = load_models_config()
    reranker_model = models_config.litellm_reranker_model
    if reranker_model is None:
        return results

    reranker = LiteLLMReranker(
        model=reranker_model,
        timeout_seconds=settings.reranking.reranker_timeout_seconds,
    )
    documents = [r.content or "" for r in results]
    node_ids = [str(r.node_id) for r in results]

    with tracer.start_as_current_span("recall.rerank") as span:
        span.set_attribute("query_length", len(query))
        span.set_attribute("candidates", len(results))
        rerank_start = time.perf_counter()
        try:
            reranked = await reranker.rerank(
                query=query,
                documents=documents,
                node_ids=node_ids,
                top_k=len(results),
            )
            latency_ms = (time.perf_counter() - rerank_start) * 1000
            span.set_attribute("latency_ms", latency_ms)
            record_reranking(latency_ms=latency_ms, success=True)
        except Exception:
            latency_ms = (time.perf_counter() - rerank_start) * 1000
            span.set_attribute("latency_ms", latency_ms)
            record_reranking(latency_ms=latency_ms, success=False)
            raise

    id_to_result = {str(r.node_id): r for r in results}
    return [id_to_result[rr.node_id] for rr in reranked if rr.node_id in id_to_result]


async def _maybe_expand_query(
    query: str,
    settings: Any,
    redis: Any,
) -> tuple[str, bool]:
    """Expand query if it's a hard query and expansion is enabled.

    Returns:
        Tuple of (effective_query, was_expanded)
    """
    if not settings.reranking.expand_hard_queries:
        return query, False

    hard = is_hard_query(query)
    record_hard_query_detection(hard)
    if not hard:
        return query, False

    if redis is None:
        logger.warning("query_expansion_skipped", reason="redis_unavailable")
        return query, False

    models_config = load_models_config()
    expander_model = models_config.litellm_expander_model
    if expander_model is None:
        return query, False

    expander = QueryExpander(
        llm_model=expander_model,
        redis=redis,
        cache_ttl_seconds=settings.reranking.expansion_cache_ttl_days * 86400,
        timeout_seconds=settings.reranking.expander_timeout_seconds,
    )

    with tracer.start_as_current_span("recall.expand_query") as span:
        span.set_attribute("query_length", len(query))
        span.set_attribute("is_hard_query", True)
        expand_start = time.perf_counter()
        try:
            expanded = await expander.expand(query)
            latency_ms = (time.perf_counter() - expand_start) * 1000
            span.set_attribute("latency_ms", latency_ms)
            span.set_attribute("was_expanded", expanded != query)
            record_query_expansion(latency_ms=latency_ms, success=True)
        except Exception:
            latency_ms = (time.perf_counter() - expand_start) * 1000
            span.set_attribute("latency_ms", latency_ms)
            record_query_expansion(latency_ms=latency_ms, success=False)
            raise

    return expanded, expanded != query


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

    settings = get_settings()
    redis = get_redis()

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

    # Query expansion for hard queries
    effective_query, was_expanded = await _maybe_expand_query(query, settings, redis)
    if was_expanded:
        logger.info("query_expanded", original=query, expanded=effective_query)

    results = await ctx_svc.query(
        scope=scope,
        query=effective_query,
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

    results = await _apply_reranking(effective_query, results, settings)

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

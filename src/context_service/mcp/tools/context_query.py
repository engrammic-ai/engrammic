"""MCP tool: context_query - Semantic search with layer filtering."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from opentelemetry import trace

from context_service.cache.result_cache import ResultCacheStore, get_knowledge_version
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
from context_service.reranking import (
    RERANK_SCORE_FLOOR,
    QueryExpander,
    apply_threshold_filter,
    compute_adaptive_threshold,
    compute_retrieval_quality,
    is_hard_query,
)
from context_service.reranking.epistemic_fusion import (
    EpistemicAdjustment,
    apply_epistemic_fusion,
)
from context_service.retrieval.fusion import FusionRetriever
from context_service.services.models import QueryResult, ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event
from context_service.telemetry.metrics import (
    record_adaptive_threshold,
    record_hard_query_detection,
    record_mcp_tool,
    record_query_expansion,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_VALID_SEARCH_MODES = frozenset({"hybrid", "dense", "sparse"})

CACHE_VERSION = "v2"


def _search_mode_to_channels(mode: str) -> dict[str, bool]:
    """Map deprecated search_mode to channel toggles."""
    if mode == "dense":
        logger.warning("search_mode='dense' deprecated, use channel config")
        return {"semantic": True, "bm25": False, "temporal": False, "ppr": False}
    if mode == "sparse":
        logger.warning("search_mode='sparse' deprecated, use channel config")
        return {"semantic": False, "bm25": True, "temporal": False, "ppr": False}
    return {"semantic": True, "bm25": True, "temporal": True, "ppr": True}

_result_cache: ResultCacheStore | None = None


def _get_result_cache() -> ResultCacheStore:
    global _result_cache
    if _result_cache is None:
        _result_cache = ResultCacheStore()
    return _result_cache


def _layer_ttls_for(layers: list[str] | None) -> dict[str, int]:
    """Return TTL values for the queried layers from settings.

    When layers is None (all layers), returns TTLs for all cacheable layers.
    """
    cfg = get_settings().result_cache
    all_ttls = {
        "memory": cfg.memory_ttl,
        "knowledge": cfg.knowledge_ttl,
        "wisdom": cfg.wisdom_ttl,
    }
    if layers is None:
        return all_ttls
    return {layer: all_ttls[layer] for layer in layers if layer in all_ttls}


async def _emit_access_events(redis: Any, silo_id: str, results: list[Any]) -> None:
    """Emit access events for retrieved nodes (used on both cache hit and miss paths)."""
    if redis is None or not results:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    emit_access_event(
                        redis, silo_id, str(r["node_id"]) if isinstance(r, dict) else str(r.node_id)
                    )
                    for r in results
                )
            ),
            timeout=2.0,
        )
    except TimeoutError:
        logger.warning("access_event_emit_timeout", silo_id=silo_id, result_count=len(results))
    except Exception as exc:
        logger.warning("access_event_emit_failed", silo_id=silo_id, error=str(exc))

async def _maybe_expand_query(
    query: str,
    settings: Any,
    redis: Any,
    silo_id: str,
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
        vertex_project=models_config.vertex_project or None,
        vertex_location=models_config.vertex_location or None,
        provider=models_config.expander_provider,
    )

    with tracer.start_as_current_span("recall.expand_query") as span:
        span.set_attribute("query_length", len(query))
        span.set_attribute("is_hard_query", True)
        expand_start = time.perf_counter()
        try:
            expanded = await expander.expand(query, silo_id)
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
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
    min_threshold: float | None = None,
    bypass_threshold: bool = False,
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
    effective_query, was_expanded = await _maybe_expand_query(query, settings, redis, silo_id)
    if was_expanded:
        logger.info("query_expanded", original=query, expanded=effective_query)

    # Fetch knowledge version for cache keying (None falls back to 0)
    knowledge_version: int | None = None
    if redis is not None:
        knowledge_version = await get_knowledge_version(redis, silo_id)
    kv_for_cache = knowledge_version if knowledge_version is not None else 0

    layer_ttls = _layer_ttls_for(layers)

    # Embed cache version into search_mode key to invalidate stale entries
    cache_mode_key = f"{CACHE_VERSION}:{search_mode}"

    # Result cache lookup (skipped when bypass_cache is set)
    if not bypass_cache:
        cached = _get_result_cache().get(
            effective_query,
            layers,
            silo_id,
            kv_for_cache,
            top_k,
            filters,
            include_superseded,
            cache_mode_key,
        )
        if cached is not None:
            cached_results, cached_at_ts = cached
            # Honour max_age_seconds if caller specified a freshness constraint
            if max_age_seconds is not None and (time.time() - cached_at_ts) > max_age_seconds:
                pass  # Treat as a miss; fall through to the query path
            else:
                await _emit_access_events(redis, silo_id, cached_results)
                elapsed_s = time.perf_counter() - start
                record_mcp_tool("context_query", elapsed_s * 1000)
                elapsed_ms = int(elapsed_s * 1000)
                cache_meta: dict[str, Any] = {
                    "embedding_cached": None,
                    "result_cached": True,
                    "cached_at": datetime.fromtimestamp(cached_at_ts, tz=UTC).isoformat(),
                    "layer_ttls": layer_ttls,
                    "knowledge_version": kv_for_cache,
                }
                return {
                    "results": cached_results,
                    "total_candidates": len(cached_results),
                    "search_time_ms": elapsed_ms,
                    "search_mode": search_mode,
                    "reflection_suggested": compute_reflection_suggested(cached_results),
                    "cache_meta": cache_meta,
                }

    channel_config = _search_mode_to_channels(search_mode)
    retriever = FusionRetriever(ctx_svc, channel_config=channel_config)
    layer_strings = [layer.value for layer in valid_layers] if valid_layers else None
    fused_results = await retriever.retrieve(
        query=effective_query,
        scope=scope,
        top_k=top_k,
        layers=layer_strings,
        include_superseded=include_superseded,
        filters=parsed_filters,
        fetch_content=True,
    )

    results = [
        QueryResult(
            node_id=uuid.UUID(f.node_id),
            layer=f.layer or "unknown",
            content=f.content or "",
            confidence=f.confidence or 0.0,
            relevance_score=f.rrf_score,
            conflict_status=f.conflict_status or "none",
            created_at=f.created_at,
            tags=f.tags,
        )
        for f in fused_results
    ]

    elapsed_s = time.perf_counter() - start
    record_mcp_tool("context_query", elapsed_s * 1000)
    elapsed_ms = int(elapsed_s * 1000)

    rerank_fallback = False
    reranked_applied = False

    # Epistemic fusion: scale post-rerank scores by confidence/conflict state
    # so evidence is load-bearing in final ranking (sprint step 1). The
    # pre-fusion score is kept per node: the abstention floor in
    # apply_threshold_filter compares against it when reranking ran.
    epistemic_adjustments: dict[str, EpistemicAdjustment] = {}
    prefusion_scores: dict[str, float | None] = {}
    if settings.epistemic_fusion.enabled:
        prefusion_scores = {str(r.node_id): r.relevance_score for r in results}
        epistemic_adjustments = apply_epistemic_fusion(
            results,
            confidence_weight=settings.epistemic_fusion.confidence_weight,
            conflict_penalty=settings.epistemic_fusion.conflict_penalty,
        )

    await _emit_access_events(redis, silo_id, results)

    metadata: dict[str, Any] = {
        "causal_edges_enabled": settings.causal.query_enabled,
    }
    if settings.causal.query_enabled:
        silo = await silo_service.get_by_id(scope)
        if silo is not None:
            coverage_from = silo.metadata.get("causal_coverage_from")
            if coverage_from is not None:
                metadata["causal_coverage_from"] = coverage_from

    raw_result_dicts = [
        {
            "node_id": str(r.node_id),
            "layer": r.layer,
            "content": r.content,
            "summary": r.summary,
            "confidence": r.confidence,
            "relevance_score": r.relevance_score,
            "tags": r.tags or [],
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "conflict_status": r.conflict_status,
            "credibility": r.credibility,
            "credibility_factors": r.credibility_factors,
            "tier": r.tier,
            "superseded_by": r.superseded_by,
            "rerank_score": (prefusion_scores.get(str(r.node_id)) if reranked_applied else None),
            "epistemic": (
                epistemic_adjustments[str(r.node_id)].to_dict()
                if str(r.node_id) in epistemic_adjustments
                else None
            ),
        }
        for r in results
    ]

    # Per-silo threshold overrides stored in silo metadata under
    # "retrieval_thresholds": {"memory": 0.2, "knowledge": 0.6, ...}
    threshold_overrides: dict[str, float] | None = None
    if settings.causal.query_enabled:
        # Silo may have already been fetched above for causal metadata.
        pass  # We fetch below only when needed.
    silo_for_thresholds = await silo_service.get_by_id(scope)
    if silo_for_thresholds is not None:
        threshold_overrides = silo_for_thresholds.metadata.get("retrieval_thresholds") or None

    # When fusion ran on top of reranking, threshold comparisons should use
    # the pre-fusion rerank score (relevance_score was mutated by fusion).
    score_basis_key = (
        "rerank_score"
        if settings.epistemic_fusion.enabled and reranked_applied
        else "relevance_score"
    )

    # Score-adaptive truncation (SmartSearch-style): tau = alpha * max_score
    effective_min_threshold = min_threshold
    if settings.reranking.adaptive_threshold_enabled and reranked_applied:
        adaptive_tau, max_score = compute_adaptive_threshold(
            raw_result_dicts,
            alpha=settings.reranking.adaptive_alpha,
            score_key=score_basis_key,
        )
        if effective_min_threshold is None or adaptive_tau > effective_min_threshold:
            effective_min_threshold = adaptive_tau

        def _score_above_tau(r: dict[str, Any]) -> bool:
            s = r.get(score_basis_key)
            return isinstance(s, (int, float)) and float(s) >= adaptive_tau

        kept_count = len(list(filter(_score_above_tau, raw_result_dicts)))
        record_adaptive_threshold(
            tau=adaptive_tau,
            max_score=max_score,
            kept=kept_count,
            filtered=len(raw_result_dicts) - kept_count,
            silo_id=silo_id,
        )

    result_dicts, below_threshold = apply_threshold_filter(
        raw_result_dicts,
        threshold_overrides,
        min_threshold=effective_min_threshold,
        bypass=bypass_threshold,
        rerank_floor=RERANK_SCORE_FLOOR if reranked_applied else None,
    )
    retrieval_quality, suggestion = compute_retrieval_quality(
        result_dicts,
        below_threshold,
        fallback_used=rerank_fallback,
        score_key=score_basis_key,
    )

    # Store results in cache (intelligence layer is silently skipped by ResultCacheStore)
    # Skip cache write when bypass_cache=True to comply with spec
    if not bypass_cache:
        _get_result_cache().set(
            effective_query,
            layers,
            silo_id,
            kv_for_cache,
            top_k,
            filters,
            include_superseded,
            cache_mode_key,
            result_dicts,
        )

    cache_meta = {
        "embedding_cached": None,
        "result_cached": False,
        "cached_at": None,
        "layer_ttls": layer_ttls,
        "knowledge_version": kv_for_cache,
    }

    return {
        "results": result_dicts,
        "total_candidates": len(raw_result_dicts),
        "search_time_ms": elapsed_ms,
        "search_mode": search_mode,
        "reflection_suggested": compute_reflection_suggested(result_dicts),
        "retrieval_quality": retrieval_quality,
        "below_threshold": below_threshold,
        "suggestion": suggestion,
        "metadata": metadata,
        "cache_meta": cache_meta,
    }

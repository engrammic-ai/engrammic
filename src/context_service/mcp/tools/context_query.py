"""MCP tool: context_query - Semantic search with layer filtering."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from opentelemetry import trace

from context_service.cache.rerank_cache import SemanticRerankCache
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
    LiteLLMReranker,
    QueryExpander,
    apply_threshold_filter,
    compute_adaptive_threshold,
    compute_retrieval_quality,
    is_hard_query,
)
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership
from context_service.signals import emit_access_event
from context_service.telemetry.metrics import (
    record_adaptive_threshold,
    record_hard_query_detection,
    record_mcp_tool,
    record_query_expansion,
    record_reranking,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_VALID_SEARCH_MODES = frozenset({"hybrid", "dense", "sparse"})

_result_cache: ResultCacheStore | None = None
_rerank_cache: SemanticRerankCache | None = None


def _get_result_cache() -> ResultCacheStore:
    global _result_cache
    if _result_cache is None:
        _result_cache = ResultCacheStore()
    return _result_cache


def _get_rerank_cache(qdrant: Any, settings: Any) -> SemanticRerankCache | None:
    """Get or create the rerank cache singleton."""
    global _rerank_cache
    if not settings.reranking.cache_enabled:
        return None
    if _rerank_cache is None:
        _rerank_cache = SemanticRerankCache(
            qdrant=qdrant,
            similarity_threshold=settings.reranking.cache_similarity_threshold,
            l1_ttl_seconds=settings.reranking.cache_l1_ttl_seconds,
            l1_maxsize=settings.reranking.cache_l1_maxsize,
            embedding_dimensions=settings.embedding_dimensions,
        )
    return _rerank_cache


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


async def _apply_reranking(
    query: str,
    results: list[Any],
    settings: Any,
    query_embedding: list[float] | None = None,
    silo_id: str | None = None,
    rerank_cache: SemanticRerankCache | None = None,
) -> tuple[list[Any], bool, bool]:
    """Apply reranking to search results if enabled.

    Returns:
        (reranked_results, fallback_used, reranked_applied)

        ``fallback_used`` is True when the reranker service failed and cosine
        scores were preserved (i.e. reranking did NOT apply).

        ``reranked_applied`` is True only when reranking ran successfully
        (fresh or cache-hit) and the reranker scores have been written back
        into each result's ``relevance_score``.  It is False for all
        early-return paths and for the fallback path.
    """
    if not settings.reranking.enabled or len(results) <= 1:
        return results, False, False

    # Skip reranking if top result has high confidence (saves a round-trip)
    top_score = max((r.relevance_score or 0.0) for r in results)
    if top_score >= settings.reranking.skip_rerank_threshold:
        logger.debug(
            "rerank_skipped_high_confidence",
            top_score=top_score,
            threshold=settings.reranking.skip_rerank_threshold,
        )
        return results, False, False

    models_config = load_models_config()
    reranker_model = models_config.litellm_reranker_model
    if reranker_model is None:
        return results, False, False

    node_ids = [str(r.node_id) for r in results]
    id_to_result = {str(r.node_id): r for r in results}

    # Check rerank cache first
    if rerank_cache is not None and query_embedding is not None and silo_id is not None:
        cached_scores = await rerank_cache.get(query, query_embedding, node_ids, silo_id)
        if cached_scores is not None:
            # Write cached reranker scores back into each result object.
            wrote_any = False
            for node_id, score in cached_scores:
                if node_id in id_to_result:
                    id_to_result[node_id].relevance_score = score
                    wrote_any = True
            # Only treat this as a cache hit if at least one cached id matched
            # the current result set. A stale cache (no overlap) falls through
            # to a fresh rerank rather than reporting reranked_applied=True with
            # no scores actually written (which would threshold cosine scores
            # against the rerank floor).
            if wrote_any:
                score_map = dict(cached_scores)
                reranked_results = sorted(
                    results,
                    key=lambda r: score_map.get(str(r.node_id), 0.0),
                    reverse=True,
                )
                return reranked_results, False, True

    reranker = LiteLLMReranker(
        model=reranker_model,
        timeout_seconds=settings.reranking.reranker_timeout_seconds,
        vertex_project=settings.vertex_project,
    )
    documents = [r.content or "" for r in results]

    with tracer.start_as_current_span("recall.rerank") as span:
        span.set_attribute("query_length", len(query))
        span.set_attribute("candidates", len(results))
        rerank_start = time.perf_counter()
        fallback_used = False
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
            # Return in original order with fallback flag; do not propagate.
            # Leave cosine scores intact -- do not write reranker scores back.
            fallback_used = True
            return results, fallback_used, False

    # Write reranker scores back into each result object (only on success)
    for rr in reranked:
        if rr.node_id in id_to_result:
            id_to_result[rr.node_id].relevance_score = rr.score

    # Store in cache for future queries
    if rerank_cache is not None and query_embedding is not None and silo_id is not None:
        scores = [(rr.node_id, rr.score) for rr in reranked]
        await rerank_cache.set(query, query_embedding, node_ids, scores, silo_id)

    reranked_results = [id_to_result[rr.node_id] for rr in reranked if rr.node_id in id_to_result]
    return reranked_results, fallback_used, True


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
            search_mode,
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

    # Get query embedding for rerank cache (reuses cached embedding from vector search)
    query_embedding: list[float] | None = None
    rerank_cache = _get_rerank_cache(ctx_svc.vector_store, settings)
    if rerank_cache is not None and ctx_svc.embedding_client is not None:
        try:
            query_embedding = await ctx_svc.embedding_client.embed_query(effective_query)
        except Exception as e:
            logger.warning("rerank_cache_embed_failed", error=str(e))

    results, rerank_fallback, reranked_applied = await _apply_reranking(
        effective_query,
        results,
        settings,
        query_embedding=query_embedding,
        silo_id=silo_id,
        rerank_cache=rerank_cache,
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

    # Score-adaptive truncation (SmartSearch-style): tau = alpha * max_score
    effective_min_threshold = min_threshold
    if settings.reranking.adaptive_threshold_enabled and reranked_applied:
        adaptive_tau, max_score = compute_adaptive_threshold(
            raw_result_dicts,
            alpha=settings.reranking.adaptive_alpha,
        )
        if effective_min_threshold is None or adaptive_tau > effective_min_threshold:
            effective_min_threshold = adaptive_tau

        def _score_above_tau(r: dict[str, Any]) -> bool:
            s = r.get("relevance_score")
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
        result_dicts, below_threshold, fallback_used=rerank_fallback
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
            search_mode,
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

"""OpenTelemetry metrics instrumentation."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from context_service import __version__

_meter: metrics.Meter | None = None

# Instruments (initialized lazily)
_request_duration: metrics.Histogram | None = None
_request_counter: metrics.Counter | None = None
_active_requests: metrics.UpDownCounter | None = None
_db_query_duration: metrics.Histogram | None = None
_embedding_duration: metrics.Histogram | None = None
_mcp_tool_duration: metrics.Histogram | None = None
_mcp_tool_counter: metrics.Counter | None = None
_llm_token_counter: metrics.Counter | None = None
_llm_call_duration: metrics.Histogram | None = None
_context_recall_size: metrics.Histogram | None = None
_chain_lookup_counter: metrics.Counter | None = None
_chain_lookup_latency: metrics.Histogram | None = None
_chain_feedback_counter: metrics.Counter | None = None
_chain_evidence_modified_counter: metrics.Counter | None = None
_reranking_duration: metrics.Histogram | None = None
_reranking_counter: metrics.Counter | None = None
_query_expansion_duration: metrics.Histogram | None = None
_query_expansion_counter: metrics.Counter | None = None
_hard_query_counter: metrics.Counter | None = None
_store_error_counter: metrics.Counter | None = None
_circuit_breaker_state: metrics.UpDownCounter | None = None
_circuit_breaker_trips: metrics.Counter | None = None
_orphan_chains_exhausted: metrics.Counter | None = None
_orphan_chains_recovered: metrics.Counter | None = None
_source_tier_counter: metrics.Counter | None = None
_embedding_cache_hit_counter: metrics.Counter | None = None
_embedding_cache_miss_counter: metrics.Counter | None = None
_belief_confidence: metrics.Histogram | None = None
_cache_hit_counter: metrics.Counter | None = None
_cache_miss_counter: metrics.Counter | None = None
_cache_eviction_counter: metrics.Counter | None = None
_recall_latency: metrics.Histogram | None = None
_recall_depth_counter: metrics.Counter | None = None
_recall_result_count: metrics.Histogram | None = None
_tool_error_counter: metrics.Counter | None = None
_supersession_used_counter: metrics.Counter | None = None
_supersession_skipped_counter: metrics.Counter | None = None
_node_confidence: metrics.Histogram | None = None
_engagement_latency: metrics.Histogram | None = None


def setup_metrics(service_name: str = "context-service") -> None:
    """Initialize OpenTelemetry metrics if OTEL_EXPORTER_OTLP_ENDPOINT is set."""
    global _meter, _request_duration, _request_counter, _active_requests
    global _db_query_duration, _embedding_duration, _mcp_tool_duration, _mcp_tool_counter
    global _llm_token_counter, _llm_call_duration, _context_recall_size
    global \
        _chain_lookup_counter, \
        _chain_lookup_latency, \
        _chain_feedback_counter, \
        _chain_evidence_modified_counter
    global \
        _reranking_duration, \
        _reranking_counter, \
        _query_expansion_duration, \
        _query_expansion_counter, \
        _hard_query_counter, \
        _store_error_counter, \
        _circuit_breaker_state, \
        _circuit_breaker_trips, \
        _orphan_chains_exhausted, \
        _orphan_chains_recovered, \
        _source_tier_counter, \
        _embedding_cache_hit_counter, \
        _embedding_cache_miss_counter, \
        _belief_confidence, \
        _cache_hit_counter, \
        _cache_miss_counter, \
        _cache_eviction_counter, \
        _recall_latency, \
        _recall_depth_counter, \
        _recall_result_count, \
        _tool_error_counter, \
        _supersession_used_counter, \
        _supersession_skipped_counter, \
        _node_confidence, \
        _engagement_latency

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": __version__,
        }
    )

    insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true"
    exporter = OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=10000)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    _meter = metrics.get_meter(__name__, __version__)

    _request_duration = _meter.create_histogram(
        name="http.server.duration",
        description="HTTP request duration",
        unit="ms",
    )

    _request_counter = _meter.create_counter(
        name="http.server.request.count",
        description="HTTP request count",
        unit="1",
    )

    _active_requests = _meter.create_up_down_counter(
        name="http.server.active_requests",
        description="Active HTTP requests",
        unit="1",
    )

    _db_query_duration = _meter.create_histogram(
        name="db.query.duration",
        description="Database query duration",
        unit="ms",
    )

    _embedding_duration = _meter.create_histogram(
        name="embedding.duration",
        description="Embedding generation duration",
        unit="ms",
    )

    _mcp_tool_duration = _meter.create_histogram(
        name="mcp.tool.duration",
        description="MCP tool invocation duration",
        unit="ms",
    )

    _mcp_tool_counter = _meter.create_counter(
        name="mcp.tool.invocations",
        description="MCP tool invocation count",
        unit="1",
    )

    _llm_token_counter = _meter.create_counter(
        name="llm.tokens",
        description="LLM token usage",
        unit="1",
    )

    _llm_call_duration = _meter.create_histogram(
        name="llm.call.duration",
        description="LLM API call duration",
        unit="ms",
    )

    _context_recall_size = _meter.create_histogram(
        name="context.recall.size",
        description="Context recall response size",
        unit="bytes",
    )

    _chain_lookup_counter = _meter.create_counter(
        name="reasoning.chain.lookup",
        description="Reasoning chain lookup attempts",
        unit="1",
    )

    _chain_lookup_latency = _meter.create_histogram(
        name="reasoning.chain.lookup.latency",
        description="Reasoning chain lookup latency",
        unit="ms",
    )

    _chain_feedback_counter = _meter.create_counter(
        name="reasoning.chain.feedback",
        description="Reasoning chain usefulness feedback",
        unit="1",
    )

    _chain_evidence_modified_counter = _meter.create_counter(
        name="reasoning.chain.evidence_modified_post_creation",
        description="Chains returned where evidence was modified after chain creation",
        unit="1",
    )

    _reranking_duration = _meter.create_histogram(
        name="recall.reranking.duration",
        description="Reranking operation latency",
        unit="ms",
    )

    _reranking_counter = _meter.create_counter(
        name="recall.reranking.count",
        description="Reranking operation count",
        unit="1",
    )

    _query_expansion_duration = _meter.create_histogram(
        name="recall.query_expansion.duration",
        description="Query expansion latency",
        unit="ms",
    )

    _query_expansion_counter = _meter.create_counter(
        name="recall.query_expansion.count",
        description="Query expansion operation count",
        unit="1",
    )

    _hard_query_counter = _meter.create_counter(
        name="recall.hard_query.count",
        description="Hard query detection count",
        unit="1",
    )

    _store_error_counter = _meter.create_counter(
        name="store.errors",
        description="Store operation errors",
        unit="1",
    )

    _circuit_breaker_state = _meter.create_up_down_counter(
        name="circuit_breaker_state",
        description="Circuit breaker state (1=open, 0=closed) per store",
        unit="1",
    )

    _circuit_breaker_trips = _meter.create_counter(
        name="circuit_breaker_trips_total",
        description="Total number of circuit breaker trips (closed->open) per store",
        unit="1",
    )

    _orphan_chains_exhausted = _meter.create_counter(
        name="context_orphan_chains_exhausted_total",
        description="Number of orphan chains that exhausted all retries",
        unit="1",
    )

    _orphan_chains_recovered = _meter.create_counter(
        name="context_orphan_chains_recovered_total",
        description="Number of orphan chains successfully recovered",
        unit="1",
    )

    _source_tier_counter = _meter.create_counter(
        name="source_tier_resolved",
        description="Count of source tier resolutions by tier and layer",
        unit="1",
    )

    _embedding_cache_hit_counter = _meter.create_counter(
        name="embedding.cache.hit",
        description="Embedding cache hits",
        unit="1",
    )

    _embedding_cache_miss_counter = _meter.create_counter(
        name="embedding.cache.miss",
        description="Embedding cache misses",
        unit="1",
    )

    _belief_confidence = _meter.create_histogram(
        name="belief.confidence",
        description="Confidence score of declared beliefs",
        unit="1",
    )

    _cache_hit_counter = _meter.create_counter(
        name="cache.hit",
        description="Cache hits",
        unit="1",
    )
    _cache_miss_counter = _meter.create_counter(
        name="cache.miss",
        description="Cache misses",
        unit="1",
    )
    _cache_eviction_counter = _meter.create_counter(
        name="cache.eviction",
        description="Cache evictions",
        unit="1",
    )
    _recall_latency = _meter.create_histogram(
        name="recall.latency",
        description="Recall operation latency",
        unit="ms",
    )
    _recall_depth_counter = _meter.create_counter(
        name="recall.depth",
        description="Recall depth distribution",
        unit="1",
    )
    _recall_result_count = _meter.create_histogram(
        name="recall.result_count",
        description="Number of results returned by recall",
        unit="1",
    )

    _tool_error_counter = _meter.create_counter(
        name="tool.error",
        description="Tool errors by type",
        unit="1",
    )

    _supersession_used_counter = _meter.create_counter(
        name="store.supersession_used",
        description="Writes that used supersession",
        unit="1",
    )

    _supersession_skipped_counter = _meter.create_counter(
        name="store.supersession_skipped",
        description="Duplicates caught by Custodian that should have been supersession",
        unit="1",
    )

    _node_confidence = _meter.create_histogram(
        name="node.confidence",
        description="Confidence distribution at write time",
        unit="1",
    )

    _engagement_latency = _meter.create_histogram(
        name="recall.engagement.latency",
        description="Engagement detection latency during recall",
        unit="ms",
    )


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    """Record HTTP request metrics."""
    if _request_duration is None:
        return
    attrs: dict[str, str | int] = {
        "http.method": method,
        "http.route": path,
        "http.status_code": status,
    }
    _request_duration.record(duration_ms, attrs)
    if _request_counter:
        _request_counter.add(1, attrs)


@contextmanager
def track_active_request(method: str, path: str) -> Generator[None, None, None]:
    """Track active request count."""
    attrs = {"http.method": method, "http.route": path}
    if _active_requests:
        _active_requests.add(1, attrs)
    try:
        yield
    finally:
        if _active_requests:
            _active_requests.add(-1, attrs)


def record_db_query(operation: str, duration_ms: float) -> None:
    """Record database query duration."""
    if _db_query_duration is None:
        return
    _db_query_duration.record(duration_ms, {"db.operation": operation})


def record_embedding(model: str, duration_ms: float, silo_id: str | None = None) -> None:
    """Record embedding generation duration."""
    if _embedding_duration is None:
        return
    attributes: dict[str, str] = {"model": model}
    if silo_id:
        attributes["silo_id"] = silo_id
    _embedding_duration.record(duration_ms, attributes)


def record_mcp_tool(
    tool: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record MCP tool invocation metrics."""
    attrs: dict[str, str] = {"mcp.tool": tool, "success": str(success).lower()}
    if silo_id:
        attrs["silo_id"] = silo_id
    if _mcp_tool_duration:
        _mcp_tool_duration.record(duration_ms, attrs)
    if _mcp_tool_counter:
        _mcp_tool_counter.add(1, attrs)


def record_llm_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage."""
    if _llm_token_counter is None:
        return
    _llm_token_counter.add(input_tokens, {"model": model, "type": "input"})
    _llm_token_counter.add(output_tokens, {"model": model, "type": "output"})


def record_llm_call(
    model: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record LLM call duration."""
    if _llm_call_duration is None:
        return
    attributes: dict[str, str] = {"model": model, "success": str(success).lower()}
    if silo_id:
        attributes["silo_id"] = silo_id
    _llm_call_duration.record(duration_ms, attributes)


def record_context_recall_size(layer: str, bytes_size: int) -> None:
    """Record context recall response size for token estimation."""
    if _context_recall_size is None:
        return
    _context_recall_size.record(bytes_size, {"layer": layer})


def _bucket_similarity(score: float) -> str:
    """Bucket a similarity score into a fixed label to avoid high cardinality."""
    if score >= 0.9:
        return "0.9-1.0"
    if score >= 0.8:
        return "0.8-0.9"
    if score >= 0.7:
        return "0.7-0.8"
    if score >= 0.5:
        return "0.5-0.7"
    return "0.0-0.5"


def record_chain_lookup(
    hit: bool,
    layer_reached: int,
    similarity_score: float | None,
    cold_start: bool,
    latency_ms: float,
) -> None:
    """Record reasoning chain lookup attempt."""
    if _chain_lookup_counter is None:
        return
    attrs: dict[str, str] = {
        "hit": str(hit).lower(),
        "layer": str(layer_reached),
        "cold_start": str(cold_start).lower(),
        "similarity_bucket": _bucket_similarity(similarity_score)
        if similarity_score is not None
        else "none",
    }
    _chain_lookup_counter.add(1, attrs)
    if _chain_lookup_latency is not None:
        _chain_lookup_latency.record(
            latency_ms,
            {"hit": str(hit).lower(), "cold_start": str(cold_start).lower()},
        )


def record_chain_feedback(signal: str) -> None:
    """Record reasoning chain usefulness feedback."""
    if _chain_feedback_counter is None:
        return
    _chain_feedback_counter.add(1, {"signal": signal})


def record_chain_evidence_modified() -> None:
    """Record when a returned chain has evidence modified after creation."""
    if _chain_evidence_modified_counter is None:
        return
    _chain_evidence_modified_counter.add(1)


def record_reranking(latency_ms: float, success: bool) -> None:
    """Record reranking operation metrics."""
    attrs = {"success": str(success).lower()}
    if _reranking_duration is not None:
        _reranking_duration.record(latency_ms, attrs)
    if _reranking_counter is not None:
        _reranking_counter.add(1, attrs)


def record_query_expansion(latency_ms: float, success: bool) -> None:
    """Record query expansion metrics.

    Note: cache_hit information is not currently exposed by QueryExpander.expand().
    A TODO exists to plumb that through when the expander is extended.
    """
    attrs = {"success": str(success).lower()}
    if _query_expansion_duration is not None:
        _query_expansion_duration.record(latency_ms, attrs)
    if _query_expansion_counter is not None:
        _query_expansion_counter.add(1, attrs)


def record_hard_query_detection(is_hard: bool) -> None:
    """Record hard query detection for monitoring."""
    if _hard_query_counter is not None:
        _hard_query_counter.add(1, {"is_hard": str(is_hard).lower()})


def record_circuit_breaker_opened(store: str) -> None:
    """Record a circuit breaker trip (closed -> open)."""
    if _circuit_breaker_trips is not None:
        _circuit_breaker_trips.add(1, {"store": store})
    if _circuit_breaker_state is not None:
        _circuit_breaker_state.add(1, {"store": store})


def record_circuit_breaker_closed(store: str) -> None:
    """Record a circuit breaker reset (open -> closed)."""
    if _circuit_breaker_state is not None:
        _circuit_breaker_state.add(-1, {"store": store})


def record_store_error(store: str, operation: str) -> None:
    """Record a store operation error."""
    if _store_error_counter is None:
        return
    _store_error_counter.add(1, {"store": store, "operation": operation})


def record_orphan_chain_exhausted(silo_id: str) -> None:
    """Record an orphan chain that exhausted all retries."""
    if _orphan_chains_exhausted is None:
        return
    _orphan_chains_exhausted.add(1, {"silo_id": silo_id})


def record_orphan_chain_recovered(silo_id: str) -> None:
    """Record an orphan chain that was successfully recovered."""
    if _orphan_chains_recovered is None:
        return
    _orphan_chains_recovered.add(1, {"silo_id": silo_id})


def record_source_tier_resolved(tier: str, layer: str, silo_id: str) -> None:
    """Record a source tier resolution event."""
    if _source_tier_counter is None:
        return
    _source_tier_counter.add(1, {"tier": tier, "resolution_layer": layer, "silo_id": silo_id})


def record_embedding_cache_hit(task: str) -> None:
    """Record an embedding cache hit."""
    if _embedding_cache_hit_counter is None:
        return
    _embedding_cache_hit_counter.add(1, {"task": task})


def record_embedding_cache_miss(task: str) -> None:
    """Record an embedding cache miss."""
    if _embedding_cache_miss_counter is None:
        return
    _embedding_cache_miss_counter.add(1, {"task": task})


def record_belief_confidence(confidence: float, silo_id: str | None = None) -> None:
    """Record the confidence score of a declared belief."""
    if _belief_confidence is None:
        return
    attributes: dict[str, str] = {}
    if silo_id:
        attributes["silo_id"] = silo_id
    _belief_confidence.record(confidence, attributes)


def record_cache_hit(cache_type: str, silo_id: str | None = None) -> None:
    if _cache_hit_counter is None:
        return
    attrs: dict[str, str] = {"cache_type": cache_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _cache_hit_counter.add(1, attrs)


def record_cache_miss(cache_type: str, silo_id: str | None = None) -> None:
    if _cache_miss_counter is None:
        return
    attrs: dict[str, str] = {"cache_type": cache_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _cache_miss_counter.add(1, attrs)


def record_cache_eviction(cache_type: str, silo_id: str | None = None) -> None:
    if _cache_eviction_counter is None:
        return
    attrs: dict[str, str] = {"cache_type": cache_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _cache_eviction_counter.add(1, attrs)


def record_recall_latency(
    duration_ms: float,
    depth: int,
    source: str,
    silo_id: str | None = None,
) -> None:
    if _recall_latency is None:
        return
    attrs: dict[str, str] = {"depth": str(depth), "source": source}
    if silo_id:
        attrs["silo_id"] = silo_id
    _recall_latency.record(duration_ms, attrs)


def record_recall_depth(depth: int, silo_id: str | None = None) -> None:
    if _recall_depth_counter is None:
        return
    attrs: dict[str, str] = {"depth": str(depth)}
    if silo_id:
        attrs["silo_id"] = silo_id
    _recall_depth_counter.add(1, attrs)


def record_recall_result_count(
    count: int,
    layer: str,
    silo_id: str | None = None,
) -> None:
    if _recall_result_count is None:
        return
    attrs: dict[str, str] = {"layer": layer}
    if silo_id:
        attrs["silo_id"] = silo_id
    _recall_result_count.record(count, attrs)


def record_tool_error(tool_name: str, error_type: str, silo_id: str | None = None) -> None:
    if _tool_error_counter is None:
        return
    attrs: dict[str, str] = {"tool": tool_name, "error_type": error_type}
    if silo_id:
        attrs["silo_id"] = silo_id
    _tool_error_counter.add(1, attrs)


def record_supersession_used(tool_name: str, silo_id: str | None = None) -> None:
    if _supersession_used_counter is None:
        return
    attrs: dict[str, str] = {"tool": tool_name}
    if silo_id:
        attrs["silo_id"] = silo_id
    _supersession_used_counter.add(1, attrs)


def record_supersession_skipped(silo_id: str | None = None) -> None:
    if _supersession_skipped_counter is None:
        return
    attrs: dict[str, str] = {}
    if silo_id:
        attrs["silo_id"] = silo_id
    _supersession_skipped_counter.add(1, attrs)


def record_node_confidence(confidence: float, layer: str, silo_id: str | None = None) -> None:
    if _node_confidence is None:
        return
    attrs: dict[str, str] = {"layer": layer}
    if silo_id:
        attrs["silo_id"] = silo_id
    _node_confidence.record(confidence, attrs)


def record_engagement_latency(duration_ms: float, silo_id: str | None = None) -> None:
    """Record engagement detection latency during recall."""
    if _engagement_latency is None:
        return
    attrs: dict[str, str] = {}
    if silo_id:
        attrs["silo_id"] = silo_id
    _engagement_latency.record(duration_ms, attrs)


# Public references used for import checks and direct access
ORPHAN_CHAINS_EXHAUSTED = record_orphan_chain_exhausted
ORPHAN_CHAINS_RECOVERED = record_orphan_chain_recovered

"""PG-based telemetry recorder implementations.

All record_* functions write to an in-process MetricsBuffer.
The buffer is flushed periodically to PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from context_service.telemetry.buffer import MetricsBuffer

if TYPE_CHECKING:
    import asyncpg

_buffer: MetricsBuffer | None = None
_db_pool: asyncpg.Pool | None = None


def setup_metrics(service_name: str = "context-service") -> None:
    """Initialize telemetry. Call once at startup."""
    global _buffer
    _buffer = MetricsBuffer()


def set_db_pool(pool: asyncpg.Pool) -> None:
    """Set the database pool for flushing."""
    global _db_pool
    _db_pool = pool


def get_buffer() -> MetricsBuffer | None:
    """Get the global metrics buffer."""
    return _buffer


def get_db_pool() -> asyncpg.Pool | None:
    """Get the database pool for flushing."""
    return _db_pool


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    """Record HTTP request metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"http.{method}.{status}",
        silo_id="system",
        latency_ms=duration_ms,
    )


@contextmanager
def track_active_request(method: str, path: str) -> Generator[None, None, None]:
    """Track active request count (no-op in PG mode)."""
    yield


def record_db_query(operation: str, duration_ms: float) -> None:
    """Record database query duration."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"db.{operation}",
        silo_id="system",
        latency_ms=duration_ms,
    )


def record_embedding(model: str, duration_ms: float, silo_id: str | None = None) -> None:
    """Record embedding generation duration."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"embedding.{model}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
    )


def record_mcp_tool(
    tool: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record MCP tool invocation metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"tool.{tool}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
        error=not success,
    )


def record_llm_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"llm.tokens.{model}.input", silo_id="system", count=input_tokens)
    _buffer.record(metric_name=f"llm.tokens.{model}.output", silo_id="system", count=output_tokens)


def record_llm_call(
    model: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record LLM call duration."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"llm.{model}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
        error=not success,
    )


def record_context_recall_size(layer: str, bytes_size: int) -> None:
    """Record context recall response size."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"recall.size.{layer}", silo_id="system")


def record_chain_lookup(
    hit: bool,
    layer_reached: int,
    similarity_score: float | None,
    cold_start: bool,
    latency_ms: float,
) -> None:
    """Record reasoning chain lookup attempt."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"chain.lookup.{'hit' if hit else 'miss'}",
        silo_id="system",
        latency_ms=latency_ms,
    )


def record_chain_feedback(signal: str) -> None:
    """Record reasoning chain usefulness feedback."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"chain.feedback.{signal}", silo_id="system")


def record_chain_evidence_modified() -> None:
    """Record when a returned chain has evidence modified after creation."""
    if _buffer is None:
        return
    _buffer.record(metric_name="chain.evidence_modified", silo_id="system")


def record_reranking(latency_ms: float, success: bool) -> None:
    """Record reranking operation metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name="recall.reranking",
        silo_id="system",
        latency_ms=latency_ms,
        error=not success,
    )


def record_query_expansion(latency_ms: float, success: bool) -> None:
    """Record query expansion metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name="recall.query_expansion",
        silo_id="system",
        latency_ms=latency_ms,
        error=not success,
    )


def record_hard_query_detection(is_hard: bool) -> None:
    """Record hard query detection."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"recall.hard_query.{'true' if is_hard else 'false'}",
        silo_id="system",
    )


def record_circuit_breaker_opened(store: str) -> None:
    """Record a circuit breaker trip."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"circuit_breaker.{store}.opened", silo_id="system")


def record_circuit_breaker_closed(store: str) -> None:
    """Record a circuit breaker reset."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"circuit_breaker.{store}.closed", silo_id="system")


def record_store_error(store: str, operation: str) -> None:
    """Record a store operation error."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"store.{store}.error", silo_id="system", error=True)


def record_orphan_chain_exhausted(silo_id: str) -> None:
    """Record an orphan chain that exhausted all retries."""
    if _buffer is None:
        return
    _buffer.record(metric_name="chain.orphan.exhausted", silo_id=silo_id)


def record_orphan_chain_recovered(silo_id: str) -> None:
    """Record an orphan chain that was successfully recovered."""
    if _buffer is None:
        return
    _buffer.record(metric_name="chain.orphan.recovered", silo_id=silo_id)


def record_source_tier_resolved(tier: str, layer: str, silo_id: str) -> None:
    """Record a source tier resolution event."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"source_tier.{tier}.{layer}", silo_id=silo_id)


def record_embedding_cache_hit(task: str) -> None:
    """Record an embedding cache hit."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"embedding.cache.{task}.hit", silo_id="system")


def record_embedding_cache_miss(task: str) -> None:
    """Record an embedding cache miss."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"embedding.cache.{task}.miss", silo_id="system")


def record_belief_confidence(confidence: float, silo_id: str | None = None) -> None:
    """Record the confidence score of a declared belief."""
    if _buffer is None:
        return
    _buffer.record(metric_name="belief.confidence", silo_id=silo_id or "unknown")


def record_cache_hit(cache_type: str, silo_id: str | None = None) -> None:
    """Record cache hit."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"cache.{cache_type}.hit", silo_id=silo_id or "unknown")


def record_cache_miss(cache_type: str, silo_id: str | None = None) -> None:
    """Record cache miss."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"cache.{cache_type}.miss", silo_id=silo_id or "unknown")


def record_cache_eviction(cache_type: str, silo_id: str | None = None) -> None:
    """Record cache eviction."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"cache.{cache_type}.eviction", silo_id=silo_id or "unknown")


def record_recall_latency(
    duration_ms: float,
    depth: int,
    source: str,
    silo_id: str | None = None,
) -> None:
    """Record recall operation latency."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"recall.{source}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
    )


def record_recall_depth(depth: int, silo_id: str | None = None) -> None:
    """Record recall depth."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"recall.depth.{depth}", silo_id=silo_id or "unknown")


def record_recall_result_count(count: int, layer: str, silo_id: str | None = None) -> None:
    """Record recall result count."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"recall.results.{layer}", silo_id=silo_id or "unknown")


def record_tool_error(tool_name: str, error_type: str, silo_id: str | None = None) -> None:
    """Record tool error."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"tool.{tool_name}",
        silo_id=silo_id or "unknown",
        error=True,
    )


def record_supersession_used(tool_name: str, silo_id: str | None = None) -> None:
    """Record supersession usage."""
    if _buffer is None:
        return
    _buffer.record(metric_name="store.supersession_used", silo_id=silo_id or "unknown")


def record_supersession_skipped(silo_id: str | None = None) -> None:
    """Record supersession skipped."""
    if _buffer is None:
        return
    _buffer.record(metric_name="store.supersession_skipped", silo_id=silo_id or "unknown")


def record_node_confidence(confidence: float, layer: str, silo_id: str | None = None) -> None:
    """Record node confidence at write time."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"node.confidence.{layer}", silo_id=silo_id or "unknown")


def record_engagement_latency(duration_ms: float, silo_id: str | None = None) -> None:
    """Record engagement detection latency during recall."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name="recall.engagement",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
    )


ORPHAN_CHAINS_EXHAUSTED = record_orphan_chain_exhausted
ORPHAN_CHAINS_RECOVERED = record_orphan_chain_recovered

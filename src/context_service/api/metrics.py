"""Prometheus metrics registry for context-service."""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry(auto_describe=True)

# ---------------------------------------------------------------------------
# HTTP request metrics
# ---------------------------------------------------------------------------

HTTP_REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency by endpoint and method",
    labelnames=["method", "endpoint", "status_code"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests by endpoint, method, and status",
    labelnames=["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# MCP tool metrics
# ---------------------------------------------------------------------------

CONTEXT_QUERY_LATENCY = Histogram(
    "context_query_latency_seconds",
    "Latency of context_query MCP tool calls",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

CONTEXT_STORE_LATENCY = Histogram(
    "context_store_latency_seconds",
    "Latency of context store write operations (remember/assert/commit/reflect)",
    labelnames=["tool"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

CONTEXT_GET_LATENCY = Histogram(
    "context_get_latency_seconds",
    "Latency of context_get MCP tool calls",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Business metrics
# ---------------------------------------------------------------------------

EXTRACTION_CLAIMS_TOTAL = Counter(
    "extraction_claims_total",
    "Total claims extracted from documents",
    labelnames=["silo_id"],
    registry=REGISTRY,
)

CUSTODIAN_PROMOTIONS_TOTAL = Counter(
    "custodian_promotions_total",
    "Total claims promoted to facts by the custodian",
    registry=REGISTRY,
)

CUSTODIAN_REJECTIONS_TOTAL = Counter(
    "custodian_rejections_total",
    "Total claims rejected by the custodian",
    labelnames=["reason"],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------


async def metrics_endpoint(_request: Request) -> Response:
    """Expose Prometheus metrics in text format."""
    output = generate_latest(REGISTRY)
    return Response(
        content=output,
        media_type=CONTENT_TYPE_LATEST,
    )


__all__ = [
    "REGISTRY",
    "HTTP_REQUEST_LATENCY",
    "HTTP_REQUESTS_TOTAL",
    "CONTEXT_QUERY_LATENCY",
    "CONTEXT_STORE_LATENCY",
    "CONTEXT_GET_LATENCY",
    "EXTRACTION_CLAIMS_TOTAL",
    "CUSTODIAN_PROMOTIONS_TOTAL",
    "CUSTODIAN_REJECTIONS_TOTAL",
    "metrics_endpoint",
]

"""Prometheus metrics registry for context-service."""

from __future__ import annotations

import hashlib

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response


def _anonymize_silo_id(silo_id: str | object) -> str:
    """Hash silo_id for metrics labels to prevent tenant enumeration.

    Uses first 8 chars of SHA256 - sufficient for cardinality, not reversible.
    """
    silo_str = str(silo_id) if not isinstance(silo_id, str) else silo_id
    return hashlib.sha256(silo_str.encode()).hexdigest()[:8]


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

CONTEXT_STORE_LATENCY = Histogram(
    "context_store_latency_seconds",
    "Latency of context store write operations",
    labelnames=["silo_id", "layer"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Confidence distribution metrics
# ---------------------------------------------------------------------------

_CONFIDENCE_BUCKETS = (0.1, 0.3, 0.5, 0.7, 0.9, float("inf"))

EDGE_CONFIDENCE_DISTRIBUTION = Histogram(
    "edge_confidence_distribution",
    "Distribution of edge confidence values at write time",
    labelnames=["silo_id", "edge_type"],
    buckets=_CONFIDENCE_BUCKETS,
    registry=REGISTRY,
)

BELIEF_CONFIDENCE_DISTRIBUTION = Histogram(
    "belief_confidence_distribution",
    "Distribution of belief confidence values at write time",
    labelnames=["silo_id", "edge_type"],
    buckets=_CONFIDENCE_BUCKETS,
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


def record_edge_confidence(
    confidence: float,
    *,
    silo_id: str,
    edge_type: str,
) -> None:
    """Observe a confidence value on the edge histogram.

    Call this from write paths (context_assert, context_link, causal assets)
    after persisting an edge.
    """
    anon_silo = _anonymize_silo_id(silo_id)
    EDGE_CONFIDENCE_DISTRIBUTION.labels(silo_id=anon_silo, edge_type=edge_type).observe(confidence)


def record_belief_confidence(
    confidence: float,
    *,
    silo_id: str,
    edge_type: str,
) -> None:
    """Observe a confidence value on the belief histogram.

    Call this from belief-synthesis and commit write paths.
    """
    anon_silo = _anonymize_silo_id(silo_id)
    BELIEF_CONFIDENCE_DISTRIBUTION.labels(silo_id=anon_silo, edge_type=edge_type).observe(
        confidence
    )


def record_store_latency(
    latency_seconds: float,
    *,
    silo_id: str,
    layer: str,
) -> None:
    """Record latency for context store operations with anonymized silo_id."""
    anon_silo = _anonymize_silo_id(silo_id)
    CONTEXT_STORE_LATENCY.labels(silo_id=anon_silo, layer=layer).observe(latency_seconds)


def record_extraction_claim(*, silo_id: str) -> None:
    """Increment extraction claims counter with anonymized silo_id."""
    anon_silo = _anonymize_silo_id(silo_id)
    EXTRACTION_CLAIMS_TOTAL.labels(silo_id=anon_silo).inc()


__all__ = [
    "REGISTRY",
    "HTTP_REQUEST_LATENCY",
    "HTTP_REQUESTS_TOTAL",
    "CUSTODIAN_PROMOTIONS_TOTAL",
    "CUSTODIAN_REJECTIONS_TOTAL",
    "record_edge_confidence",
    "record_belief_confidence",
    "record_store_latency",
    "record_extraction_claim",
    "metrics_endpoint",
]

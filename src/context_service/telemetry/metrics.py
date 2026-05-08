"""OpenTelemetry metrics instrumentation."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Generator

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


def setup_metrics(service_name: str = "context-service") -> None:
    """Initialize OpenTelemetry metrics if OTEL_EXPORTER_OTLP_ENDPOINT is set."""
    global _meter, _request_duration, _request_counter, _active_requests
    global _db_query_duration, _embedding_duration, _mcp_tool_duration, _mcp_tool_counter

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": __version__,
        }
    )

    exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
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


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    """Record HTTP request metrics."""
    if _request_duration is None:
        return
    attrs = {"http.method": method, "http.route": path, "http.status_code": status}
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


def record_embedding(model: str, duration_ms: float) -> None:
    """Record embedding generation duration."""
    if _embedding_duration is None:
        return
    _embedding_duration.record(duration_ms, {"model": model})


def record_mcp_tool(tool: str, duration_ms: float, success: bool = True) -> None:
    """Record MCP tool invocation metrics."""
    attrs = {"mcp.tool": tool, "success": str(success).lower()}
    if _mcp_tool_duration:
        _mcp_tool_duration.record(duration_ms, attrs)
    if _mcp_tool_counter:
        _mcp_tool_counter.add(1, attrs)


@contextmanager
def timed_operation(
    record_fn: callable, **attrs: str
) -> Generator[None, None, None]:
    """Context manager to time an operation and record it."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        record_fn(duration_ms=duration_ms, **attrs)

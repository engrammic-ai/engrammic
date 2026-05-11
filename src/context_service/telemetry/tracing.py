"""OpenTelemetry tracing instrumentation."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from context_service import __version__


def setup_tracing(service_name: str = "context-service") -> None:
    """Initialize OpenTelemetry tracing and metrics if OTEL_EXPORTER_OTLP_ENDPOINT is set."""
    import structlog

    logger = structlog.get_logger(__name__)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    logger.info("otel_setup_check", endpoint=endpoint)
    if not endpoint:
        logger.info("otel_disabled", reason="no endpoint")
        return

    from context_service.telemetry.metrics import setup_metrics

    setup_metrics(service_name)

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": __version__,
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()

    logger.info("otel_tracing_enabled", endpoint=endpoint, service=service_name)


def instrument_fastapi(app: object) -> None:
    """Instrument a FastAPI app if tracing is enabled."""
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]

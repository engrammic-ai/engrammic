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


def _is_gcp_environment() -> bool:
    """Detect if running on GCP (Cloud Run, GCE, GKE)."""
    return any(
        os.getenv(var)
        for var in ("K_SERVICE", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT")
    )


def _create_exporter(endpoint: str | None) -> OTLPSpanExporter | None:
    """Create the appropriate span exporter based on environment."""
    if _is_gcp_environment() and not endpoint:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        return CloudTraceSpanExporter()  # type: ignore[no-untyped-call,return-value]
    if endpoint:
        return OTLPSpanExporter(endpoint=endpoint, insecure=True)
    return None


def setup_tracing(service_name: str = "context-service") -> None:
    """Initialize OpenTelemetry tracing.

    Uses Cloud Trace when running on GCP, otherwise OTLP if endpoint is set.
    """
    import structlog

    logger = structlog.get_logger(__name__)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    is_gcp = _is_gcp_environment()
    otel_enabled = os.getenv("OTEL_ENABLED", "").lower() in ("true", "1")

    logger.info("otel_setup_check", endpoint=endpoint, is_gcp=is_gcp, otel_enabled=otel_enabled)

    if not endpoint and not (is_gcp and otel_enabled):
        logger.info("otel_disabled", reason="no endpoint and not GCP with OTEL_ENABLED")
        return

    exporter = _create_exporter(endpoint)
    if not exporter:
        logger.info("otel_disabled", reason="no exporter configured")
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
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()

    exporter_type = "cloud_trace" if is_gcp and not endpoint else "otlp"
    logger.info("otel_tracing_enabled", exporter=exporter_type, endpoint=endpoint, service=service_name)


def instrument_fastapi(app: object) -> None:
    """Instrument a FastAPI app if tracing is enabled."""
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]

"""OpenTelemetry tracing instrumentation."""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from context_service import __version__

P = ParamSpec("P")
R = TypeVar("R")


def traced(
    name: str | None = None,
    *,
    capture_args: list[str] | None = None,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Decorator to add OTEL tracing to async methods.

    Creates a child span that records:
    - duration_ms: execution time in milliseconds
    - error: True if an exception occurred
    - error.message: exception message on failure
    - error.type: exception class name on failure
    - Any kwargs specified in capture_args

    Args:
        name: Span name. Defaults to "{ClassName}.{method_name}" for methods
              or "{module}.{function_name}" for functions.
        capture_args: List of kwarg names to capture as span attributes.
                      Lists/dicts record their length as "{name}.count".

    Example:
        @traced()
        async def embed_query(self, query: str) -> list[float]:
            ...

        @traced(name="splade.encode", capture_args=["texts"])
        async def encode_batch(self, texts: list[str]) -> list[dict[int, float]]:
            ...
    """
    capture_args = capture_args or []

    def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        _tracer: trace.Tracer | None = None

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            nonlocal _tracer
            if _tracer is None:
                _tracer = trace.get_tracer(func.__module__)

            span_name = name
            if span_name is None:
                if args and hasattr(args[0], "__class__"):
                    span_name = f"{args[0].__class__.__name__}.{func.__name__}"
                else:
                    span_name = f"{func.__module__}.{func.__name__}"

            attributes: dict[str, Any] = {}
            for arg_name in capture_args:
                if arg_name in kwargs:
                    value = kwargs[arg_name]
                    if isinstance(value, (list, tuple, dict)):
                        attributes[f"{arg_name}.count"] = len(value)
                    else:
                        attributes[arg_name] = str(value)[:256]

            with _tracer.start_as_current_span(span_name, attributes=attributes) as span:
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e)[:512])
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    span.set_attribute("duration_ms", duration_ms)

        return wrapper

    return decorator


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

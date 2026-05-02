"""Request timing middleware for FastAPI."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from context_service.api.metrics import HTTP_REQUEST_LATENCY, HTTP_REQUESTS_TOTAL


def _resolve_route_template(request: Request) -> str:
    """Return the route template (e.g. '/health') rather than the concrete path.

    Falls back to the raw path when no matching route is found so the label
    cardinality stays bounded even for 404 requests.
    """
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            path: str = getattr(route, "path", request.url.path)
            return path
    return request.url.path


class PrometheusTimingMiddleware(BaseHTTPMiddleware):
    """Record per-endpoint HTTP latency and request counts."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip the /metrics endpoint itself to avoid self-measurement noise.
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        endpoint = _resolve_route_template(request)
        method = request.method
        status = str(response.status_code)

        HTTP_REQUEST_LATENCY.labels(method=method, endpoint=endpoint, status_code=status).observe(
            elapsed
        )
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=status).inc()

        return response


__all__ = ["PrometheusTimingMiddleware"]

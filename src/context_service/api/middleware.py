"""Request timing middleware for FastAPI."""

from __future__ import annotations

import time
from collections.abc import MutableMapping
from typing import Any

from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from context_service.api.metrics import HTTP_REQUEST_LATENCY, HTTP_REQUESTS_TOTAL


def _resolve_route_template(scope: Scope, app: ASGIApp) -> str:
    """Return the route template rather than the concrete path to bound label cardinality."""
    from starlette.routing import Router

    fallback: str = scope.get("path") or "/"
    if not isinstance(app, Router):
        return fallback
    request_scope: MutableMapping[str, Any] = dict(scope)
    for route in app.routes:
        match, _ = route.matches(request_scope)
        if match == Match.FULL:
            path = getattr(route, "path", None)
            return str(path) if path is not None else fallback
    return fallback


class PrometheusTimingMiddleware:
    """Record per-endpoint HTTP latency and request counts.

    Implemented as a raw ASGI middleware (not BaseHTTPMiddleware) so that SSE
    streaming responses pass through without being buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = "0"
        method = scope.get("method", "GET")

        async def _send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            endpoint = _resolve_route_template(scope, self.app)
            HTTP_REQUEST_LATENCY.labels(
                method=method, endpoint=endpoint, status_code=status_code
            ).observe(elapsed)
            HTTP_REQUESTS_TOTAL.labels(
                method=method, endpoint=endpoint, status_code=status_code
            ).inc()


__all__ = ["PrometheusTimingMiddleware"]

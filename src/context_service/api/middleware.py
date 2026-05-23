"""Request timing and rate limit middleware for FastAPI."""

from __future__ import annotations

import time
from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any

from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from context_service.api.metrics import HTTP_REQUEST_LATENCY, HTTP_REQUESTS_TOTAL

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient


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


SKIP_RATE_LIMIT_PATHS = frozenset({"/health", "/metrics", "/mcp", "/_mcp"})


class RateLimitMiddleware:
    """Rate limit middleware for REST endpoints.

    Implemented as raw ASGI middleware (not BaseHTTPMiddleware) to preserve
    SSE streaming behavior. Skips /health, /metrics, and /mcp paths.
    """

    def __init__(self, app: ASGIApp, redis: RedisClient | None = None) -> None:
        self.app = app
        self._redis = redis
        self._limiter: Any = None

    def _get_limiter(self) -> Any:
        if self._limiter is None and self._redis is not None:
            from context_service.api.rate_limit import RateLimiter

            self._limiter = RateLimiter(self._redis)
        return self._limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if any(path.startswith(skip) for skip in SKIP_RATE_LIMIT_PATHS):
            await self.app(scope, receive, send)
            return

        from context_service.config.settings import get_settings

        settings = get_settings()
        if not settings.security.rate_limit.enabled:
            await self.app(scope, receive, send)
            return

        limiter = self._get_limiter()
        if limiter is None:
            await self.app(scope, receive, send)
            return

        from context_service.api.rate_limit import RateLimitCategory, RateLimitExceeded

        org_id = settings.dev_org_id if not settings.auth_enabled else "unknown"
        user_id = settings.dev_user_id if not settings.auth_enabled else "unknown"

        category = RateLimitCategory.ADMIN if path.startswith("/admin") else RateLimitCategory.REST

        rate_headers: Any = None
        try:
            rate_headers = await limiter.check(
                org_id=org_id,
                user_id=user_id,
                category=category,
                is_dev=not settings.auth_enabled,
            )
        except RateLimitExceeded as exc:
            response_body = (
                f'{{"error": "rate_limit_exceeded", "retry_after": {exc.retry_after}}}'.encode()
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(exc.retry_after).encode()),
                        (b"x-ratelimit-limit", str(exc.limit).encode()),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": response_body,
                }
            )
            return

        async def _send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start" and rate_headers:
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-ratelimit-limit", str(rate_headers.limit).encode()),
                        (b"x-ratelimit-remaining", str(rate_headers.remaining).encode()),
                        (b"x-ratelimit-reset", str(rate_headers.reset).encode()),
                        (b"x-ratelimit-policy", rate_headers.policy.encode()),
                    ]
                )
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, _send_with_headers)


__all__ = ["PrometheusTimingMiddleware", "RateLimitMiddleware", "SKIP_RATE_LIMIT_PATHS"]

"""Rate limiting decorator for MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from context_service.api.rate_limit import RateLimiter, RateLimitHeaders
from context_service.mcp.server import get_mcp_auth_context

if TYPE_CHECKING:
    from context_service.auth.context import AuthContext
    from context_service.stores.redis import RedisClient

_rate_limiter: RateLimiter | None = None

F = TypeVar("F", bound=Callable[..., Any])


def set_mcp_rate_limiter(redis: RedisClient) -> None:
    """Set the rate limiter for MCP tools. Called at app startup."""
    global _rate_limiter
    _rate_limiter = RateLimiter(redis)


async def _check_rate_limit(auth: AuthContext, tool_name: str) -> RateLimitHeaders:
    """Check rate limit. Returns headers or raises RateLimitExceeded."""
    if _rate_limiter is None:
        return RateLimitHeaders(
            limit=9999,
            remaining=9999,
            reset=0,
            policy=f"unlimited/{tool_name}",
        )
    return await _rate_limiter.check_mcp(auth, tool_name)


def rate_limited(tool_name: str) -> Callable[[F], F]:
    """Decorator that checks rate limit before executing an MCP tool."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            auth = await get_mcp_auth_context()
            await _check_rate_limit(auth, tool_name)
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["rate_limited", "set_mcp_rate_limiter"]

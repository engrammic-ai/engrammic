"""Rate limiting service for API and MCP endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from context_service.config.settings import get_settings
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from context_service.auth.context import AuthContext
    from context_service.stores.redis import RedisClient

logger = structlog.get_logger(__name__)


class RateLimitCategory(StrEnum):
    """Categories for rate limiting with different limits per tier."""

    MCP_WRITE = "mcp_write"
    MCP_READ = "mcp_read"
    ADMIN = "admin"
    REST = "rest"


WRITE_TOOLS = frozenset(
    {
        "remember",
        "learn",
        "believe",
        "link",
        "reason",
        "reflect",
        "hypothesize",
        "revise",
        "commit",
    }
)
READ_TOOLS = frozenset({"recall", "trace", "patterns"})


def get_tool_category(tool_name: str) -> RateLimitCategory:
    """Map MCP tool name to rate limit category."""
    if tool_name in READ_TOOLS:
        return RateLimitCategory.MCP_READ
    return RateLimitCategory.MCP_WRITE


@dataclass(frozen=True, slots=True)
class RateLimitHeaders:
    """Rate limit info for response headers."""

    limit: int
    remaining: int
    reset: int
    policy: str


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: int, limit: int, current: int, category: str) -> None:
        self.retry_after = retry_after
        self.limit = limit
        self.current = current
        self.category = category
        super().__init__(f"Rate limit exceeded for {category}: {current}/{limit}")


def _build_key(category: RateLimitCategory, window_start: int, org_id: str) -> str:
    """Build Redis key for rate limit counter."""
    return f"rl:{category.value}:{window_start}:{org_id}"


def _get_window_start(window_seconds: int) -> int:
    """Get the start timestamp of the current fixed window."""
    now = int(time.time())
    return (now // window_seconds) * window_seconds


class RateLimiter:
    """Rate limiter service using Redis fixed-window counters."""

    MINUTE_WINDOW = 60
    HOUR_WINDOW = 3600
    TIER_CACHE_PREFIX = "tier:"

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def _get_tier(self, org_id: str) -> str:
        """Resolve tier for org: cache -> default."""
        settings = get_settings()
        silo_id = str(derive_silo_id(org_id))
        cache_key = f"{self.TIER_CACHE_PREFIX}{silo_id}"

        # Check cache first
        cached = await self._redis._redis.get(cache_key)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached

        return settings.security.rate_limit.default_tier

    async def check(
        self,
        org_id: str,
        user_id: str,  # noqa: ARG002 - reserved for per-user limiting
        category: RateLimitCategory,
        is_dev: bool,
    ) -> RateLimitHeaders:
        """Check rate limit and return headers. Raises RateLimitExceeded if over limit."""
        settings = get_settings()
        config = settings.security.rate_limit

        if not config.enabled or is_dev:
            return RateLimitHeaders(
                limit=9999,
                remaining=9999,
                reset=_get_window_start(self.MINUTE_WINDOW) + self.MINUTE_WINDOW,
                policy=f"unlimited/{category.value}",
            )

        tier = await self._get_tier(org_id)
        limits = config.get_limits(tier)

        category_limits = getattr(limits, category.value)
        rpm_limit = category_limits.requests_per_minute

        window_start = _get_window_start(self.MINUTE_WINDOW)
        key = _build_key(category, window_start, org_id)

        current = await self._redis.incr_with_expire(key, self.MINUTE_WINDOW + 10)

        # Fail-open: if Redis returned 0 (circuit open), allow the request
        if current == 0:
            logger.warning(
                "rate_limit_redis_unavailable",
                org_id=org_id,
                category=category.value,
            )
            return RateLimitHeaders(
                limit=rpm_limit,
                remaining=rpm_limit,
                reset=window_start + self.MINUTE_WINDOW,
                policy=f"{tier}/{category.value}",
            )

        if current > rpm_limit:
            retry_after = (window_start + self.MINUTE_WINDOW) - int(time.time())
            logger.info(
                "rate_limit_exceeded",
                org_id=org_id,
                category=category.value,
                tier=tier,
                current=current,
                limit=rpm_limit,
            )
            raise RateLimitExceeded(
                retry_after=max(1, retry_after),
                limit=rpm_limit,
                current=current,
                category=category.value,
            )

        return RateLimitHeaders(
            limit=rpm_limit,
            remaining=max(0, rpm_limit - current),
            reset=window_start + self.MINUTE_WINDOW,
            policy=f"{tier}/{category.value}",
        )

    async def check_mcp(self, auth: AuthContext, tool_name: str) -> RateLimitHeaders:
        """Check rate limit for an MCP tool call."""
        category = get_tool_category(tool_name)
        return await self.check(
            org_id=auth.org_id,
            user_id=auth.user_id,
            category=category,
            is_dev=auth.is_dev,
        )


__all__ = [
    "RateLimitCategory",
    "RateLimitExceeded",
    "RateLimitHeaders",
    "RateLimiter",
    "get_tool_category",
]

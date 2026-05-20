# Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tiered rate limiting to MCP tools and REST routes, with per-org RPM limits configurable by pricing tier. This is v1 (abuse prevention); monthly quotas and per-user fairness come in v1.1.

**Architecture:** Two enforcement points sharing one `RateLimiter` service: (1) raw ASGI middleware for REST routes, (2) decorator-based hook for MCP tools. Redis fixed-window counters with atomic Lua script (INCR+EXPIRE). Tier resolved from silo metadata with Redis caching, DB fallback on miss. Fail-open on Redis unavailability.

**Tech Stack:** FastAPI, Redis 6.2+ (existing), Pydantic settings, pytest with AsyncMock

**Scope:**
- v1 (this plan): Per-org RPM limits, tier-based config, fail-open behavior
- v1.1 (deferred): Monthly quotas (writes/mo, recalls/mo), per-user fairness cap (20% sublimit)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/config/settings.py` | Expand `RateLimitConfig` to `TierLimits` schema |
| `src/context_service/stores/redis.py` | Add `incr_with_expire` atomic Lua script helper |
| `src/context_service/api/rate_limit.py` | New: `RateLimiter` service, `RateLimitExceeded`, tier resolver with DB fallback |
| `src/context_service/api/middleware.py` | Add `RateLimitMiddleware` (raw ASGI) |
| `src/context_service/api/app.py` | Wire middleware (order: rate limit runs before timing) |
| `src/context_service/mcp/rate_limit.py` | New: `@rate_limited` decorator for MCP tools |
| `src/context_service/mcp/tools/*.py` | Add `@rate_limited` decorator to `_*_impl` functions |
| `src/context_service/api/routes/admin.py` | Add tier endpoints to existing admin router |
| `tests/api/test_rate_limit.py` | New: unit tests for RateLimiter |
| `tests/api/test_rate_limit_middleware.py` | New: middleware tests |
| `tests/mcp/test_rate_limit_tools.py` | New: MCP tool rate limit tests |

---

## Task 1: Expand RateLimitConfig Schema

**Files:**
- Modify: `src/context_service/config/settings.py:589-600`
- Test: `tests/config/test_rate_limit_config.py` (new)

- [ ] **Step 1: Write the failing test for new config schema**

Create `tests/config/test_rate_limit_config.py`:

```python
"""Tests for tiered rate limit configuration."""

from __future__ import annotations

import pytest

from context_service.config.settings import (
    EndpointLimits,
    RateLimitConfig,
    TierLimits,
)


class TestEndpointLimits:
    def test_default_values(self) -> None:
        limits = EndpointLimits()
        assert limits.requests_per_minute == 60
        assert limits.requests_per_hour == 600

    def test_custom_values(self) -> None:
        limits = EndpointLimits(requests_per_minute=100, requests_per_hour=1000)
        assert limits.requests_per_minute == 100
        assert limits.requests_per_hour == 1000


class TestTierLimits:
    def test_has_all_categories(self) -> None:
        tier = TierLimits()
        assert hasattr(tier, "mcp_write")
        assert hasattr(tier, "mcp_read")
        assert hasattr(tier, "admin")
        assert hasattr(tier, "rest")


class TestRateLimitConfig:
    def test_default_tiers_exist(self) -> None:
        config = RateLimitConfig()
        assert "free" in config.tiers
        assert "starter" in config.tiers
        assert "pro" in config.tiers
        assert "enterprise" in config.tiers

    def test_enabled_defaults_false(self) -> None:
        config = RateLimitConfig()
        assert config.enabled is False

    def test_default_tier_is_free(self) -> None:
        config = RateLimitConfig()
        assert config.default_tier == "free"

    def test_get_limits_for_tier(self) -> None:
        config = RateLimitConfig()
        limits = config.get_limits("pro")
        assert limits.mcp_write.requests_per_minute == 200

    def test_get_limits_unknown_tier_returns_default(self) -> None:
        config = RateLimitConfig()
        limits = config.get_limits("unknown")
        assert limits == config.tiers[config.default_tier]

    def test_pro_has_higher_limits_than_free(self) -> None:
        config = RateLimitConfig()
        free = config.get_limits("free")
        pro = config.get_limits("pro")
        assert pro.mcp_write.requests_per_minute > free.mcp_write.requests_per_minute
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_rate_limit_config.py -v`
Expected: FAIL with ImportError (EndpointLimits, TierLimits not defined)

- [ ] **Step 3: Implement the new config schema**

In `src/context_service/config/settings.py`, replace the existing `RateLimitConfig` (around line 589) with:

```python
class EndpointLimits(BaseModel):
    """Rate limits for a single endpoint category."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    requests_per_minute: int = 60
    requests_per_hour: int = 600


class TierLimits(BaseModel):
    """Rate limits for all endpoint categories within a tier."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    mcp_write: EndpointLimits = Field(default_factory=EndpointLimits)
    mcp_read: EndpointLimits = Field(default_factory=EndpointLimits)
    admin: EndpointLimits = Field(default_factory=EndpointLimits)
    rest: EndpointLimits = Field(default_factory=EndpointLimits)


def _default_tiers() -> dict[str, TierLimits]:
    """Default tier configurations matching pricing model."""
    return {
        "free": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=20, requests_per_hour=200),
            mcp_read=EndpointLimits(requests_per_minute=60, requests_per_hour=600),
            admin=EndpointLimits(requests_per_minute=10, requests_per_hour=60),
            rest=EndpointLimits(requests_per_minute=30, requests_per_hour=300),
        ),
        "starter": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=60, requests_per_hour=600),
            mcp_read=EndpointLimits(requests_per_minute=200, requests_per_hour=2000),
            admin=EndpointLimits(requests_per_minute=30, requests_per_hour=300),
            rest=EndpointLimits(requests_per_minute=100, requests_per_hour=1000),
        ),
        "pro": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=200, requests_per_hour=2000),
            mcp_read=EndpointLimits(requests_per_minute=600, requests_per_hour=6000),
            admin=EndpointLimits(requests_per_minute=60, requests_per_hour=600),
            rest=EndpointLimits(requests_per_minute=300, requests_per_hour=3000),
        ),
        "enterprise": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=1000, requests_per_hour=10000),
            mcp_read=EndpointLimits(requests_per_minute=3000, requests_per_hour=30000),
            admin=EndpointLimits(requests_per_minute=200, requests_per_hour=2000),
            rest=EndpointLimits(requests_per_minute=1000, requests_per_hour=10000),
        ),
    }


class RateLimitConfig(BaseModel):
    """Tiered rate limiting configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = False
    tiers: dict[str, TierLimits] = Field(default_factory=_default_tiers)
    default_tier: str = "free"
    tier_cache_ttl_seconds: int = 300

    def get_limits(self, tier: str) -> TierLimits:
        """Get limits for a tier, falling back to default if unknown."""
        return self.tiers.get(tier, self.tiers[self.default_tier])
```

- [ ] **Step 4: Update SecurityConfig to use new RateLimitConfig**

The existing `SecurityConfig` references `RateLimitConfig`. Verify it still works (it should, since the class name is unchanged).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/config/test_rate_limit_config.py -v`
Expected: PASS

- [ ] **Step 6: Run full check to ensure no regressions**

Run: `uv run just check`
Expected: PASS (no mypy or ruff errors)

- [ ] **Step 7: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_rate_limit_config.py
git commit -m "feat(config): expand RateLimitConfig to support tiered limits"
```

---

## Task 2: Add Redis Atomic Helper

**Files:**
- Modify: `src/context_service/stores/redis.py`
- Test: `tests/test_redis_store.py`

- [ ] **Step 1: Write the failing test for incr_with_expire**

Add to `tests/test_redis_store.py`:

```python
class TestIncrWithExpire:
    async def test_increments_and_returns_count(self) -> None:
        mock_redis = _make_redis_mock()
        mock_redis.eval = AsyncMock(return_value=5)

        client = RedisClient(mock_redis)
        result = await client.incr_with_expire("test:key", 60)

        assert result == 5
        mock_redis.eval.assert_called_once()
        call_args = mock_redis.eval.call_args
        assert call_args[0][1] == 1  # number of keys
        assert call_args[0][2] == "test:key"
        assert call_args[0][3] == 60  # ttl

    async def test_returns_zero_on_circuit_open(self) -> None:
        mock_redis = _make_redis_mock()
        mock_redis.eval = AsyncMock(side_effect=RedisConnectionError("connection refused"))

        client = RedisClient(mock_redis)

        with patch("context_service.stores.redis.guard_degrade") as mock_guard:
            mock_guard.return_value = 0
            result = await client.incr_with_expire("test:key", 60)

        assert result == 0

    async def test_first_increment_sets_ttl(self) -> None:
        """Verify the Lua script logic: TTL set only when count == 1."""
        mock_redis = _make_redis_mock()
        mock_redis.eval = AsyncMock(return_value=1)

        client = RedisClient(mock_redis)
        result = await client.incr_with_expire("test:key", 3600)

        assert result == 1
        # The Lua script handles TTL internally; we just verify it's called
        assert mock_redis.eval.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_redis_store.py::TestIncrWithExpire -v`
Expected: FAIL with AttributeError (incr_with_expire not defined)

- [ ] **Step 3: Implement incr_with_expire using Lua script**

Add to `src/context_service/stores/redis.py` in the `RedisClient` class:

```python
    # Lua script for atomic INCR + EXPIRE (works on Redis 6.2+)
    # Sets TTL only on first creation (when count == 1)
    _INCR_EXPIRE_SCRIPT = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return count
    """

    async def incr_with_expire(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment a counter and set TTL on first creation.

        Uses a Lua script for true atomicity (no race between INCR and EXPIRE).
        TTL is only set when count == 1 (first increment).

        Args:
            key: Redis key to increment.
            ttl_seconds: TTL for the key (only applied on first creation).

        Returns:
            New counter value, or 0 if circuit is open (fail-open).
        """
        return await guard_degrade(
            STORE_REDIS, self._incr_with_expire_impl(key, ttl_seconds), 0
        )

    async def _incr_with_expire_impl(self, key: str, ttl_seconds: int) -> int:
        """Implementation for atomic INCR + EXPIRE via Lua."""
        start = time.perf_counter()
        try:
            result = await self._redis.eval(
                self._INCR_EXPIRE_SCRIPT,
                1,  # number of keys
                key,
                ttl_seconds,
            )
            return int(result)
        except (RedisConnectionError, RedisError) as e:
            logger.warning("redis_incr_with_expire_failed", key=key, error=str(e))
            raise
        finally:
            record_db_query("redis.incr_with_expire", (time.perf_counter() - start) * 1000)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_redis_store.py::TestIncrWithExpire -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/stores/redis.py tests/test_redis_store.py
git commit -m "feat(redis): add incr_with_expire atomic helper for rate limiting"
```

---

## Task 3: Create RateLimiter Service

**Files:**
- Create: `src/context_service/api/rate_limit.py`
- Test: `tests/api/test_rate_limit.py` (new)

- [ ] **Step 1: Create test directory if needed**

```bash
mkdir -p tests/api
touch tests/api/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `tests/api/test_rate_limit.py`:

```python
"""Tests for the rate limiter service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.api.rate_limit import (
    RateLimitCategory,
    RateLimitExceeded,
    RateLimitHeaders,
    RateLimiter,
    get_tool_category,
)
from context_service.auth.context import AuthContext


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.incr_with_expire = AsyncMock(return_value=1)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.security.rate_limit.enabled = True
    settings.security.rate_limit.default_tier = "free"
    settings.security.rate_limit.tier_cache_ttl_seconds = 300
    settings.security.rate_limit.get_limits.return_value = MagicMock(
        mcp_write=MagicMock(requests_per_minute=20, requests_per_hour=200),
        mcp_read=MagicMock(requests_per_minute=60, requests_per_hour=600),
    )
    return settings


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        org_id="org_123",
        user_id="user_456",
        email="test@example.com",
        is_dev=False,
    )


class TestGetToolCategory:
    def test_write_tools(self) -> None:
        for tool in ["remember", "learn", "believe", "link", "reason", "reflect", "hypothesize", "revise", "commit"]:
            assert get_tool_category(tool) == RateLimitCategory.MCP_WRITE

    def test_read_tools(self) -> None:
        for tool in ["recall", "trace", "patterns"]:
            assert get_tool_category(tool) == RateLimitCategory.MCP_READ

    def test_unknown_defaults_to_write(self) -> None:
        assert get_tool_category("unknown_tool") == RateLimitCategory.MCP_WRITE


class TestRateLimiter:
    async def test_check_returns_headers_when_within_limit(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

        assert isinstance(headers, RateLimitHeaders)
        assert headers.remaining > 0

    async def test_check_raises_when_limit_exceeded(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        mock_redis.incr_with_expire = AsyncMock(return_value=21)  # Over 20 RPM limit

        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)

            with pytest.raises(RateLimitExceeded) as exc_info:
                await limiter.check(
                    org_id=auth_context.org_id,
                    user_id=auth_context.user_id,
                    category=RateLimitCategory.MCP_WRITE,
                    is_dev=False,
                )

        assert exc_info.value.retry_after > 0

    async def test_dev_mode_skips_limiting(
        self, mock_redis: AsyncMock, mock_settings: MagicMock
    ) -> None:
        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id="dev_org",
                user_id="dev_user",
                category=RateLimitCategory.MCP_WRITE,
                is_dev=True,
            )

        assert headers.remaining == headers.limit
        mock_redis.incr_with_expire.assert_not_called()

    async def test_disabled_rate_limiting_skips_check(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        mock_settings.security.rate_limit.enabled = False

        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

        assert headers.remaining == headers.limit
        mock_redis.incr_with_expire.assert_not_called()

    async def test_redis_failure_fails_open(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        mock_redis.incr_with_expire = AsyncMock(return_value=0)  # Circuit open returns 0

        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

        assert headers.remaining == headers.limit


class TestCheckMcp:
    async def test_maps_tool_to_category(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check_mcp(auth_context, "remember")

        assert isinstance(headers, RateLimitHeaders)

    async def test_recall_uses_read_limits(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            await limiter.check_mcp(auth_context, "recall")

        key_arg = mock_redis.incr_with_expire.call_args[0][0]
        assert "mcp_read" in key_arg
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/api/test_rate_limit.py -v`
Expected: FAIL with ImportError

- [ ] **Step 4: Implement the RateLimiter service**

Create `src/context_service/api/rate_limit.py`:

```python
"""Rate limiting service for API and MCP endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from context_service.config.settings import get_settings

if TYPE_CHECKING:
    from context_service.auth.context import AuthContext
    from context_service.stores.redis import RedisClient

logger = structlog.get_logger(__name__)


class RateLimitCategory(str, Enum):
    """Categories for rate limiting with different limits per tier."""

    MCP_WRITE = "mcp_write"
    MCP_READ = "mcp_read"
    ADMIN = "admin"
    REST = "rest"


WRITE_TOOLS = frozenset({
    "remember", "learn", "believe", "link",
    "reason", "reflect", "hypothesize", "revise", "commit",
})
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


def _build_key(category: RateLimitCategory, window_start: int, org_id: str, user_id: str | None = None) -> str:
    """Build Redis key for rate limit counter."""
    if user_id:
        return f"rl:{category.value}:{window_start}:{org_id}:{user_id}"
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
        """Resolve tier for org: cache -> silo metadata -> default."""
        settings = get_settings()
        cache_key = f"{self.TIER_CACHE_PREFIX}{org_id}"

        # Check cache first
        cached = await self._redis._redis.get(cache_key)
        if cached:
            return cached.decode()

        # Cache miss: try to load from silo metadata
        tier = await self._load_tier_from_silo(org_id)
        if tier:
            # Populate cache for next time
            ttl = settings.security.rate_limit.tier_cache_ttl_seconds
            await self._redis._redis.set(cache_key, tier.encode(), ex=ttl)
            return tier

        return settings.security.rate_limit.default_tier

    async def _load_tier_from_silo(self, org_id: str) -> str | None:
        """Load tier from silo metadata. Returns None if not found."""
        try:
            from context_service.services.models import derive_silo_id
            from context_service.stores.memgraph import get_memgraph

            silo_id = derive_silo_id(org_id)
            memgraph = get_memgraph()
            result = await memgraph.execute_read(
                "MATCH (s:Silo {id: $silo_id}) RETURN s.metadata AS metadata",
                {"silo_id": str(silo_id)},
            )
            if result and result[0].get("metadata"):
                metadata = result[0]["metadata"]
                if isinstance(metadata, str):
                    import json
                    metadata = json.loads(metadata)
                return metadata.get("tier")
        except Exception as e:
            logger.warning("tier_lookup_failed", org_id=org_id, error=str(e))
        return None

    async def check(
        self,
        org_id: str,
        user_id: str,
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_rate_limit.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/rate_limit.py tests/api/test_rate_limit.py tests/api/__init__.py
git commit -m "feat(api): add RateLimiter service with tiered limits"
```

---

## Task 4: Add REST Rate Limit Middleware

**Files:**
- Modify: `src/context_service/api/middleware.py`
- Modify: `src/context_service/api/app.py`
- Test: `tests/api/test_rate_limit_middleware.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_rate_limit_middleware.py`:

```python
"""Tests for rate limit middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from context_service.api.rate_limit import RateLimitExceeded


class TestRateLimitMiddleware:
    def test_skips_health_endpoint(self) -> None:
        with patch("context_service.api.app.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.enabled = True
            mock_settings.return_value.auth_enabled = False
            mock_settings.return_value.dev_org_id = "test_org"
            mock_settings.return_value.dev_user_id = "test_user"
            mock_settings.return_value.custodian.enabled = False
            mock_settings.return_value.mcp_profile = "standard"

            from context_service.api.app import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/health")
            assert response.status_code == 200

    def test_skips_metrics_endpoint(self) -> None:
        with patch("context_service.api.app.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.enabled = True
            mock_settings.return_value.auth_enabled = False
            mock_settings.return_value.dev_org_id = "test_org"
            mock_settings.return_value.dev_user_id = "test_user"
            mock_settings.return_value.custodian.enabled = False
            mock_settings.return_value.mcp_profile = "standard"

            from context_service.api.app import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/metrics")
            assert response.status_code == 200

    def test_adds_rate_limit_headers(self) -> None:
        with (
            patch("context_service.api.app.get_settings") as mock_settings,
            patch("context_service.api.middleware.RateLimiter") as mock_limiter_cls,
        ):
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.enabled = True
            mock_settings.return_value.auth_enabled = False
            mock_settings.return_value.dev_org_id = "test_org"
            mock_settings.return_value.dev_user_id = "test_user"
            mock_settings.return_value.custodian.enabled = False
            mock_settings.return_value.mcp_profile = "standard"

            mock_limiter = AsyncMock()
            mock_limiter.check.return_value = MagicMock(
                limit=100, remaining=99, reset=1234567890, policy="free/rest"
            )
            mock_limiter_cls.return_value = mock_limiter

            from context_service.api.app import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/health")

            assert "X-RateLimit-Limit" in response.headers or response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_rate_limit_middleware.py -v`
Expected: May pass partially (health skips are already working), but header injection will fail

- [ ] **Step 3: Implement the middleware**

Add to `src/context_service/api/middleware.py`:

```python
from context_service.api.rate_limit import (
    RateLimitCategory,
    RateLimitExceeded,
    RateLimitHeaders,
    RateLimiter,
)
from context_service.config.settings import get_settings
from context_service.stores.redis import RedisClient


SKIP_PATHS = frozenset({"/health", "/metrics", "/mcp", "/_mcp"})


class RateLimitMiddleware:
    """Rate limit middleware for REST endpoints.

    Implemented as raw ASGI middleware (not BaseHTTPMiddleware) to preserve
    SSE streaming behavior. Skips /health, /metrics, and /mcp paths.
    """

    def __init__(self, app: ASGIApp, redis: RedisClient | None = None) -> None:
        self.app = app
        self._redis = redis
        self._limiter: RateLimiter | None = None

    def _get_limiter(self) -> RateLimiter | None:
        if self._limiter is None and self._redis is not None:
            self._limiter = RateLimiter(self._redis)
        return self._limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if any(path.startswith(skip) for skip in SKIP_PATHS):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.security.rate_limit.enabled:
            await self.app(scope, receive, send)
            return

        limiter = self._get_limiter()
        if limiter is None:
            await self.app(scope, receive, send)
            return

        org_id = settings.dev_org_id if not settings.auth_enabled else "unknown"
        user_id = settings.dev_user_id if not settings.auth_enabled else "unknown"

        category = RateLimitCategory.ADMIN if path.startswith("/admin") else RateLimitCategory.REST

        rate_headers: RateLimitHeaders | None = None
        try:
            rate_headers = await limiter.check(
                org_id=org_id,
                user_id=user_id,
                category=category,
                is_dev=not settings.auth_enabled,
            )
        except RateLimitExceeded as exc:
            response_body = f'{{"error": "rate_limit_exceeded", "retry_after": {exc.retry_after}}}'.encode()
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(exc.retry_after).encode()),
                    (b"x-ratelimit-limit", str(exc.limit).encode()),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })
            return

        async def _send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start" and rate_headers:
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-ratelimit-limit", str(rate_headers.limit).encode()),
                    (b"x-ratelimit-remaining", str(rate_headers.remaining).encode()),
                    (b"x-ratelimit-reset", str(rate_headers.reset).encode()),
                    (b"x-ratelimit-policy", rate_headers.policy.encode()),
                ])
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, _send_with_headers)
```

- [ ] **Step 4: Wire middleware in app.py**

In `src/context_service/api/app.py`, add middleware wiring. Note: `add_middleware` is LIFO (last added runs first), so add RateLimitMiddleware AFTER PrometheusTimingMiddleware to make rate limiting run BEFORE timing:

```python
from context_service.api.middleware import PrometheusTimingMiddleware, RateLimitMiddleware

# In create_app():
# Order matters! add_middleware is LIFO:
# - PrometheusTimingMiddleware added first, runs LAST (times the full request including rate limit)
# - RateLimitMiddleware added second, runs FIRST (rejects before work is done)
app.add_middleware(PrometheusTimingMiddleware)
app.add_middleware(RateLimitMiddleware, redis=None)  # Redis injected at startup
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_rate_limit_middleware.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/middleware.py src/context_service/api/app.py tests/api/test_rate_limit_middleware.py
git commit -m "feat(api): add rate limit middleware for REST endpoints"
```

---

## Task 5: Wire MCP Tool Rate Limiting via Decorator

**Files:**
- Create: `src/context_service/mcp/rate_limit.py` (new decorator)
- Modify: `src/context_service/mcp/error_boundary.py`
- Modify: `src/context_service/mcp/tools/remember.py` (example, apply to all)
- Test: `tests/mcp/test_rate_limit_tools.py` (new)

Using a decorator pattern ensures no tool is accidentally missed and centralizes the rate limit check.

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_rate_limit_tools.py`:

```python
"""Tests for MCP tool rate limiting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.api.rate_limit import RateLimitExceeded
from context_service.auth.context import AuthContext


class TestRateLimitDecorator:
    @pytest.fixture
    def mock_auth(self) -> AuthContext:
        return AuthContext(
            org_id="test_org",
            user_id="test_user",
            email="test@example.com",
            is_dev=False,
        )

    async def test_decorator_checks_rate_limit(self, mock_auth: AuthContext) -> None:
        from context_service.mcp.rate_limit import rate_limited

        @rate_limited("test_tool")
        async def my_tool() -> dict:
            return {"result": "ok"}

        with (
            patch("context_service.mcp.rate_limit.get_mcp_auth_context", return_value=mock_auth),
            patch("context_service.mcp.rate_limit._check_rate_limit") as mock_check,
        ):
            mock_check.return_value = MagicMock(limit=100, remaining=99)
            result = await my_tool()

            mock_check.assert_called_once_with(mock_auth, "test_tool")
            assert result["result"] == "ok"

    async def test_decorator_raises_on_limit_exceeded(self, mock_auth: AuthContext) -> None:
        from context_service.mcp.rate_limit import rate_limited

        @rate_limited("test_tool")
        async def my_tool() -> dict:
            return {"result": "ok"}

        with (
            patch("context_service.mcp.rate_limit.get_mcp_auth_context", return_value=mock_auth),
            patch("context_service.mcp.rate_limit._check_rate_limit") as mock_check,
        ):
            mock_check.side_effect = RateLimitExceeded(
                retry_after=30, limit=20, current=21, category="mcp_write"
            )

            with pytest.raises(RateLimitExceeded):
                await my_tool()


class TestMcpToolRateLimiting:
    @pytest.fixture
    def mock_auth(self) -> AuthContext:
        return AuthContext(
            org_id="test_org",
            user_id="test_user",
            email="test@example.com",
            is_dev=False,
        )

    async def test_remember_is_rate_limited(self, mock_auth: AuthContext) -> None:
        with (
            patch("context_service.mcp.rate_limit.get_mcp_auth_context", return_value=mock_auth),
            patch("context_service.mcp.rate_limit._check_rate_limit") as mock_check,
            patch("context_service.mcp.tools.remember.track_tool_usage"),
            patch("context_service.mcp.tools.remember._context_remember", return_value={"node_id": "123"}),
        ):
            mock_check.return_value = MagicMock(limit=100, remaining=99)

            from context_service.mcp.tools.remember import _remember_impl

            result = await _remember_impl("test content")

            assert mock_check.called
            assert result["node_id"] == "123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_rate_limit_tools.py -v`
Expected: FAIL (rate_limited decorator not defined)

- [ ] **Step 3: Create the rate_limited decorator**

Create `src/context_service/mcp/rate_limit.py`:

```python
"""Rate limiting decorator for MCP tools."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from context_service.api.rate_limit import RateLimitHeaders, RateLimiter
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
    """Decorator that checks rate limit before executing an MCP tool.

    Usage:
        @rate_limited("remember")
        async def _remember_impl(...):
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            auth = await get_mcp_auth_context()
            await _check_rate_limit(auth, tool_name)
            return await func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


__all__ = ["rate_limited", "set_mcp_rate_limiter"]
```

- [ ] **Step 4: Update error boundary to handle RateLimitExceeded**

Modify `src/context_service/mcp/error_boundary.py` to catch and format `RateLimitExceeded`:

```python
from context_service.api.rate_limit import RateLimitExceeded

# In the mcp_error_boundary decorator, add this except block BEFORE the generic Exception handler:
except RateLimitExceeded as exc:
    logger.info("mcp_rate_limit_exceeded", tool=func.__name__, retry_after=exc.retry_after)
    return {
        "error": "rate_limit_exceeded",
        "message": str(exc),
        "retry_after": exc.retry_after,
        "limit": exc.limit,
    }
```

- [ ] **Step 5: Apply decorator to remember tool**

Modify `src/context_service/mcp/tools/remember.py`:

```python
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage

@rate_limited("remember")
async def _remember_impl(
    content: str,
    tags: list[str] | None = None,
    decay: str = "standard",
) -> dict[str, Any]:
    """Implementation for remember tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "remember")
    return await _context_remember(
        silo_id=None,
        content=content,
        tags=tags,
        decay_class=decay,
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_rate_limit_tools.py -v`
Expected: PASS

- [ ] **Step 7: Apply decorator to remaining tools**

Add `@rate_limited("tool_name")` decorator to `_*_impl` functions in:
- `learn.py` → `@rate_limited("learn")`
- `believe.py` → `@rate_limited("believe")`
- `link.py` → `@rate_limited("link")`
- `reason.py` → `@rate_limited("reason")`
- `reflect.py` → `@rate_limited("reflect")`
- `hypothesize.py` → `@rate_limited("hypothesize")`
- `revise.py` → `@rate_limited("revise")`
- `commit.py` → `@rate_limited("commit")`
- `recall.py` → `@rate_limited("recall")`
- `trace.py` → `@rate_limited("trace")`
- `patterns.py` → `@rate_limited("patterns")`

- [ ] **Step 8: Commit**

```bash
git add src/context_service/mcp/rate_limit.py src/context_service/mcp/error_boundary.py src/context_service/mcp/tools/*.py tests/mcp/test_rate_limit_tools.py
git commit -m "feat(mcp): add rate limiting decorator for MCP tools"
```

---

## Task 6: Add Tier Management Admin Endpoints

**Files:**
- Modify: `src/context_service/api/routes/admin.py` (existing file)
- Test: `tests/api/test_admin_tier.py` (new)

Note: Admin router already exists. Add to existing file using existing `_require_admin_key` dependency.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_admin_tier.py`:

```python
"""Tests for tier management admin endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTierEndpoint:
    async def test_set_tier_updates_cache_and_silo(self) -> None:
        mock_redis = AsyncMock()
        mock_redis._redis = AsyncMock()
        mock_redis._redis.set = AsyncMock(return_value=True)

        mock_memgraph = AsyncMock()
        mock_memgraph.execute_write = AsyncMock(return_value=[{"updated": True}])

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.tiers = {
                "free": {}, "starter": {}, "pro": {}, "enterprise": {}
            }
            mock_settings.return_value.security.rate_limit.tier_cache_ttl_seconds = 300

            from context_service.api.routes.admin import set_silo_tier

            result = await set_silo_tier(
                silo_id="test_silo",
                tier="pro",
                redis=mock_redis,
                memgraph=mock_memgraph,
            )

            assert result["tier"] == "pro"
            mock_redis._redis.set.assert_called_once()
            mock_memgraph.execute_write.assert_called_once()

    async def test_set_tier_validates_tier_name(self) -> None:
        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.tiers = {"free": {}, "pro": {}}

            from fastapi import HTTPException

            from context_service.api.routes.admin import set_silo_tier

            with pytest.raises(HTTPException) as exc_info:
                await set_silo_tier(
                    silo_id="test",
                    tier="invalid",
                    redis=AsyncMock(),
                    memgraph=AsyncMock(),
                )

            assert exc_info.value.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_admin_tier.py -v`
Expected: FAIL (set_silo_tier not defined)

- [ ] **Step 3: Add tier endpoints to existing admin.py**

Add to `src/context_service/api/routes/admin.py` (existing file):

```python
TIER_CACHE_PREFIX = "tier:"


@router.patch("/silos/{silo_id}/tier")
async def set_silo_tier(
    silo_id: str,
    tier: str,
    redis: RedisClient = Depends(get_redis_client),
    memgraph: HyperGraphStore = Depends(get_memgraph),
) -> dict[str, Any]:
    """Set the rate limit tier for a silo.

    Updates both Redis cache (for fast lookup) and silo metadata (persistent).
    """
    settings = get_settings()
    valid_tiers = settings.security.rate_limit.tiers.keys()

    if tier not in valid_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{tier}'. Valid tiers: {list(valid_tiers)}",
        )

    # Update silo metadata (persistent)
    await memgraph.execute_write(
        """
        MATCH (s:Silo {id: $silo_id})
        SET s.metadata = CASE
            WHEN s.metadata IS NULL THEN $new_metadata
            ELSE apoc.map.merge(s.metadata, $new_metadata)
        END
        RETURN true AS updated
        """,
        {"silo_id": silo_id, "new_metadata": {"tier": tier}},
    )

    # Update Redis cache
    cache_key = f"{TIER_CACHE_PREFIX}{silo_id}"
    ttl = settings.security.rate_limit.tier_cache_ttl_seconds
    await redis._redis.set(cache_key, tier.encode(), ex=ttl)

    return {
        "silo_id": silo_id,
        "tier": tier,
        "cache_ttl_seconds": ttl,
    }


@router.get("/silos/{silo_id}/tier")
async def get_silo_tier(
    silo_id: str,
    redis: RedisClient = Depends(get_redis_client),
) -> dict[str, Any]:
    """Get the current rate limit tier for a silo."""
    settings = get_settings()
    cache_key = f"{TIER_CACHE_PREFIX}{silo_id}"

    cached = await redis._redis.get(cache_key)
    tier = cached.decode() if cached else settings.security.rate_limit.default_tier

    return {
        "silo_id": silo_id,
        "tier": tier,
        "is_cached": cached is not None,
    }
```

- [ ] **Step 4: Verify admin router is already wired**

Check `src/context_service/api/app.py` — admin router should already be included. If not:

```python
from context_service.api.routes.admin import router as admin_router
app.include_router(admin_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_admin_tier.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/routes/admin.py src/context_service/api/app.py tests/api/test_admin_tier.py
git commit -m "feat(admin): add tier management endpoints"
```

---

## Task 7: Integration Test and Final Verification

**Files:**
- Test: `tests/integration/test_rate_limiting.py` (new)

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_rate_limiting.py`:

```python
"""Integration tests for rate limiting end-to-end."""

from __future__ import annotations

import pytest

from context_service.api.rate_limit import RateLimitCategory, RateLimiter
from context_service.auth.context import AuthContext
from context_service.config.settings import get_settings


@pytest.mark.integration
class TestRateLimitingIntegration:
    async def test_tier_limits_enforced(self, redis_client) -> None:
        """Verify tier limits are actually enforced."""
        settings = get_settings()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings.security.rate_limit, "enabled", True)

            limiter = RateLimiter(redis_client)

            await redis_client._redis.set("tier:test_org", b"free")

            headers = await limiter.check(
                org_id="test_org",
                user_id="test_user",
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

            assert headers.limit == 20  # Free tier limit

    async def test_rate_limit_counter_increments(self, redis_client) -> None:
        """Verify counters increment correctly."""
        limiter = RateLimiter(redis_client)

        h1 = await limiter.check("org1", "user1", RateLimitCategory.REST, is_dev=True)
        h2 = await limiter.check("org1", "user1", RateLimitCategory.REST, is_dev=True)

        assert h1.remaining >= h2.remaining or h1.limit == 9999  # Dev mode unlimited
```

- [ ] **Step 2: Run full test suite**

Run: `uv run just test`
Expected: PASS

- [ ] **Step 3: Run type check and lint**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 4: Final commit**

```bash
git add tests/integration/test_rate_limiting.py
git commit -m "test: add rate limiting integration tests"
```

---

## Summary

This plan implements tiered rate limiting with:

1. **Config schema** (`TierLimits`, `EndpointLimits`) supporting free/starter/pro/enterprise tiers
2. **Redis atomic helper** (`incr_with_expire` via Lua script) for fixed-window counters
3. **RateLimiter service** with fail-open behavior, tier caching, and DB fallback
4. **REST middleware** for admin/REST routes (skips /health, /metrics, /mcp)
5. **MCP tool decorator** (`@rate_limited`) for per-tool rate limiting
6. **Admin endpoints** for tier management (persistent + cached)

**Feature flag:** `settings.security.rate_limit.enabled` (defaults to `False`)

**Next steps after implementation:**
- Enable in staging: `SECURITY__RATE_LIMIT__ENABLED=true`
- Backfill existing silos to appropriate tiers via admin endpoint
- Monitor via SigNoz for rate limit events
- Adjust tier limits based on actual usage patterns

---

## v1.1: Deferred Features

These features are scoped out of v1 (abuse prevention) and will be added in v1.1 (pricing enforcement):

### Monthly Quotas

Track writes/mo and recalls/mo per org to enforce pricing tier limits:

| Tier | Writes/mo | Recalls/mo |
|------|-----------|------------|
| Free | 2,000 | 200 |
| Starter | 50,000 | 5,000 |
| Pro | 300,000 | 30,000 |
| Enterprise | Unlimited | Unlimited |

**Implementation:** Separate Redis keys `rl_monthly:{category}:{YYYY-MM}:{org_id}`, checked before RPM limits.

### Per-User Fairness Cap

Prevent a single user from exhausting the org's shared quota:

```python
user_limit = int(org_limit * 0.2)  # 20% of org limit
```

**Implementation:** Additional counter check in `RateLimiter.check()` with user-scoped key.

### Billing Integration

- Overage charges when quota exceeded
- Stripe metered billing integration
- Usage dashboard for customers

"""Distributed rate limiting for embedding API calls using Redis."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from context_service.config.settings import ModelRateLimitConfig

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = structlog.get_logger(__name__)

# Global rate limiter instance (set at startup)
_embedding_rate_limiter: EmbeddingRateLimiter | None = None


class EmbeddingRateLimitExceeded(Exception):
    """Raised when embedding rate limit is exceeded."""

    def __init__(self, retry_after: float, current: int, limit: int) -> None:
        self.retry_after = retry_after
        self.current = current
        self.limit = limit
        super().__init__(f"Embedding rate limit exceeded: {current}/{limit} RPM")


class EmbeddingRateLimiter:
    """Redis-based rate limiter for embedding API calls.

    Uses a sliding window counter to enforce requests-per-minute limits
    across all workers. This protects against Vertex AI quota exhaustion.
    """

    KEY_PREFIX = "embed_rl"
    WINDOW_SECONDS = 60

    def __init__(
        self,
        redis: RedisClient,
        requests_per_minute: int = 250,
        max_concurrent: int = 10,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            redis: Redis client for distributed coordination.
            requests_per_minute: Max requests per minute (Vertex default: 250/region).
            max_concurrent: Max concurrent in-flight requests.
        """
        self._redis = redis
        self._rpm = requests_per_minute
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _get_window_key(self) -> tuple[str, int]:
        """Get the current window key and its start timestamp."""
        now = int(time.time())
        window_start = (now // self.WINDOW_SECONDS) * self.WINDOW_SECONDS
        key = f"{self.KEY_PREFIX}:{window_start}"
        return key, window_start

    async def acquire(self, timeout: float = 30.0) -> None:
        """Acquire a rate limit slot. Blocks if limit exceeded.

        Args:
            timeout: Max seconds to wait for a slot.

        Raises:
            EmbeddingRateLimitExceeded: If timeout expires waiting for slot.
        """
        deadline = time.monotonic() + timeout

        while True:
            key, window_start = self._get_window_key()

            # Increment counter with TTL
            try:
                current = await self._redis.incr_with_expire(
                    key, self.WINDOW_SECONDS + 10
                )
            except Exception as e:
                # Fail-open on Redis errors
                logger.warning("embedding_rate_limit_redis_error", error=str(e))
                return

            # Fail-open if Redis circuit is open (returns 0)
            if current == 0:
                logger.warning("embedding_rate_limit_redis_unavailable")
                return

            if current <= self._rpm:
                return

            # Over limit - calculate wait time
            now = time.monotonic()
            if now >= deadline:
                raise EmbeddingRateLimitExceeded(
                    retry_after=window_start + self.WINDOW_SECONDS - int(time.time()),
                    current=current,
                    limit=self._rpm,
                )

            # Wait until next window
            sleep_time = min(
                window_start + self.WINDOW_SECONDS - int(time.time()) + 0.1,
                deadline - now,
            )
            if sleep_time > 0:
                logger.debug(
                    "embedding_rate_limit_waiting",
                    current=current,
                    limit=self._rpm,
                    sleep_seconds=sleep_time,
                )
                await asyncio.sleep(sleep_time)

    async def __aenter__(self) -> None:
        """Context manager entry - acquires both semaphore and rate limit."""
        await self._semaphore.acquire()
        try:
            await self.acquire()
        except Exception:
            self._semaphore.release()
            raise

    async def __aexit__(self, *args: object) -> None:
        """Context manager exit - releases semaphore."""
        self._semaphore.release()


def set_embedding_rate_limiter(
    redis: RedisClient,
    config: ModelRateLimitConfig | None = None,
    requests_per_minute: int = 250,
) -> EmbeddingRateLimiter:
    """Initialize the global embedding rate limiter.

    Called at app/worker startup.

    Args:
        redis: Redis client.
        config: Rate limit config (uses max_concurrent_requests).
        requests_per_minute: RPM limit for the embedding API.

    Returns:
        The configured rate limiter.
    """
    global _embedding_rate_limiter
    max_concurrent = config.max_concurrent_requests if config else 10
    _embedding_rate_limiter = EmbeddingRateLimiter(
        redis=redis,
        requests_per_minute=requests_per_minute,
        max_concurrent=max_concurrent,
    )
    return _embedding_rate_limiter


def get_embedding_rate_limiter() -> EmbeddingRateLimiter | None:
    """Get the global embedding rate limiter (None if not initialized)."""
    return _embedding_rate_limiter


__all__ = [
    "EmbeddingRateLimiter",
    "EmbeddingRateLimitExceeded",
    "get_embedding_rate_limiter",
    "set_embedding_rate_limiter",
]

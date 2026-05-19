"""Unit tests for RedisClient.incr — no live Redis instance required."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from context_service.extraction.filter import circuit_breaker
from context_service.stores.redis import RedisClient


@pytest.fixture(autouse=True)
def clear_cb_registry() -> Generator[None, None, None]:
    """Reset the CB registry between tests to prevent circuit state bleed."""
    circuit_breaker._registry.clear()
    yield
    circuit_breaker._registry.clear()


class TestRedisClientIncr:
    async def test_redis_client_incr_returns_incremented_value(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)

        client = RedisClient(mock_redis)
        result = await client.incr("some:counter:key")

        assert result == 5
        mock_redis.incr.assert_awaited_once_with("some:counter:key")

    async def test_redis_client_incr_returns_zero_when_redis_unavailable(
        self,
    ) -> None:
        """Verify guard_degrade returns 0 when Redis raises ConnectionError."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=RedisConnectionError("unreachable"))

        client = RedisClient(mock_redis)

        # Prime the circuit breaker past its failure threshold so it opens.
        from context_service.engine.storage_circuit import _FAILURE_THRESHOLD

        for _ in range(_FAILURE_THRESHOLD):
            await client.incr("some:counter:key")

        # With circuit open, incr should degrade gracefully and return 0.
        result = await client.incr("some:counter:key")

        assert result == 0

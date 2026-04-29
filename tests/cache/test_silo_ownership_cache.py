"""Unit tests for SiloOwnershipCache."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.cache.silo_ownership_cache import SiloOwnershipCache


class _FakeRedis:
    """In-memory async stand-in for RedisClient."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: str | bytes,
        ttl_seconds: int | None = None,
    ) -> bool:
        if isinstance(value, str):
            value = value.encode()
        self.store[key] = value
        return True

    async def delete(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def cache(fake_redis: _FakeRedis) -> SiloOwnershipCache:
    redis: Any = fake_redis
    return SiloOwnershipCache(redis, ttl=90)


@pytest.mark.asyncio
async def test_miss_returns_none(cache: SiloOwnershipCache) -> None:
    assert await cache.get("org-1", "silo-a") is None


@pytest.mark.asyncio
async def test_set_then_get_returns_true(cache: SiloOwnershipCache) -> None:
    await cache.set("org-1", "silo-a")
    assert await cache.get("org-1", "silo-a") is True


@pytest.mark.asyncio
async def test_hit_returns_true(
    cache: SiloOwnershipCache,
    fake_redis: _FakeRedis,
) -> None:
    # Pre-populate as if a previous validation succeeded.
    fake_redis.store["cache:silo_ownership:org-2:silo-b"] = b"1"
    assert await cache.get("org-2", "silo-b") is True


@pytest.mark.asyncio
async def test_delete_then_get_returns_none(cache: SiloOwnershipCache) -> None:
    await cache.set("org-1", "silo-a")
    await cache.delete("org-1", "silo-a")
    assert await cache.get("org-1", "silo-a") is None


@pytest.mark.asyncio
async def test_get_swallows_redis_errors() -> None:
    redis: Any = AsyncMock()
    redis.get.side_effect = RuntimeError("boom")
    cache = SiloOwnershipCache(redis)
    assert await cache.get("org", "silo") is None


@pytest.mark.asyncio
async def test_set_swallows_redis_errors() -> None:
    redis: Any = AsyncMock()
    redis.set.side_effect = RuntimeError("boom")
    cache = SiloOwnershipCache(redis)
    # Must not raise.
    await cache.set("org", "silo")


@pytest.mark.asyncio
async def test_keys_isolate_orgs(
    cache: SiloOwnershipCache,
    fake_redis: _FakeRedis,
) -> None:
    await cache.set("org-x", "silo-shared")
    assert await cache.get("org-x", "silo-shared") is True
    assert await cache.get("org-y", "silo-shared") is None


@pytest.mark.asyncio
async def test_no_negative_caching(cache: SiloOwnershipCache) -> None:
    """A miss must not implicitly cache False; subsequent gets still miss."""
    assert await cache.get("org-1", "silo-a") is None
    assert await cache.get("org-1", "silo-a") is None


@pytest.mark.asyncio
async def test_ttl_override_is_passed_through() -> None:
    redis: Any = AsyncMock()
    cache = SiloOwnershipCache(redis, ttl=90)
    await cache.set("org", "silo", ttl_seconds=10)
    redis.set.assert_awaited_once()
    kwargs = redis.set.await_args.kwargs
    assert kwargs.get("ttl_seconds") == 10

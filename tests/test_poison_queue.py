"""Tests: PoisonQueue push / peek / TTL behaviour with a mocked Redis client."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.pipelines.poison_queue import PoisonQueue


def _make_redis(store: dict[str, bytes] | None = None) -> Any:
    """Build a minimal async Redis mock backed by an in-memory dict."""
    backing: dict[str, bytes] = store if store is not None else {}

    async def _set(key: str, value: bytes, ex: int | None = None) -> None:
        backing[key] = value

    async def _get(key: str) -> bytes | None:
        return backing.get(key)

    async def _scan(cursor: int, match: str = "*", count: int = 100) -> tuple[int, list[str]]:
        import fnmatch

        matched = [k for k in backing if fnmatch.fnmatch(k, match)]
        return 0, matched

    redis = MagicMock()
    redis.set = AsyncMock(side_effect=_set)
    redis.get = AsyncMock(side_effect=_get)
    redis.scan = AsyncMock(side_effect=_scan)
    return redis, backing


@pytest.mark.asyncio
async def test_push_writes_correct_key() -> None:
    redis, backing = _make_redis()
    queue = PoisonQueue(redis)
    await queue.push(run_id="run-abc", asset_key="extraction", error="timeout")
    assert "dagster:poison:extraction:run-abc" in backing


@pytest.mark.asyncio
async def test_push_payload_fields() -> None:
    redis, backing = _make_redis()
    queue = PoisonQueue(redis)
    await queue.push(run_id="run-xyz", asset_key="clustering", error="OOM")
    raw = backing["dagster:poison:clustering:run-xyz"]
    payload = json.loads(raw)
    assert payload["run_id"] == "run-xyz"
    assert payload["asset_key"] == "clustering"
    assert payload["error"] == "OOM"


@pytest.mark.asyncio
async def test_push_passes_ttl() -> None:
    redis, _ = _make_redis()
    queue = PoisonQueue(redis)
    await queue.push(run_id="r1", asset_key="embedding", error="err", ttl_seconds=3600)
    redis.set.assert_awaited_once()
    _, kwargs = redis.set.call_args
    assert kwargs.get("ex") == 3600


@pytest.mark.asyncio
async def test_push_default_ttl_seven_days() -> None:
    redis, _ = _make_redis()
    queue = PoisonQueue(redis)
    await queue.push(run_id="r2", asset_key="embedding", error="err")
    _, kwargs = redis.set.call_args
    assert kwargs.get("ex") == 7 * 24 * 3600


@pytest.mark.asyncio
async def test_peek_returns_all_entries() -> None:
    redis, _ = _make_redis()
    queue = PoisonQueue(redis)
    await queue.push(run_id="r1", asset_key="extraction", error="e1")
    await queue.push(run_id="r2", asset_key="extraction", error="e2")
    results = await queue.peek()
    run_ids = {r["run_id"] for r in results}
    assert "r1" in run_ids
    assert "r2" in run_ids


@pytest.mark.asyncio
async def test_peek_filtered_by_asset_key() -> None:
    redis, _ = _make_redis()
    queue = PoisonQueue(redis)
    await queue.push(run_id="r1", asset_key="extraction", error="e1")
    await queue.push(run_id="r2", asset_key="clustering", error="e2")
    results = await queue.peek(asset_key="extraction")
    assert all(r["asset_key"] == "extraction" for r in results)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_push_swallows_redis_error() -> None:
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=Exception("connection refused"))
    queue = PoisonQueue(redis)
    await queue.push(run_id="r", asset_key="a", error="e")


@pytest.mark.asyncio
async def test_peek_swallows_redis_error() -> None:
    redis = MagicMock()
    redis.scan = AsyncMock(side_effect=Exception("connection refused"))
    queue = PoisonQueue(redis)
    results = await queue.peek()
    assert results == []

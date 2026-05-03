"""Tests for signals.access_events.emit_access_event."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.signals.access_events import (
    ACCESS_STREAM_MAXLEN,
    access_stream_key,
    emit_access_event,
)


@pytest.mark.asyncio
async def test_emit_calls_xadd_with_expected_shape() -> None:
    redis = AsyncMock()
    redis.set_nx = AsyncMock(return_value=True)
    redis.xadd = AsyncMock(return_value="1700000000-0")

    await emit_access_event(redis, "silo-a", "node-42")

    redis.xadd.assert_awaited_once()
    args, kwargs = redis.xadd.call_args
    assert args[0] == "silo:silo-a:access_events"
    assert args[1] == {"node_id": "node-42", "event_type": "read"}
    assert kwargs == {"maxlen": ACCESS_STREAM_MAXLEN, "approximate": True}


@pytest.mark.asyncio
async def test_emit_includes_layer_when_provided() -> None:
    redis = AsyncMock()
    redis.set_nx = AsyncMock(return_value=True)
    redis.xadd = AsyncMock(return_value="1700000000-0")

    await emit_access_event(redis, "silo-a", "node-42", layer="Fact")

    args, _kwargs = redis.xadd.call_args
    assert args[1] == {"node_id": "node-42", "event_type": "read", "layer": "Fact"}


@pytest.mark.asyncio
async def test_emit_write_event_type() -> None:
    redis = AsyncMock()
    redis.set_nx = AsyncMock(return_value=True)
    redis.xadd = AsyncMock(return_value="1700000000-0")

    await emit_access_event(redis, "silo-a", "node-42", event_type="write", layer="Claim")

    args, _kwargs = redis.xadd.call_args
    assert args[1] == {"node_id": "node-42", "event_type": "write", "layer": "Claim"}


@pytest.mark.asyncio
async def test_emit_skips_duplicate_within_dedup_window() -> None:
    redis = AsyncMock()
    redis.set_nx = AsyncMock(return_value=False)  # Key already exists
    redis.xadd = AsyncMock()

    await emit_access_event(redis, "silo-a", "node-42")

    redis.xadd.assert_not_awaited()  # Should skip emit


@pytest.mark.asyncio
async def test_emit_swallows_redis_failure() -> None:
    redis = AsyncMock()
    redis.xadd = AsyncMock(side_effect=RuntimeError("connection refused"))

    # Must not raise.
    await emit_access_event(redis, "silo-a", "node-42")


def test_access_stream_key_format() -> None:
    assert access_stream_key("silo-x") == "silo:silo-x:access_events"

"""Tests for metrics flush to database."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.telemetry.buffer import MetricsBuffer
from context_service.telemetry.flush import flush_metrics_to_db


def _make_pool(conn: AsyncMock) -> MagicMock:
    """Return a pool mock where pool.acquire() acts as an async context manager."""
    ctx = AsyncMock()
    ctx.__aenter__.return_value = conn
    ctx.__aexit__.return_value = None
    pool = MagicMock()
    pool.acquire.return_value = ctx
    return pool


@pytest.mark.asyncio
async def test_flush_empty_buffer_does_nothing() -> None:
    buffer = MetricsBuffer()
    pool = MagicMock()

    await flush_metrics_to_db(pool, buffer)

    pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_flush_executes_insert() -> None:
    buffer = MetricsBuffer()
    buffer.record("tool.remember", "silo-1", latency_ms=100.0)

    conn = AsyncMock()
    pool = _make_pool(conn)

    await flush_metrics_to_db(pool, buffer)

    conn.executemany.assert_called_once()
    call_args = conn.executemany.call_args
    assert "INSERT INTO service_metrics" in call_args[0][0]
    assert len(call_args[0][1]) == 1


@pytest.mark.asyncio
async def test_flush_clears_buffer_after_insert() -> None:
    buffer = MetricsBuffer()
    buffer.record("tool.remember", "silo-1")

    conn = AsyncMock()
    pool = _make_pool(conn)

    await flush_metrics_to_db(pool, buffer)

    assert buffer.flush() == []


@pytest.mark.asyncio
async def test_flush_preserves_data_on_db_error() -> None:
    """Buffer should not be cleared if DB write fails."""
    buffer = MetricsBuffer()
    buffer.record("tool.remember", "silo-1")

    conn = AsyncMock()
    conn.executemany.side_effect = Exception("DB connection lost")
    pool = _make_pool(conn)

    with pytest.raises(Exception, match="DB connection lost"):
        await flush_metrics_to_db(pool, buffer)

    # Buffer should still have the data
    rows = buffer.peek()
    assert len(rows) == 1
    assert rows[0]["metric_name"] == "tool.remember"

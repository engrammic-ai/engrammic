"""Tests for signals.cursor: HeatCursor init and atomic advance."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.signals.cursor import (
    advance_heat_cursor,
    fetch_or_init_heat_cursor,
)


@pytest.mark.asyncio
async def test_fetch_returns_initial_cursor_on_first_call() -> None:
    """MERGE response with '0-0' is returned verbatim."""
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=[{"last_id": "0-0"}])

    result = await fetch_or_init_heat_cursor(memgraph, "silo-a")

    assert result == "0-0"
    memgraph.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_returns_persisted_cursor_on_subsequent_calls() -> None:
    """When cursor already exists, MERGE returns the existing last_id."""
    persisted_id = "1746000000000-42"
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=[{"last_id": persisted_id}])

    result = await fetch_or_init_heat_cursor(memgraph, "silo-a")

    assert result == persisted_id


@pytest.mark.asyncio
async def test_fetch_falls_back_to_initial_on_empty_rows() -> None:
    """Empty row list (shouldn't happen with MERGE but guard for safety)."""
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=[])

    result = await fetch_or_init_heat_cursor(memgraph, "silo-b")

    assert result == "0-0"


@pytest.mark.asyncio
async def test_advance_calls_execute_write_without_tx() -> None:
    """Without a transaction, advance uses memgraph.execute_write."""
    memgraph = AsyncMock()
    memgraph.execute_write = AsyncMock(return_value=None)

    await advance_heat_cursor(memgraph, "silo-a", "1746000000001-0")

    memgraph.execute_write.assert_awaited_once()
    call_args = memgraph.execute_write.call_args
    params = call_args[0][1]
    assert params["silo_id"] == "silo-a"
    assert params["last_id"] == "1746000000001-0"


@pytest.mark.asyncio
async def test_advance_uses_tx_when_provided() -> None:
    """When a transaction is passed, advance uses tx.run instead of execute_write."""
    memgraph = AsyncMock()
    memgraph.execute_write = AsyncMock()

    result_mock = AsyncMock()
    result_mock.consume = AsyncMock()
    tx = MagicMock()
    tx.run = AsyncMock(return_value=result_mock)

    await advance_heat_cursor(memgraph, "silo-a", "1746000000002-0", tx=tx)

    tx.run.assert_awaited_once()
    result_mock.consume.assert_awaited_once()
    # execute_write must NOT be called when tx is provided.
    memgraph.execute_write.assert_not_awaited()

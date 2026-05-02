"""Tests for signals.heat.get_heat (Phase 2: real Memgraph read).

Phase 1 stub (returning 0.5 unconditionally) has been replaced. These tests
cover the real lookup path and the fallback behaviour.

Two variants for the happy path and empty-result path: one using AsyncMock
(original) and one using FakeGraphStore (demonstrating the fake).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.signals.heat import DEFAULT_HEAT, get_heat
from tests.fakes.fake_graph_store import FakeGraphStore


@pytest.mark.asyncio
async def test_returns_heat_score_from_memgraph() -> None:
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=[{"h": 0.85}])

    result = await get_heat(memgraph, "node-1", "silo-a")

    assert result == pytest.approx(0.85)
    memgraph.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_returns_heat_score_from_memgraph_fake() -> None:
    """Same assertion as above, using FakeGraphStore instead of AsyncMock."""
    store = FakeGraphStore()
    store.seed_query_result([{"h": 0.85}])

    result = await get_heat(store, "node-1", "silo-a")

    assert result == pytest.approx(0.85)
    assert len(store.query_log) == 1


@pytest.mark.asyncio
async def test_returns_default_when_node_not_found() -> None:
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=[])

    result = await get_heat(memgraph, "node-missing", "silo-a")

    assert result == DEFAULT_HEAT


@pytest.mark.asyncio
async def test_returns_default_when_node_not_found_fake() -> None:
    """Same assertion as above, using FakeGraphStore (no seed = empty result)."""
    store = FakeGraphStore()
    # No seed — execute_query returns [] by default.

    result = await get_heat(store, "node-missing", "silo-a")

    assert result == DEFAULT_HEAT
    assert len(store.query_log) == 1


@pytest.mark.asyncio
async def test_returns_default_on_memgraph_error() -> None:
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(side_effect=RuntimeError("connection refused"))

    # Must not raise.
    result = await get_heat(memgraph, "node-1", "silo-a")

    assert result == DEFAULT_HEAT


@pytest.mark.asyncio
async def test_default_heat_value_is_neutral() -> None:
    assert DEFAULT_HEAT == 0.5

"""Phase-1 stub coverage for signals.heat.get_heat.

Phase 2 swaps this for a real Memgraph read; the test suite for that lives
in test_signals_heat.py (created in Phase 2).
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from context_service.signals.heat import _STUB_LOG_GUARD, get_heat


@pytest.fixture(autouse=True)
def _reset_stub_log_guard() -> None:
    _STUB_LOG_GUARD.clear()
    yield
    _STUB_LOG_GUARD.clear()


@pytest.mark.asyncio
async def test_stub_returns_neutral() -> None:
    memgraph = AsyncMock()
    result = await get_heat(memgraph, "node-1", "silo-a")
    assert result == 0.5


@pytest.mark.asyncio
async def test_stub_does_not_touch_memgraph() -> None:
    memgraph = AsyncMock()
    await get_heat(memgraph, "node-1", "silo-a")
    memgraph.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_stub_logs_once_per_silo(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    memgraph = AsyncMock()

    await get_heat(memgraph, "node-1", "silo-a")
    await get_heat(memgraph, "node-2", "silo-a")
    await get_heat(memgraph, "node-3", "silo-b")

    stub_logs = [r for r in caplog.records if "heat.stub_active" in r.getMessage()]
    silos_logged = {r.__dict__.get("silo_id") for r in stub_logs}
    assert len(stub_logs) == 2
    assert silos_logged == {"silo-a", "silo-b"}

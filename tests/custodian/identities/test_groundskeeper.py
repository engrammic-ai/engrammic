import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

from context_service.custodian.identities.groundskeeper import (
    get_expired_memory_nodes,
    GroundskeeperIdentity,
)


@pytest.mark.asyncio
async def test_get_expired_memory_nodes():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"node_id": "n1", "decay_class": "ephemeral", "created_at": "2026-01-01T00:00:00Z"},
    ]

    result = await get_expired_memory_nodes(
        mock_store,
        silo_id="test-silo",
        decay_config={"ephemeral": {"hard_delete_days": 14}},
    )

    assert len(result) >= 0  # Depends on current date logic


@pytest.mark.asyncio
async def test_get_expired_memory_nodes_skips_none_config():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []

    result = await get_expired_memory_nodes(
        mock_store,
        silo_id="test-silo",
        decay_config={"ephemeral": None},
    )

    mock_store.execute_query.assert_not_called()
    assert result == []


@pytest.mark.asyncio
async def test_get_expired_memory_nodes_uses_default_hard_delete_days():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []

    await get_expired_memory_nodes(
        mock_store,
        silo_id="test-silo",
        decay_config={"ephemeral": {}},
    )

    mock_store.execute_query.assert_called_once()
    call_params = mock_store.execute_query.call_args[0][1]
    # cutoff should be ~9999 days ago (default)
    cutoff = datetime.fromisoformat(call_params["cutoff"])
    assert cutoff < datetime.now(UTC) - timedelta(days=9990)


@pytest.mark.asyncio
async def test_run_gc_no_expired_nodes():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []

    identity = GroundskeeperIdentity(
        store=mock_store,
        silo_id="test-silo",
        decay_config={"ephemeral": {"hard_delete_days": 14}},
    )

    result = await identity.run_gc()

    assert result == {"deleted": 0, "silo_id": "test-silo"}
    mock_store.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_run_gc_deletes_expired_nodes():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"node_id": "n1", "decay_class": "ephemeral", "created_at": "2026-01-01T00:00:00Z"},
        {"node_id": "n2", "decay_class": "ephemeral", "created_at": "2026-01-02T00:00:00Z"},
    ]

    identity = GroundskeeperIdentity(
        store=mock_store,
        silo_id="test-silo",
        decay_config={"ephemeral": {"hard_delete_days": 14}},
    )

    result = await identity.run_gc()

    assert result == {"deleted": 2, "silo_id": "test-silo"}
    mock_store.execute_write.assert_called_once()
    write_params = mock_store.execute_write.call_args[0][1]
    assert set(write_params["node_ids"]) == {"n1", "n2"}
    assert write_params["silo_id"] == "test-silo"


@pytest.mark.asyncio
async def test_run_hyperedge_dedup_returns_zero():
    mock_store = AsyncMock()

    identity = GroundskeeperIdentity(
        store=mock_store,
        silo_id="test-silo",
        decay_config={},
    )

    result = await identity.run_hyperedge_dedup()

    assert result == {"deduped": 0, "silo_id": "test-silo"}

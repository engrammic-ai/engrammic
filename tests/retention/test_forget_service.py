"""Tests for ForgetService."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_write.return_value = [{"id": "node-1", "downstream_count": 3}]
    store.execute_query.return_value = [{"requested_at": 12345}]
    return store


@pytest.mark.asyncio
async def test_forget_tombstones_node(mock_store):
    from context_service.retention.forget_service import ForgetService

    service = ForgetService(store=mock_store, qdrant_store=AsyncMock())
    result = await service.forget("node-1", "silo-1")

    assert result["status"] == "tombstoned"
    assert result["node_id"] == "node-1"
    assert result["downstream_references"] == 3
    mock_store.execute_write.assert_called()


@pytest.mark.asyncio
async def test_forget_returns_not_found_when_node_missing(mock_store):
    from context_service.retention.forget_service import ForgetService

    mock_store.execute_write.return_value = []

    service = ForgetService(store=mock_store, qdrant_store=None)
    result = await service.forget("missing-node", "silo-1")

    assert result["status"] == "not_found"
    assert result["node_id"] == "missing-node"


@pytest.mark.asyncio
async def test_cancel_forget_within_window(mock_store):
    from context_service.retention.forget_service import ForgetService

    # execute_query (node exists check) returns node, execute_write (cancel) succeeds
    mock_store.execute_query.return_value = [{"requested_at": 12345}]
    mock_store.execute_write.return_value = [{"id": "node-1"}]

    service = ForgetService(store=mock_store, qdrant_store=AsyncMock())
    result = await service.cancel_forget("node-1", "silo-1")

    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_forget_node_not_found(mock_store):
    from context_service.retention.forget_service import ForgetService

    # Node does not exist at all
    mock_store.execute_query.return_value = []

    service = ForgetService(store=mock_store, qdrant_store=None)
    result = await service.cancel_forget("missing-node", "silo-1")

    assert result["status"] == "not_found"
    assert result["node_id"] == "missing-node"


@pytest.mark.asyncio
async def test_cancel_forget_expired_window(mock_store):
    from context_service.retention.forget_service import ForgetService

    # Node exists (execute_query returns it), but window has expired (execute_write returns [])
    mock_store.execute_query.return_value = [{"requested_at": 12345}]
    mock_store.execute_write.return_value = []

    service = ForgetService(store=mock_store, qdrant_store=None)
    result = await service.cancel_forget("node-1", "silo-1")

    assert result["status"] == "cancel_window_expired"
    assert result["node_id"] == "node-1"

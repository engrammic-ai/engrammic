import pytest
from unittest.mock import AsyncMock

from context_service.retention.service import RetentionService
from context_service.retention.policy import RetentionPolicy

@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=[])
    return store

@pytest.fixture
def service(mock_store):
    return RetentionService(store=mock_store, policy=RetentionPolicy())

@pytest.mark.asyncio
async def test_find_tombstone_candidates_queries_store(service, mock_store):
    await service.find_tombstone_candidates("silo-123")
    mock_store.execute_query.assert_called_once()
    call_args = mock_store.execute_query.call_args
    assert "silo_id" in str(call_args)

@pytest.mark.asyncio
async def test_tombstone_nodes_sets_timestamp(service, mock_store):
    mock_store.execute_query.return_value = [{"id": "node-1"}]
    run_id = "run-abc"

    result = await service.tombstone_nodes(["node-1"], "silo-123", run_id)

    assert result == 1

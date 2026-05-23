"""Tests for stub-retention methods on MemgraphStore."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.engine import queries
from context_service.engine.memgraph_store import MemgraphStore


@pytest.fixture
def silo_id() -> str:
    return f"test-silo-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.execute_write = AsyncMock()
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def memgraph_store(mock_client: MagicMock) -> MemgraphStore:
    store = MemgraphStore.__new__(MemgraphStore)
    store._client = mock_client
    return store


# ---------------------------------------------------------------------------
# find_stale_chain_interior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_stale_chain_interior_returns_node_ids(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """find_stale_chain_interior returns node_ids for interior nodes beyond max_length."""
    node_a = str(uuid.uuid4())
    node_b = str(uuid.uuid4())

    mock_client.execute_query.return_value = [
        {"node_id": node_a},
        {"node_id": node_b},
    ]

    result = await memgraph_store.find_stale_chain_interior(
        silo_id=silo_id,
        max_length=3,
        batch_size=50,
    )

    assert result == [node_a, node_b]
    mock_client.execute_query.assert_called_once()

    call_args = mock_client.execute_query.call_args
    assert call_args[0][0] is queries.FIND_STALE_CHAIN_INTERIOR
    params = call_args[0][1]
    assert params["silo_id"] == silo_id
    assert params["max_length"] == 3
    assert params["batch_size"] == 50


@pytest.mark.asyncio
async def test_find_stale_chain_interior_empty_when_no_candidates(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """find_stale_chain_interior returns an empty list when no nodes qualify."""
    mock_client.execute_query.return_value = []

    result = await memgraph_store.find_stale_chain_interior(
        silo_id=silo_id,
        max_length=10,
    )

    assert result == []


@pytest.mark.asyncio
async def test_find_stale_chain_interior_uses_default_batch_size(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """find_stale_chain_interior defaults batch_size to 100."""
    mock_client.execute_query.return_value = []

    await memgraph_store.find_stale_chain_interior(silo_id=silo_id, max_length=5)

    params = mock_client.execute_query.call_args[0][1]
    assert params["batch_size"] == 100


@pytest.mark.asyncio
async def test_find_stale_chain_interior_query_filters_stub_and_length(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """The FIND_STALE_CHAIN_INTERIOR query filters already-stubbed nodes and length."""
    mock_client.execute_query.return_value = []

    await memgraph_store.find_stale_chain_interior(silo_id=silo_id, max_length=2)

    query = mock_client.execute_query.call_args[0][0]
    assert "stub" in query, "Query should filter nodes that are already stubbed"
    assert "max_length" in query, "Query should compare against max_length parameter"
    assert "SUPERSEDES" in query, "Query should traverse SUPERSEDES edges"


# ---------------------------------------------------------------------------
# convert_to_stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_to_stub_returns_true_on_success(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """convert_to_stub returns True when the node is found and updated."""
    node_id = str(uuid.uuid4())
    mock_client.execute_write.return_value = [{"id": node_id}]

    result = await memgraph_store.convert_to_stub(node_id=node_id, silo_id=silo_id)

    assert result is True
    mock_client.execute_write.assert_called_once()


@pytest.mark.asyncio
async def test_convert_to_stub_returns_false_when_node_not_found(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """convert_to_stub returns False when the node does not exist."""
    mock_client.execute_write.return_value = []

    result = await memgraph_store.convert_to_stub(node_id=str(uuid.uuid4()), silo_id=silo_id)

    assert result is False


@pytest.mark.asyncio
async def test_convert_to_stub_clears_content_fields(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """convert_to_stub uses a query that nulls content, content_hash, and embedding."""
    node_id = str(uuid.uuid4())
    mock_client.execute_write.return_value = [{"id": node_id}]

    await memgraph_store.convert_to_stub(node_id=node_id, silo_id=silo_id)

    call_args = mock_client.execute_write.call_args
    query = call_args[0][0]

    assert "n.content = NULL" in query, "Query should null content"
    assert "n.content_hash = NULL" in query, "Query should null content_hash"
    assert "n.embedding = NULL" in query, "Query should null embedding"
    assert "n.stub = true" in query, "Query should set stub flag"


@pytest.mark.asyncio
async def test_convert_to_stub_passes_stubbed_at_timestamp(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """convert_to_stub passes a stubbed_at epoch-microsecond timestamp."""
    node_id = str(uuid.uuid4())
    mock_client.execute_write.return_value = [{"id": node_id}]

    await memgraph_store.convert_to_stub(node_id=node_id, silo_id=silo_id)

    params = mock_client.execute_write.call_args[0][1]
    assert "stubbed_at" in params
    assert isinstance(params["stubbed_at"], int)
    # epoch-microseconds: should be a large int (> 1e15 for post-2001 timestamps)
    assert params["stubbed_at"] > 1_000_000_000_000_000


@pytest.mark.asyncio
async def test_convert_to_stub_preserves_node_identity_in_query(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """convert_to_stub passes the correct node_id and silo_id to the query."""
    node_id = str(uuid.uuid4())
    mock_client.execute_write.return_value = [{"id": node_id}]

    await memgraph_store.convert_to_stub(node_id=node_id, silo_id=silo_id)

    params = mock_client.execute_write.call_args[0][1]
    assert params["id"] == node_id
    assert params["silo_id"] == silo_id

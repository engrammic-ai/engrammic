"""Tests for supersession chain pointer optimization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.engine.memgraph_store import MemgraphStore


@pytest.fixture
def silo_id() -> str:
    return f"test-silo-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock Memgraph client that tracks query execution."""
    client = MagicMock()
    client.execute_write = AsyncMock()
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def memgraph_store(mock_client: MagicMock) -> MemgraphStore:
    """Create MemgraphStore with mocked client."""
    store = MemgraphStore.__new__(MemgraphStore)
    store._client = mock_client
    return store


@pytest.mark.asyncio
async def test_supersession_sets_tail_and_head_pointers(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
    now: datetime,
) -> None:
    """When B supersedes A, query should set pointers.

    The CREATE_CROSS_NODE_SUPERSEDES query should:
    - Set tail_id on the new (superseding) node
    - Set head_id on the tail node pointing to new head
    """
    node_a_id = uuid.uuid4()
    node_b_id = uuid.uuid4()

    # Mock successful edge creation
    mock_client.execute_write.return_value = [{"created": 1}]

    # B supersedes A
    created = await memgraph_store.create_supersedes_edge(
        from_id=node_b_id,
        to_id=node_a_id,
        silo_id=silo_id,
        valid_from=now,
    )
    assert created

    # Verify the query was called
    mock_client.execute_write.assert_called_once()

    # Get the query that was executed
    call_args = mock_client.execute_write.call_args
    query = call_args[0][0]

    # The query should include pointer updates
    # - SET new.tail_id (derived from old's tail_id or old.id)
    # - SET tail.head_id = new.id
    assert "tail_id" in query, "Query should set tail_id on new node"
    assert "head_id" in query, "Query should set head_id on tail node"


@pytest.mark.asyncio
async def test_supersession_query_derives_tail_from_chain(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
    now: datetime,
) -> None:
    """When extending a chain (C supersedes B which already superseded A),
    C should get tail_id = A (from B's tail_id), not B.
    """
    node_b_id = uuid.uuid4()
    node_c_id = uuid.uuid4()

    mock_client.execute_write.return_value = [{"created": 1}]

    await memgraph_store.create_supersedes_edge(
        from_id=node_c_id,
        to_id=node_b_id,
        silo_id=silo_id,
        valid_from=now,
    )

    # Verify the query uses COALESCE to derive tail_id
    query = mock_client.execute_write.call_args[0][0]
    assert "COALESCE" in query, "Query should use COALESCE to derive tail_id from chain"


@pytest.mark.asyncio
async def test_belief_supersession_query_sets_pointers() -> None:
    """Verify CREATE_BELIEF_SUPERSEDES query includes pointer updates.

    The query should:
    - Set tail_id on the newer belief (to track chain origin)
    - Set head_id on the tail belief (to track current head)
    """
    from context_service.db import queries as db_queries

    query = db_queries.CREATE_BELIEF_SUPERSEDES

    # Query should set pointers for O(1) chain resolution
    assert "tail_id" in query, "Query should set tail_id on newer belief"
    assert "head_id" in query, "Query should set head_id on tail belief"
    assert "COALESCE" in query, "Query should derive tail_id from existing chain"

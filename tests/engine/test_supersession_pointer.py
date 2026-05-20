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
    """Create MemgraphStore with mocked client and no-op Redis lock helpers."""
    store = MemgraphStore.__new__(MemgraphStore)
    store._client = mock_client
    # Patch lock helpers so tests don't require a live Redis instance.
    store._acquire_supersession_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    store._release_supersession_lock = AsyncMock()  # type: ignore[method-assign]
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


@pytest.mark.asyncio
async def test_chain_extension_updates_tail_head_pointer(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
    now: datetime,
) -> None:
    """When C supersedes B (which superseded A), tail A's head_id updates to C.

    The query uses COALESCE(old.tail_id, old.id) to derive the tail_id for
    the new node. When B already has tail_id=A, C gets tail_id=A (from B).
    The query then updates tail.head_id = new.id, so A.head_id becomes C.
    """
    node_a_id, node_b_id, node_c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    # Mock successful edge creation for both supersession calls
    mock_client.execute_write.return_value = [{"created": 1}]

    # B supersedes A
    await memgraph_store.create_supersedes_edge(
        from_id=node_b_id, to_id=node_a_id, silo_id=silo_id, valid_from=now
    )

    # C supersedes B
    await memgraph_store.create_supersedes_edge(
        from_id=node_c_id, to_id=node_b_id, silo_id=silo_id, valid_from=now
    )

    # Verify both calls were made
    assert mock_client.execute_write.call_count == 2

    # Verify both calls use the same query with pointer updates
    for call in mock_client.execute_write.call_args_list:
        query = call[0][0]
        # Query should derive tail_id from chain and update head pointer
        assert "COALESCE" in query, "Query should derive tail_id from chain"
        assert "tail.head_id" in query, "Query should update tail's head_id"

    # Verify parameters for second call (C supersedes B)
    second_call_params = mock_client.execute_write.call_args_list[1][0][1]
    assert second_call_params["from_id"] == str(node_c_id)
    assert second_call_params["to_id"] == str(node_b_id)


@pytest.mark.asyncio
async def test_crystallize_commitment_query_sets_pointers() -> None:
    """Verify CRYSTALLIZE_TO_COMMITMENT query includes pointer updates.

    The query should:
    - Set tail_id on the new commitment (to track chain origin)
    - Set head_id on the tail commitment (to track current head)
    """
    from context_service.db import queries as db_queries

    query = db_queries.CRYSTALLIZE_TO_COMMITMENT

    # Query should set pointers for O(1) chain resolution
    assert "tail_id" in query, "Query should set tail_id on new commitment"
    assert "head_id" in query, "Query should set head_id on tail commitment"
    assert "COALESCE" in query, "Query should derive tail_id from existing chain"


@pytest.mark.asyncio
async def test_resolve_current_head_via_pointers(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """resolve_current_head returns chain head in O(1) via pointers."""
    node_a_id = uuid.uuid4()
    node_c_id = uuid.uuid4()

    # Mock: query returns C as head when looking up A
    mock_client.execute_query.return_value = [{"head_id": str(node_c_id)}]

    head = await memgraph_store.resolve_current_head(node_a_id, silo_id)

    assert head == node_c_id
    mock_client.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_current_head_single_node(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """Single node with no supersession returns itself."""
    node_id = uuid.uuid4()

    # Mock: standalone node returns itself as head
    mock_client.execute_query.return_value = [{"head_id": str(node_id)}]

    head = await memgraph_store.resolve_current_head(node_id, silo_id)

    assert head == node_id


@pytest.mark.asyncio
async def test_resolve_current_head_nonexistent_node(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    """Nonexistent node returns None."""
    node_id = uuid.uuid4()

    # Mock: no result for nonexistent node
    mock_client.execute_query.return_value = []

    head = await memgraph_store.resolve_current_head(node_id, silo_id)

    assert head is None


@pytest.mark.asyncio
async def test_filter_superseded_at_uses_pointers(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
    now: datetime,
) -> None:
    """filter_superseded_at returns head for all nodes in chain.

    The query should use pointer fast-path when available, falling back
    to chain walk for historical queries or nodes without pointers.
    """
    node_a_id, node_b_id, node_c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    # Mock: all three nodes resolve to C (the head)
    mock_client.execute_query.return_value = [
        {"input_id": str(node_a_id), "valid_id": str(node_c_id)},
        {"input_id": str(node_b_id), "valid_id": str(node_c_id)},
        {"input_id": str(node_c_id), "valid_id": str(node_c_id)},
    ]

    result = await memgraph_store.filter_superseded_at(
        node_ids=[node_a_id, node_b_id, node_c_id],
        silo_id=silo_id,
        as_of=now,
    )

    # All should map to C
    assert result[node_a_id] == node_c_id
    assert result[node_b_id] == node_c_id
    assert result[node_c_id] == node_c_id

    # Verify the query was called
    mock_client.execute_query.assert_called_once()

    # Verify the query includes pointer fast-path
    query = mock_client.execute_query.call_args[0][0]
    assert "tail_id" in query, "Query should use tail_id for fast-path"
    assert "head_id" in query, "Query should use head_id for fast-path"

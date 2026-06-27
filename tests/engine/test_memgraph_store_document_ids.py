"""Tests for MemgraphStore.query_document_ids."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.engine.memgraph_store import MemgraphStore


@pytest.fixture
def silo_id() -> str:
    return f"test-silo-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def memgraph_store(mock_client: MagicMock) -> MemgraphStore:
    store = MemgraphStore.__new__(MemgraphStore)
    store._client = mock_client
    return store


@pytest.mark.asyncio
async def test_query_document_ids_returns_existing(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    node_id = str(uuid.uuid4())
    mock_client.execute_query.return_value = [
        {"doc_id": "doc-1", "node_id": node_id},
    ]

    result = await memgraph_store.query_document_ids(silo_id, ["doc-1", "doc-2"])

    assert result == {"doc-1": node_id}


@pytest.mark.asyncio
async def test_query_document_ids_empty_input(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    result = await memgraph_store.query_document_ids(silo_id, [])

    assert result == {}
    mock_client.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_query_document_ids_none_found(
    memgraph_store: MemgraphStore,
    mock_client: MagicMock,
    silo_id: str,
) -> None:
    mock_client.execute_query.return_value = []

    result = await memgraph_store.query_document_ids(silo_id, ["doc-99"])

    assert result == {}

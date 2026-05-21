"""Tests for EngineQdrantStore tombstone filter and set_payload."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.models import ScoredPoint

from context_service.engine.qdrant_store import EngineQdrantStore
from context_service.stores.qdrant import QdrantClient


def _make_qdrant_client(vector_size: int = 512) -> QdrantClient:
    return QdrantClient(
        vector_size=vector_size,
        url="http://localhost:6333",
        collection_name="unused",
        scalar_quantization=False,
    )


def _make_mock_async_client(existing_collections: list[str] | None = None) -> AsyncMock:
    mock = AsyncMock()
    mock_collections = MagicMock()
    mock_collections.collections = [
        MagicMock(name=n) for n in (existing_collections or [])
    ]
    mock.get_collections.return_value = mock_collections
    mock.create_collection = AsyncMock()
    mock.create_payload_index = AsyncMock()
    mock.upsert = AsyncMock()
    mock.set_payload = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_search_excludes_tombstoned_nodes() -> None:
    """Tombstoned nodes should not appear in search results."""
    silo_id = "test-silo"
    node_id = str(uuid.uuid4())
    collection_name = f"ctx_{silo_id}"

    qdrant_client = _make_qdrant_client()
    store = EngineQdrantStore(qdrant_client, hybrid=False)

    mock_async_client = _make_mock_async_client(existing_collections=[collection_name])

    # query_points returns empty results (tombstoned node is filtered out)
    mock_query_response = MagicMock()
    mock_query_response.points = []
    mock_async_client.query_points = AsyncMock(return_value=mock_query_response)
    mock_async_client.set_payload = AsyncMock()

    with patch.object(qdrant_client, "_get_client", return_value=mock_async_client):
        # Upsert the node
        await store.upsert(
            node_id=uuid.UUID(node_id),
            vector=[0.1] * 512,
            silo_id=silo_id,
            node_type="Observation",
        )

        # Tombstone it via set_payload
        # tombstoned_at is an integer microsecond timestamp matching the Memgraph property format
        await store.set_payload(
            silo_id=silo_id,
            node_id=uuid.UUID(node_id),
            payload={"tombstoned_at": 1716249600000000},
        )

        # Search should not find it (tombstone filter excludes it)
        results = await store.query(
            vector=[0.1] * 512,
            silo_id=silo_id,
        )

    assert not any(r.node_id == node_id for r in results)

    # Verify set_payload was called with the tombstone payload
    mock_async_client.set_payload.assert_called_once_with(
        collection_name=collection_name,
        payload={"tombstoned_at": 1716249600000000},
        points=[node_id],
        wait=True,
    )

    # Verify query_points was called with a filter that excludes tombstoned nodes
    query_call_kwargs = mock_async_client.query_points.call_args.kwargs
    query_filter = query_call_kwargs.get("query_filter")
    assert query_filter is not None

    # The filter must conditions should include tombstone exclusion
    must_conditions = query_filter.must
    assert must_conditions is not None
    assert len(must_conditions) >= 2, (
        "Expected at least 2 must conditions: silo_id match and tombstone exclusion"
    )


@pytest.mark.asyncio
async def test_set_payload_updates_point() -> None:
    """set_payload should call Qdrant client set_payload with correct args."""
    silo_id = "test-silo-2"
    node_id = str(uuid.uuid4())
    collection_name = f"ctx_{silo_id}"

    qdrant_client = _make_qdrant_client()
    store = EngineQdrantStore(qdrant_client, hybrid=False)

    mock_async_client = _make_mock_async_client(existing_collections=[collection_name])

    node_uuid = uuid.UUID(node_id)
    with patch.object(qdrant_client, "_get_client", return_value=mock_async_client):
        # tombstoned_at is an integer microsecond timestamp matching the Memgraph property format
        await store.set_payload(
            silo_id=silo_id,
            node_id=node_uuid,
            payload={"tombstoned_at": 9999999999},
        )

    mock_async_client.set_payload.assert_called_once_with(
        collection_name=collection_name,
        payload={"tombstoned_at": 9999999999},
        points=[str(node_uuid)],
        wait=True,
    )


@pytest.mark.asyncio
async def test_search_includes_non_tombstoned_nodes() -> None:
    """Nodes without tombstoned_at should appear in search results."""
    silo_id = "test-silo-3"
    node_id = str(uuid.uuid4())
    collection_name = f"ctx_{silo_id}"

    qdrant_client = _make_qdrant_client()
    store = EngineQdrantStore(qdrant_client, hybrid=False)

    mock_async_client = _make_mock_async_client(existing_collections=[collection_name])

    # query_points returns the non-tombstoned node
    mock_scored_point = MagicMock(spec=ScoredPoint)
    mock_scored_point.id = node_id
    mock_scored_point.score = 0.95
    mock_scored_point.payload = {"silo_id": silo_id, "type": "Observation"}

    mock_query_response = MagicMock()
    mock_query_response.points = [mock_scored_point]
    mock_async_client.query_points = AsyncMock(return_value=mock_query_response)

    with patch.object(qdrant_client, "_get_client", return_value=mock_async_client):
        results = await store.query(
            vector=[0.1] * 512,
            silo_id=silo_id,
        )

    assert len(results) == 1
    assert results[0].node_id == node_id
    assert results[0].score == 0.95

"""Tests for three-store hard-delete coordination."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_stores():
    return {
        "memgraph": AsyncMock(),
        "qdrant": AsyncMock(),
        "postgres": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_hard_delete_memgraph_first(mock_stores):
    """Memgraph delete must succeed before Qdrant delete runs."""
    from context_service.retention.service import RetentionService

    node_id = str(uuid.uuid4())
    mock_stores["memgraph"].execute_query.return_value = [{"id": node_id}]

    service = RetentionService(
        store=mock_stores["memgraph"],
        qdrant_store=mock_stores["qdrant"],
    )

    result = await service.hard_delete_node(node_id, "silo-1")

    assert result is True
    mock_stores["memgraph"].execute_query.assert_called_once()
    mock_stores["qdrant"].delete.assert_called_once()
    call_kwargs = mock_stores["qdrant"].delete.call_args
    assert call_kwargs.kwargs.get("silo_id") == "silo-1" or (
        len(call_kwargs.args) >= 2 and call_kwargs.args[1] == "silo-1"
    )


@pytest.mark.asyncio
async def test_hard_delete_aborts_when_memgraph_returns_empty(mock_stores):
    """If Memgraph returns no results, Qdrant must not be called."""
    from context_service.retention.service import RetentionService

    mock_stores["memgraph"].execute_query.return_value = []

    service = RetentionService(
        store=mock_stores["memgraph"],
        qdrant_store=mock_stores["qdrant"],
    )

    result = await service.hard_delete_node("node-missing", "silo-1")

    assert result is False
    mock_stores["qdrant"].delete.assert_not_called()


@pytest.mark.asyncio
async def test_hard_delete_dead_letters_on_qdrant_failure(mock_stores):
    """Qdrant failure after 3 attempts must enqueue to dead-letter queue."""
    from context_service.retention.service import RetentionService

    node_id = str(uuid.uuid4())
    mock_stores["memgraph"].execute_query.return_value = [{"id": node_id}]
    mock_stores["qdrant"].delete.side_effect = Exception("qdrant unavailable")

    with patch(
        "context_service.retention.service.enqueue_failed_delete", new_callable=AsyncMock
    ) as mock_enqueue:
        service = RetentionService(
            store=mock_stores["memgraph"],
            qdrant_store=mock_stores["qdrant"],
        )

        result = await service.hard_delete_node(node_id, "silo-1")

    assert result is True
    assert mock_stores["qdrant"].delete.call_count == 3
    mock_enqueue.assert_called_once_with("silo-1", node_id, "qdrant unavailable")


@pytest.mark.asyncio
async def test_hard_delete_no_qdrant_store(mock_stores):
    """When no qdrant_store is provided, hard_delete_node still returns True."""
    from context_service.retention.service import RetentionService

    node_id = str(uuid.uuid4())
    mock_stores["memgraph"].execute_query.return_value = [{"id": node_id}]

    service = RetentionService(
        store=mock_stores["memgraph"],
        qdrant_store=None,
    )

    result = await service.hard_delete_node(node_id, "silo-1")

    assert result is True
    mock_stores["qdrant"].delete.assert_not_called()

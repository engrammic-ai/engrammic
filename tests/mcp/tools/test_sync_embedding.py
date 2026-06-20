# tests/mcp/tools/test_sync_embedding.py
"""Tests: sync embedding wired into remember/learn/reflect/hypothesize/decide/commit/accept paths."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.context_store import (
    _context_assert,
    _context_remember,
)

DUMMY_EMBEDDING = [0.1] * 768
NODE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_remember_upserts_embedding_to_qdrant(mock_mcp_context, mock_context_service):
    """_context_remember should embed content and upsert to Qdrant after node creation."""
    mock_vector_store = AsyncMock()
    mock_vector_store.upsert = AsyncMock(return_value=True)
    mock_context_service.vector_store = mock_vector_store

    with patch(
        "context_service.mcp.tools.context_store.embed",
        new=AsyncMock(return_value=DUMMY_EMBEDDING),
    ) as mock_embed:
        result = await _context_remember(
            silo_id=None,
            content="Test observation for embedding",
        )

    assert "node_id" in result
    assert result.get("error") is None

    mock_embed.assert_called_once_with("Test observation for embedding")
    mock_vector_store.upsert.assert_called_once()

    call_kwargs = mock_vector_store.upsert.call_args.kwargs
    assert call_kwargs["node_id"] == result["node_id"]
    assert call_kwargs["vector"] == DUMMY_EMBEDDING
    assert call_kwargs["payload"]["layer"] == "memory"


@pytest.mark.asyncio
async def test_remember_embedding_failure_does_not_fail_write(
    mock_mcp_context, mock_context_service
):
    """_context_remember should return the node_id even when embedding fails."""
    mock_vector_store = AsyncMock()
    mock_vector_store.upsert = AsyncMock(side_effect=RuntimeError("qdrant down"))
    mock_context_service.vector_store = mock_vector_store

    with patch(
        "context_service.mcp.tools.context_store.embed",
        new=AsyncMock(return_value=DUMMY_EMBEDDING),
    ):
        result = await _context_remember(
            silo_id=None,
            content="Test observation",
        )

    assert "node_id" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_remember_embed_exception_does_not_fail_write(
    mock_mcp_context, mock_context_service
):
    """_context_remember should return the node_id even when embed() raises."""
    mock_context_service.vector_store = AsyncMock()

    with patch(
        "context_service.mcp.tools.context_store.embed",
        new=AsyncMock(side_effect=RuntimeError("embedding service down")),
    ):
        result = await _context_remember(
            silo_id=None,
            content="Test observation",
        )

    assert "node_id" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_assert_upserts_embedding_to_qdrant(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """_context_assert should embed claim text and upsert to Qdrant after node creation."""
    mock_vector_store = AsyncMock()
    mock_vector_store.upsert = AsyncMock(return_value=True)
    mock_context_service.vector_store = mock_vector_store
    mock_context_service.graph_store.execute_query = AsyncMock(return_value=[])

    with (
        patch(
            "context_service.mcp.tools.context_store.embed",
            new=AsyncMock(return_value=DUMMY_EMBEDDING),
        ) as mock_embed,
        patch(
            "context_service.mcp.tools.context_store.get_settings",
            return_value=MagicMock(
                contradiction_flagging_enabled=False,
                affinity_computation_enabled=False,
            ),
        ),
    ):
        result = await _context_assert(
            silo_id=None,
            claim="The sky is blue",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            source_type="document",
            confidence=0.9,
        )

    assert "node_id" in result
    assert result.get("error") is None

    mock_embed.assert_called_once_with("The sky is blue")
    mock_vector_store.upsert.assert_called_once()

    call_kwargs = mock_vector_store.upsert.call_args.kwargs
    assert call_kwargs["node_id"] == result["node_id"]
    assert call_kwargs["vector"] == DUMMY_EMBEDDING
    assert call_kwargs["payload"]["layer"] == "knowledge"


@pytest.mark.asyncio
async def test_assert_embedding_failure_does_not_fail_write(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """_context_assert should return node_id even when embedding or upsert fails."""
    mock_vector_store = AsyncMock()
    mock_vector_store.upsert = AsyncMock(side_effect=RuntimeError("qdrant down"))
    mock_context_service.vector_store = mock_vector_store
    mock_context_service.graph_store.execute_query = AsyncMock(return_value=[])

    with (
        patch(
            "context_service.mcp.tools.context_store.embed",
            new=AsyncMock(return_value=DUMMY_EMBEDDING),
        ),
        patch(
            "context_service.mcp.tools.context_store.get_settings",
            return_value=MagicMock(
                contradiction_flagging_enabled=False,
                affinity_computation_enabled=False,
            ),
        ),
    ):
        result = await _context_assert(
            silo_id=None,
            claim="The sky is blue",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            source_type="document",
            confidence=0.9,
        )

    assert "node_id" in result
    assert "error" not in result

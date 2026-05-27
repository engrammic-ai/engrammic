# tests/mcp/tools/test_context_store_affinity.py
"""Integration tests: affinity computation wired into the Knowledge store flow."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.context_store import _context_assert
from context_service.services.models import derive_silo_id

NODE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
NEIGHBOUR_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
DUMMY_EMBEDDING = [0.1] * 768
# mock_mcp_auth_context uses org_id="test-org"; derive_silo_id produces the silo UUID
EXPECTED_SILO_ID = str(derive_silo_id("test-org"))


@pytest.mark.asyncio
async def test_store_knowledge_computes_and_stores_affinities(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """Storing a Knowledge node should trigger affinity computation and edge storage."""
    from context_service.engine.affinity import AffinityEdge

    affinity_edge = AffinityEdge(
        source_id=NODE_ID,
        target_id=NEIGHBOUR_ID,
        similarity=0.92,
        source_embedding_model="openai/text-embedding-3-small",
    )

    # graph_store returns the node's embedding on query
    mock_context_service.graph_store.execute_query = AsyncMock(
        return_value=[{"embedding": DUMMY_EMBEDDING}]
    )

    # mock the raw qdrant client returned by _qdrant._get_client()
    mock_raw_qdrant = MagicMock()

    mock_context_service._qdrant = MagicMock()
    mock_context_service._qdrant._get_client = AsyncMock(return_value=mock_raw_qdrant)

    with (
        patch(
            "context_service.engine.affinity.compute_affinities",
            new=AsyncMock(return_value=[affinity_edge]),
        ) as mock_compute,
        patch(
            "context_service.engine.affinity.store_affinity_edges",
            new=AsyncMock(),
        ) as mock_store_edges,
        patch(
            "context_service.mcp.tools.context_store.get_settings",
            return_value=MagicMock(
                contradiction_flagging_enabled=False,
                affinity_computation_enabled=True,
                litellm_embedding_model="openai/text-embedding-3-small",
            ),
        ),
    ):
        result = await _context_assert(
            silo_id=None,
            claim="Integration test claim",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            source_type="document",
            confidence=0.9,
        )

    assert "node_id" in result, f"Expected node_id in result, got: {result}"
    mock_compute.assert_called_once()
    mock_store_edges.assert_called_once()

    # Verify compute_affinities received the right args
    call_kwargs = mock_compute.call_args.kwargs
    assert call_kwargs["source_id"] == NODE_ID
    assert call_kwargs["embedding"] == DUMMY_EMBEDDING
    assert call_kwargs["silo_id"] == EXPECTED_SILO_ID
    assert call_kwargs["collection_name"] == f"ctx_{EXPECTED_SILO_ID}"


@pytest.mark.asyncio
async def test_store_knowledge_skips_affinity_when_disabled(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """Affinity computation should be skipped when the feature flag is off."""
    mock_context_service.graph_store.execute_query = AsyncMock(
        return_value=[{"embedding": DUMMY_EMBEDDING}]
    )

    with (
        patch(
            "context_service.engine.affinity.compute_affinities",
            new=AsyncMock(return_value=[]),
        ) as mock_compute,
        patch(
            "context_service.mcp.tools.context_store.get_settings",
            return_value=MagicMock(
                contradiction_flagging_enabled=False,
                affinity_computation_enabled=False,
                litellm_embedding_model="openai/text-embedding-3-small",
            ),
        ),
    ):
        result = await _context_assert(
            silo_id=None,
            claim="Disabled affinity test claim",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            source_type="document",
            confidence=0.8,
        )

    assert "node_id" in result
    mock_compute.assert_not_called()


@pytest.mark.asyncio
async def test_store_knowledge_affinity_failure_is_non_blocking(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """A failure in affinity computation must not block the store response."""
    mock_context_service.graph_store.execute_query = AsyncMock(
        return_value=[{"embedding": DUMMY_EMBEDDING}]
    )
    mock_context_service._qdrant = MagicMock()
    mock_context_service._qdrant._get_client = AsyncMock(side_effect=RuntimeError("qdrant down"))

    with patch(
        "context_service.mcp.tools.context_store.get_settings",
        return_value=MagicMock(
            contradiction_flagging_enabled=False,
            affinity_computation_enabled=True,
            litellm_embedding_model="openai/text-embedding-3-small",
        ),
    ):
        result = await _context_assert(
            silo_id=None,
            claim="Non-blocking affinity failure claim",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            source_type="document",
            confidence=0.8,
        )

    # Store must succeed despite affinity failure
    assert "node_id" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_store_knowledge_skips_affinity_when_no_embedding(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """No embedding in graph means affinity computation is skipped gracefully."""
    # graph_store returns no embedding
    mock_context_service.graph_store.execute_query = AsyncMock(return_value=[])

    with (
        patch(
            "context_service.engine.affinity.compute_affinities",
            new=AsyncMock(return_value=[]),
        ) as mock_compute,
        patch(
            "context_service.mcp.tools.context_store.get_settings",
            return_value=MagicMock(
                contradiction_flagging_enabled=False,
                affinity_computation_enabled=True,
                litellm_embedding_model="openai/text-embedding-3-small",
            ),
        ),
    ):
        result = await _context_assert(
            silo_id=None,
            claim="No-embedding affinity test claim",
            evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
            source_type="document",
            confidence=0.8,
        )

    assert "node_id" in result
    mock_compute.assert_not_called()

# tests/engine/test_epistemic_store.py
"""Tests for MemgraphEpistemicStore."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_graph_store():
    """Mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_query = AsyncMock()
    store.execute_write = AsyncMock()

    # Mock transaction context manager
    tx = AsyncMock()
    tx.execute_write = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    store.transaction = MagicMock(return_value=tx)

    return store


class TestMemgraphEpistemicStore:
    """Tests for MemgraphEpistemicStore implementation."""

    @pytest.mark.asyncio
    async def test_get_fact_cluster(self, mock_graph_store):
        """Should query facts in cluster."""
        mock_graph_store.execute_query.return_value = [
            {"id": "fact-1", "content": "fact content", "confidence": 0.9},
        ]

        from context_service.engine.epistemic_store import MemgraphEpistemicStore

        store = MemgraphEpistemicStore(mock_graph_store)
        result = await store.get_fact_cluster("silo-1", "cluster-1")

        assert len(result) == 1
        assert result[0]["id"] == "fact-1"
        mock_graph_store.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_unclustered_facts(self, mock_graph_store):
        """Should query unclustered facts with limit."""
        mock_graph_store.execute_query.return_value = [
            {"id": "fact-1", "content": "content", "confidence": 0.8},
        ]

        from context_service.engine.epistemic_store import MemgraphEpistemicStore

        store = MemgraphEpistemicStore(mock_graph_store)
        result = await store.get_unclustered_facts("silo-1", limit=50)

        assert len(result) == 1
        call_args = mock_graph_store.execute_query.call_args
        assert call_args[0][1]["limit"] == 50

    @pytest.mark.asyncio
    async def test_create_belief_with_links_atomic(self, mock_graph_store):
        """Should create belief and links in transaction."""
        tx = mock_graph_store.transaction.return_value
        tx.__aenter__.return_value = tx
        tx.execute_write.return_value = [{"id": "belief-123"}]

        from context_service.engine.epistemic_store import MemgraphEpistemicStore

        store = MemgraphEpistemicStore(mock_graph_store)
        result = await store.create_belief_with_links(
            silo_id="silo-1",
            content="synthesized belief",
            fact_ids=["fact-1", "fact-2"],
            confidence=0.85,
        )

        assert result == "belief-123"
        # Should have called execute_write twice (create + link)
        assert tx.execute_write.call_count == 2

    @pytest.mark.asyncio
    async def test_update_belief_centroid_noop_without_client(self, mock_graph_store):
        """Should no-op when embedding_client is None."""
        from context_service.engine.epistemic_store import MemgraphEpistemicStore

        store = MemgraphEpistemicStore(mock_graph_store)
        await store.update_belief_centroid("silo-1", "belief-1", embedding_client=None)

        # Should not query anything
        mock_graph_store.execute_query.assert_not_called()
        mock_graph_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_mark_belief_stale(self, mock_graph_store):
        """Should mark belief as stale with reason."""
        from context_service.engine.epistemic_store import MemgraphEpistemicStore

        store = MemgraphEpistemicStore(mock_graph_store)
        await store.mark_belief_stale("silo-1", "belief-1", "merged_into:belief-2")

        mock_graph_store.execute_write.assert_called_once()
        call_args = mock_graph_store.execute_write.call_args
        assert call_args[0][1]["reason"] == "merged_into:belief-2"

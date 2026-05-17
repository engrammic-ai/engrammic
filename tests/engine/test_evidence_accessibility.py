# tests/engine/test_evidence_accessibility.py
"""Tests for evidence accessibility in chain applicability Layer 3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def mock_store():
    """Mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_query = AsyncMock()
    return store


@pytest.fixture
def mock_context_service(mock_store):
    """Mock context service with memgraph store."""
    ctx = MagicMock()
    ctx._memgraph = mock_store
    return ctx


class TestGetAccessibleEvidence:
    """Tests for get_accessible_evidence function."""

    @pytest.mark.asyncio
    async def test_returns_session_nodes(self, mock_store, mock_context_service):
        """Should return node IDs from session query."""
        mock_store.execute_query.return_value = [
            {"node_id": "node-1"},
            {"node_id": "node-2"},
        ]

        with patch(
            "context_service.engine.chain_applicability.get_context_service",
            return_value=mock_context_service,
        ):
            from context_service.engine.chain_applicability import get_accessible_evidence

            result = await get_accessible_evidence("silo-123", "session-456")

            assert result == {"node-1", "node-2"}
            mock_store.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_empty_result(self, mock_store, mock_context_service):
        """Should fallback to silo-wide when session returns empty."""
        # First call returns empty (session), second returns silo-wide
        mock_store.execute_query.side_effect = [
            [],  # session query
            [{"node_id": "fallback-1"}],  # silo-wide fallback
        ]

        with patch(
            "context_service.engine.chain_applicability.get_context_service",
            return_value=mock_context_service,
        ):
            from context_service.engine.chain_applicability import get_accessible_evidence

            result = await get_accessible_evidence("silo-123", "session-456")

            assert result == {"fallback-1"}
            assert mock_store.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self, mock_store, mock_context_service):
        """Should fallback to silo-wide on query exception."""
        mock_store.execute_query.side_effect = [
            Exception("Connection failed"),
            [{"node_id": "fallback-1"}],
        ]

        with patch(
            "context_service.engine.chain_applicability.get_context_service",
            return_value=mock_context_service,
        ):
            from context_service.engine.chain_applicability import get_accessible_evidence

            result = await get_accessible_evidence("silo-123", "session-456")

            assert result == {"fallback-1"}


class TestGetSiloWideEvidence:
    """Tests for _get_silo_wide_evidence fallback."""

    @pytest.mark.asyncio
    async def test_returns_silo_nodes(self, mock_store):
        """Should return all evidence nodes in silo."""
        mock_store.execute_query.return_value = [
            {"node_id": "node-a"},
            {"node_id": "node-b"},
            {"node_id": "node-c"},
        ]

        from context_service.engine.chain_applicability import _get_silo_wide_evidence

        result = await _get_silo_wide_evidence("silo-123", mock_store)

        assert result == {"node-a", "node-b", "node-c"}

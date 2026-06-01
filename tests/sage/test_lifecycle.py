"""Tests for Phase 4 lifecycle transactions (TX10, TX15, TX16, CASCADE_STALENESS)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    BrainError,
    CancelForgetResult,
    ForgetResult,
    HardDeleteResult,
    InvariantViolation,
    NodeState,
    tx15_forget,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_write = AsyncMock(return_value=[{"id": str(uuid.uuid4())}])
    store.execute_query = AsyncMock(return_value=[])
    return store


def make_uuid() -> str:
    """Generate a valid UUID string for tests."""
    return str(uuid.uuid4())


class TestTx15Forget:
    """Tests for TX15 FORGET."""

    @pytest.mark.asyncio
    async def test_tombstones_active_node(self, mock_store: AsyncMock) -> None:
        """Test that TX15 tombstones an active node."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "ACTIVE", "layer": "memory", "cancel_window_expires": None}
        ])
        mock_store.execute_write = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED"}
        ])

        result, events = await tx15_forget(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, ForgetResult)
        assert result.state == NodeState.TOMBSTONED
        assert result.cancel_window_expires > datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_rejects_already_tombstoned(self, mock_store: AsyncMock) -> None:
        """Test that TX15 rejects already tombstoned nodes."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED", "layer": "memory", "cancel_window_expires": None}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx15_forget(
                store=mock_store,
                node_id=node_id,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "ALREADY_TOMBSTONED"

    @pytest.mark.asyncio
    async def test_rejects_missing_node(self, mock_store: AsyncMock) -> None:
        """Test that TX15 rejects non-existent nodes."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx15_forget(
                store=mock_store,
                node_id=make_uuid(),
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NODE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cascades_to_dependents(self, mock_store: AsyncMock) -> None:
        """Test that TX15 with cascade=True triggers CASCADE_STALENESS."""
        node_id = make_uuid()
        dependent_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_NODE_FOR_FORGET
            [{"id": node_id, "state": "ACTIVE", "layer": "knowledge", "cancel_window_expires": None}],
            # GET_DEPENDENTS_FOR_CASCADE
            [{"id": dependent_id, "layer": "wisdom", "edge_type": "SYNTHESIZED_FROM"}],
        ])
        mock_store.execute_write = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED"}
        ])

        result, events = await tx15_forget(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            agent_id="test-agent",
            cascade=True,
        )

        assert result.cascade_count >= 1

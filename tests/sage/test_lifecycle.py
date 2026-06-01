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
    MAX_CASCADE_DEPTH,
    cascade_staleness,
    tx10_hard_delete,
    tx15_forget,
    tx16_cancel_forget,
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


class TestTx16CancelForget:
    """Tests for TX16 CANCEL_FORGET."""

    @pytest.mark.asyncio
    async def test_restores_tombstoned_node(self, mock_store: AsyncMock) -> None:
        """Test that TX16 restores a tombstoned node within cancel window."""
        node_id = make_uuid()
        future_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED", "cancel_window_expires": future_time}
        ])
        mock_store.execute_write = AsyncMock(return_value=[
            {"id": node_id, "state": "ACTIVE", "previous_state": "ACTIVE"}
        ])

        result = await tx16_cancel_forget(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, CancelForgetResult)
        assert result.previous_state == NodeState.ACTIVE

    @pytest.mark.asyncio
    async def test_rejects_expired_window(self, mock_store: AsyncMock) -> None:
        """Test that TX16 rejects nodes past cancel window."""
        node_id = make_uuid()
        past_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED", "cancel_window_expires": past_time}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx16_cancel_forget(
                store=mock_store,
                node_id=node_id,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "CANCEL_WINDOW_EXPIRED"

    @pytest.mark.asyncio
    async def test_rejects_non_tombstoned(self, mock_store: AsyncMock) -> None:
        """Test that TX16 rejects non-tombstoned nodes."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "ACTIVE", "cancel_window_expires": None}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx16_cancel_forget(
                store=mock_store,
                node_id=node_id,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NOT_TOMBSTONED"


class TestCascadeStaleness:
    """Tests for CASCADE_STALENESS helper."""

    @pytest.mark.asyncio
    async def test_marks_dependent_beliefs_stale(self, mock_store: AsyncMock) -> None:
        """Test that cascade marks dependent wisdom-layer nodes as stale."""
        node_id = make_uuid()
        belief_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": belief_id, "layer": "wisdom", "edge_type": "SYNTHESIZED_FROM"}
        ])

        count = await cascade_staleness(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            depth=1,
        )

        assert count >= 1
        mock_store.execute_write.assert_called()

    @pytest.mark.asyncio
    async def test_respects_depth_limit(self, mock_store: AsyncMock) -> None:
        """Test that cascade stops at MAX_CASCADE_DEPTH."""
        node_id = make_uuid()

        count = await cascade_staleness(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            depth=MAX_CASCADE_DEPTH + 1,
        )

        assert count == 0
        mock_store.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicates_visited_nodes(self, mock_store: AsyncMock) -> None:
        """Test that cascade doesn't revisit already-visited nodes."""
        node_id = make_uuid()
        visited = {node_id}

        count = await cascade_staleness(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            depth=1,
            visited=visited,
        )

        assert count == 0


class TestTx10HardDelete:
    """Tests for TX10 HARD_DELETE."""

    @pytest.mark.asyncio
    async def test_deletes_expired_tombstoned_nodes(self, mock_store: AsyncMock) -> None:
        """Test that TX10 deletes nodes past cancel window."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id}
        ])
        mock_store.execute_write = AsyncMock(return_value=[{"deleted_count": 1}])

        result = await tx10_hard_delete(
            store=mock_store,
            silo_id="test-silo",
            batch_size=100,
        )

        assert isinstance(result, HardDeleteResult)
        assert result.deleted_count >= 1

    @pytest.mark.asyncio
    async def test_skips_unexpired_nodes(self, mock_store: AsyncMock) -> None:
        """Test that TX10 skips nodes still in cancel window."""
        mock_store.execute_query = AsyncMock(return_value=[])

        result = await tx10_hard_delete(
            store=mock_store,
            silo_id="test-silo",
            batch_size=100,
        )

        assert result.deleted_count == 0
        assert result.skipped_count == 0

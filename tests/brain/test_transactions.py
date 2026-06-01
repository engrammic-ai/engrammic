"""Tests for brain transactions (TX0, TX2, TX3, TX17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.brain.transactions import (
    BrainError,
    CrossSiloViolation,
    CycleError,
    InvariantViolation,
    LinkType,
    NodeState,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeReason,
    tx0_store_memory,
    tx2_store_claim,
    tx3_supersede,
    tx17_link,
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


class TestTx0StoreMemory:
    """Tests for TX0 STORE_MEMORY."""

    @pytest.mark.asyncio
    async def test_basic_store(self, mock_store: AsyncMock) -> None:
        """Test basic memory storage."""
        result, events = await tx0_store_memory(
            store=mock_store,
            content="Test observation",
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, StoreMemoryResult)
        assert result.layer == "memory"
        assert result.state == NodeState.ACTIVE
        assert isinstance(result.node_id, uuid.UUID)
        assert isinstance(result.created_at, datetime)

        mock_store.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_emits_compute_embedding_event(self, mock_store: AsyncMock) -> None:
        """Test that compute_embedding event is emitted."""
        result, events = await tx0_store_memory(
            store=mock_store,
            content="Test",
            silo_id="test-silo",
            agent_id="test-agent",
        )

        event_types = [e.event_type for e in events]
        assert "compute_embedding" in event_types

    @pytest.mark.asyncio
    async def test_emits_update_heat_event(self, mock_store: AsyncMock) -> None:
        """Test that update_heat event is emitted."""
        result, events = await tx0_store_memory(
            store=mock_store,
            content="Test",
            silo_id="test-silo",
            agent_id="test-agent",
        )

        heat_events = [e for e in events if e.event_type == "update_heat"]
        assert len(heat_events) == 1
        assert heat_events[0].payload["access_type"] == "WRITE"

    @pytest.mark.asyncio
    async def test_long_content_triggers_extraction_check(self, mock_store: AsyncMock) -> None:
        """Test that long content triggers extraction check event."""
        long_content = "x" * 600  # Over _EXTRACTION_THRESHOLD (500)

        result, events = await tx0_store_memory(
            store=mock_store,
            content=long_content,
            silo_id="test-silo",
            agent_id="test-agent",
        )

        event_types = [e.event_type for e in events]
        assert "check_extraction_trigger" in event_types

    @pytest.mark.asyncio
    async def test_with_tags(self, mock_store: AsyncMock) -> None:
        """Test storage with tags."""
        result, events = await tx0_store_memory(
            store=mock_store,
            content="Test",
            silo_id="test-silo",
            agent_id="test-agent",
            tags=["tag1", "tag2"],
        )

        assert isinstance(result, StoreMemoryResult)
        call_args = mock_store.execute_write.call_args
        assert "tag1" in str(call_args)


class TestTx2StoreClaim:
    """Tests for TX2 STORE_CLAIM."""

    @pytest.mark.asyncio
    async def test_rejects_empty_evidence(self, mock_store: AsyncMock) -> None:
        """Test that empty evidence is rejected (INV2)."""
        with pytest.raises(InvariantViolation) as exc_info:
            await tx2_store_claim(
                store=mock_store,
                content="Test claim",
                evidence_refs=[],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NO_EVIDENCE"

    @pytest.mark.asyncio
    async def test_validates_evidence_exists(self, mock_store: AsyncMock) -> None:
        """Test that missing evidence is rejected."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx2_store_claim(
                store=mock_store,
                content="Test claim",
                evidence_refs=["node:12345678-1234-1234-1234-123456789abc"],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "EVIDENCE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_validates_evidence_same_silo(self, mock_store: AsyncMock) -> None:
        """Test that cross-silo evidence is rejected (INV5)."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "12345678-1234-1234-1234-123456789abc",
                    "silo_id": "other-silo",
                    "layer": "memory",
                    "state": "ACTIVE",
                }
            ]
        )

        with pytest.raises(InvariantViolation) as exc_info:
            await tx2_store_claim(
                store=mock_store,
                content="Test claim",
                evidence_refs=["node:12345678-1234-1234-1234-123456789abc"],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "CROSS_SILO_VIOLATION"

    @pytest.mark.asyncio
    async def test_validates_memory_layer_evidence(self, mock_store: AsyncMock) -> None:
        """Test that at least one evidence must be from Memory layer (INV2)."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "12345678-1234-1234-1234-123456789abc",
                    "silo_id": "test-silo",
                    "layer": "knowledge",  # Not memory!
                    "state": "ACTIVE",
                }
            ]
        )

        with pytest.raises(InvariantViolation) as exc_info:
            await tx2_store_claim(
                store=mock_store,
                content="Test claim",
                evidence_refs=["node:12345678-1234-1234-1234-123456789abc"],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NO_MEMORY_EVIDENCE"

    @pytest.mark.asyncio
    async def test_basic_store_with_valid_evidence(self, mock_store: AsyncMock) -> None:
        """Test successful claim storage with valid evidence."""
        evidence_id = "12345678-1234-1234-1234-123456789abc"
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": evidence_id,
                    "silo_id": "test-silo",
                    "layer": "memory",
                    "state": "ACTIVE",
                }
            ]
        )

        result, events = await tx2_store_claim(
            store=mock_store,
            content="Test claim",
            evidence_refs=[f"node:{evidence_id}"],
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, StoreClaimResult)
        assert result.layer == "knowledge"
        assert result.state == NodeState.ACTIVE


class TestTx3Supersede:
    """Tests for TX3 SUPERSEDE."""

    @pytest.mark.asyncio
    async def test_validates_nodes_exist(self, mock_store: AsyncMock) -> None:
        """Test that missing nodes are rejected."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(BrainError) as exc_info:
            await tx3_supersede(
                store=mock_store,
                winner_id=make_uuid(),
                loser_id=make_uuid(),
                silo_id="test-silo",
                reason=SupersedeReason.AUTHOR_UPDATE,
            )

        assert exc_info.value.code == "NODE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_validates_same_silo(self, mock_store: AsyncMock) -> None:
        """Test that cross-silo supersession is rejected (INV5)."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "winner_silo": "test-silo",
                    "loser_silo": "other-silo",
                    "winner_state": "ACTIVE",
                    "loser_state": "ACTIVE",
                }
            ]
        )

        with pytest.raises(CrossSiloViolation):
            await tx3_supersede(
                store=mock_store,
                winner_id=make_uuid(),
                loser_id=make_uuid(),
                silo_id="test-silo",
                reason=SupersedeReason.CONTRADICTION,
            )

    @pytest.mark.asyncio
    async def test_validates_winner_active(self, mock_store: AsyncMock) -> None:
        """Test that non-active winner is rejected."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "winner_silo": "test-silo",
                    "loser_silo": "test-silo",
                    "winner_state": "SUPERSEDED",
                    "loser_state": "ACTIVE",
                }
            ]
        )

        with pytest.raises(BrainError) as exc_info:
            await tx3_supersede(
                store=mock_store,
                winner_id=make_uuid(),
                loser_id=make_uuid(),
                silo_id="test-silo",
                reason=SupersedeReason.AUTHOR_UPDATE,
            )

        assert exc_info.value.code == "WINNER_NOT_ACTIVE"

    @pytest.mark.asyncio
    async def test_detects_cycle(self, mock_store: AsyncMock) -> None:
        """Test that cycles are detected (INV4)."""

        async def mock_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            if "SUPERSEDES" in cypher and "*" in cypher:
                return [{"would_cycle": True}]
            return [
                {
                    "winner_silo": "test-silo",
                    "loser_silo": "test-silo",
                    "winner_state": "ACTIVE",
                    "loser_state": "ACTIVE",
                }
            ]

        mock_store.execute_query = AsyncMock(side_effect=mock_query)

        with pytest.raises(CycleError):
            await tx3_supersede(
                store=mock_store,
                winner_id=make_uuid(),
                loser_id=make_uuid(),
                silo_id="test-silo",
                reason=SupersedeReason.CONTRADICTION,
            )


class TestTx17Link:
    """Tests for TX17 LINK."""

    @pytest.mark.asyncio
    async def test_validates_nodes_exist(self, mock_store: AsyncMock) -> None:
        """Test that missing nodes are rejected."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(BrainError) as exc_info:
            await tx17_link(
                store=mock_store,
                source_id=make_uuid(),
                target_id=make_uuid(),
                edge_type=LinkType.RELATED_TO,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NODE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_validates_same_silo(self, mock_store: AsyncMock) -> None:
        """Test that cross-silo links are rejected (INV5)."""
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "source_silo": "test-silo",
                    "target_silo": "other-silo",
                    "source_state": "ACTIVE",
                    "target_state": "ACTIVE",
                }
            ]
        )

        with pytest.raises(CrossSiloViolation):
            await tx17_link(
                store=mock_store,
                source_id=make_uuid(),
                target_id=make_uuid(),
                edge_type=LinkType.SUPPORTS,
                silo_id="test-silo",
                agent_id="test-agent",
            )

    @pytest.mark.asyncio
    async def test_rejects_duplicate_edge(self, mock_store: AsyncMock) -> None:
        """Test that duplicate edges are rejected."""

        async def mock_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            if "RELATED_TO" in cypher:
                return [{"existing_id": "existing-edge-id"}]
            return [
                {
                    "source_silo": "test-silo",
                    "target_silo": "test-silo",
                    "source_state": "ACTIVE",
                    "target_state": "ACTIVE",
                }
            ]

        mock_store.execute_query = AsyncMock(side_effect=mock_query)

        with pytest.raises(BrainError) as exc_info:
            await tx17_link(
                store=mock_store,
                source_id=make_uuid(),
                target_id=make_uuid(),
                edge_type=LinkType.RELATED_TO,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "DUPLICATE_EDGE"

    @pytest.mark.asyncio
    async def test_contradicts_emits_flag_event(self, mock_store: AsyncMock) -> None:
        """Test that CONTRADICTS link emits flag_contradiction event."""
        source_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())

        async def mock_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            if "CONTRADICTS" in cypher:
                return []  # No duplicate
            return [
                {
                    "source_silo": "test-silo",
                    "target_silo": "test-silo",
                    "source_state": "ACTIVE",
                    "target_state": "ACTIVE",
                }
            ]

        mock_store.execute_query = AsyncMock(side_effect=mock_query)

        result, events = await tx17_link(
            store=mock_store,
            source_id=source_id,
            target_id=target_id,
            edge_type=LinkType.CONTRADICTS,
            silo_id="test-silo",
            agent_id="test-agent",
        )

        flag_events = [e for e in events if e.event_type == "flag_contradiction"]
        assert len(flag_events) == 1
        assert flag_events[0].payload["contradicting_node_id"] == target_id

    @pytest.mark.asyncio
    async def test_hierarchical_edge_cycle_detection(self, mock_store: AsyncMock) -> None:
        """Test cycle detection for hierarchical edge types."""

        async def mock_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            if "REFINES" in cypher and "*" in cypher:
                return [{"would_cycle": True}]
            if "REFINES" in cypher:
                return []  # No duplicate
            return [
                {
                    "source_silo": "test-silo",
                    "target_silo": "test-silo",
                    "source_state": "ACTIVE",
                    "target_state": "ACTIVE",
                }
            ]

        mock_store.execute_query = AsyncMock(side_effect=mock_query)

        with pytest.raises(CycleError):
            await tx17_link(
                store=mock_store,
                source_id=make_uuid(),
                target_id=make_uuid(),
                edge_type=LinkType.REFINES,
                silo_id="test-silo",
                agent_id="test-agent",
            )

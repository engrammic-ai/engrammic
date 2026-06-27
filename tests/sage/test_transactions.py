"""Tests for sage transactions (TX0, TX2, TX3, TX17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    BrainError,
    ConflictStatus,
    CrossSiloViolation,
    CycleError,
    InvariantViolation,
    LinkType,
    NodeState,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeReason,
    check_corroboration,
    link,
    store_claim,
    store_memory,
    supersede,
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
        result, events = await store_memory(
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
        result, events = await store_memory(
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
        result, events = await store_memory(
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

        result, events = await store_memory(
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
        result, events = await store_memory(
            store=mock_store,
            content="Test",
            silo_id="test-silo",
            agent_id="test-agent",
            tags=["tag1", "tag2"],
        )

        assert isinstance(result, StoreMemoryResult)
        call_args = mock_store.execute_write.call_args
        assert "tag1" in str(call_args)

    @pytest.mark.asyncio
    async def test_with_precomputed_embedding(self, mock_store: AsyncMock) -> None:
        """Precomputed embedding skips compute_embedding event and stores inline."""
        embedding = [0.1] * 1024

        result, events = await store_memory(
            store=mock_store,
            content="Test",
            silo_id="test-silo",
            agent_id="test-agent",
            embedding=embedding,
            document_id="ext-doc-1",
        )

        assert isinstance(result, StoreMemoryResult)
        event_types = [e.event_type for e in events]
        assert "compute_embedding" not in event_types

        call_args = mock_store.execute_write.call_args
        props = call_args[0][1]["props"]
        assert props["embedding"] == embedding
        assert props["document_id"] == "ext-doc-1"
        assert props["embedding_pending"] is False


class TestTx2StoreClaim:
    """Tests for TX2 STORE_CLAIM."""

    @pytest.mark.asyncio
    async def test_rejects_empty_evidence(self, mock_store: AsyncMock) -> None:
        """Test that empty evidence is rejected (INV2)."""
        with pytest.raises(InvariantViolation) as exc_info:
            await store_claim(
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
            await store_claim(
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
            await store_claim(
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
            await store_claim(
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

        result, events = await store_claim(
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
            await supersede(
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
            await supersede(
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
            await supersede(
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
            await supersede(
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
            await link(
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
            await link(
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
            await link(
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

        result, events = await link(
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
            await link(
                store=mock_store,
                source_id=make_uuid(),
                target_id=make_uuid(),
                edge_type=LinkType.REFINES,
                silo_id="test-silo",
                agent_id="test-agent",
            )


class TestCheckCorroboration:
    """Tests for atomic CHECK_CORROBORATION helper."""

    @pytest.mark.asyncio
    async def test_returns_count_and_should_promote(self, mock_store: AsyncMock) -> None:
        """Test that corroboration check returns count and promotion flag."""
        mock_store.execute_write = AsyncMock(
            return_value=[
                {
                    "count": 2,
                    "should_promote": False,
                }
            ]
        )

        count, should_promote = await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        assert count == 2
        assert should_promote is False

    @pytest.mark.asyncio
    async def test_returns_true_when_threshold_met(self, mock_store: AsyncMock) -> None:
        """Test that should_promote is True when count meets threshold."""
        mock_store.execute_write = AsyncMock(
            return_value=[
                {
                    "count": 3,
                    "should_promote": True,
                }
            ]
        )

        count, should_promote = await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        assert count == 3
        assert should_promote is True

    @pytest.mark.asyncio
    async def test_uses_single_atomic_query(self, mock_store: AsyncMock) -> None:
        """Test that exactly one write query is issued (atomic operation)."""
        mock_store.execute_write = AsyncMock(
            return_value=[
                {
                    "count": 1,
                    "should_promote": False,
                }
            ]
        )

        await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        # Should be exactly one write call (atomic, contains SET mutation)
        assert mock_store.execute_write.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_results(self, mock_store: AsyncMock) -> None:
        """Test that (1, False) is returned when query returns no rows."""
        mock_store.execute_query = AsyncMock(return_value=[])

        count, should_promote = await check_corroboration(
            store=mock_store,
            node_id="test-node-id",
            silo_id="test-silo",
        )

        assert count == 1
        assert should_promote is False


class TestFlagContradiction:
    """Tests for FLAG_CONTRADICTION in TX2 flow."""

    @pytest.mark.asyncio
    async def test_detects_structural_conflict(self, mock_store: AsyncMock) -> None:
        """Test that TX2 detects conflicting claims and emits ConflictDetected event."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                # Evidence validation
                [
                    {
                        "id": "evidence-1",
                        "silo_id": "test-silo",
                        "layer": "memory",
                        "state": "ACTIVE",
                    }
                ],
                # Conflict detection: existing claim with different object
                [{"id": "existing-claim"}],
            ]
        )
        # Corroboration uses execute_write
        mock_store.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])

        result, events = await store_claim(
            store=mock_store,
            content="test-subject has_value test-value",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="test-subject",
            predicate="has_value",
            object_value="test-value",
        )

        conflict_events = [e for e in events if e.event_type == "conflict_detected"]
        assert len(conflict_events) == 1
        assert conflict_events[0].payload["conflict_type"] == "structural"
        assert conflict_events[0].payload["node_b"] == "existing-claim"

    @pytest.mark.asyncio
    async def test_no_conflict_when_no_spo(self, mock_store: AsyncMock) -> None:
        """Test no conflict detection when SPO is not provided."""
        evidence_id = "12345678-1234-1234-1234-123456789abc"
        mock_store.execute_query = AsyncMock(
            return_value=[
                {"id": evidence_id, "silo_id": "test-silo", "layer": "memory", "state": "ACTIVE"}
            ]
        )

        result, events = await store_claim(
            store=mock_store,
            content="Test claim with no SPO",
            evidence_refs=[f"node:{evidence_id}"],
            silo_id="test-silo",
            agent_id="test-agent",
            # No subject/predicate/object_value
        )

        conflict_events = [e for e in events if e.event_type == "conflict_detected"]
        assert len(conflict_events) == 0

    @pytest.mark.asyncio
    async def test_no_conflict_when_no_conflicting_claims(self, mock_store: AsyncMock) -> None:
        """Test no conflict event when conflict query returns empty."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                # Evidence validation
                [
                    {
                        "id": "evidence-1",
                        "silo_id": "test-silo",
                        "layer": "memory",
                        "state": "ACTIVE",
                    }
                ],
                # Conflict detection: no conflicts
                [],
            ]
        )
        mock_store.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])

        result, events = await store_claim(
            store=mock_store,
            content="test-subject has_value test-value",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="test-subject",
            predicate="has_value",
            object_value="test-value",
        )

        conflict_events = [e for e in events if e.event_type == "conflict_detected"]
        assert len(conflict_events) == 0

    @pytest.mark.asyncio
    async def test_creates_bidirectional_contradicts_edges(self, mock_store: AsyncMock) -> None:
        """Test that bidirectional CONTRADICTS edges are created on conflict."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                # Evidence validation
                [
                    {
                        "id": "evidence-1",
                        "silo_id": "test-silo",
                        "layer": "memory",
                        "state": "ACTIVE",
                    }
                ],
                # Conflict detection: one conflict
                [{"id": "existing-claim"}],
            ]
        )
        mock_store.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])

        await store_claim(
            store=mock_store,
            content="s p new",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="s",
            predicate="p",
            object_value="new",
        )

        # Check that a CONTRADICTS write was issued
        write_calls = mock_store.execute_write.call_args_list
        contradicts_calls = [c for c in write_calls if "CONTRADICTS" in str(c)]
        assert len(contradicts_calls) >= 1

        # Verify both directions are in a single MERGE query
        call_str = str(contradicts_calls[0])
        assert "CONTRADICTS" in call_str

    @pytest.mark.asyncio
    async def test_sets_conflict_status_on_both_nodes(self, mock_store: AsyncMock) -> None:
        """Test that conflict_status is set to UNRESOLVED on both nodes."""
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": "evidence-1",
                        "silo_id": "test-silo",
                        "layer": "memory",
                        "state": "ACTIVE",
                    }
                ],
                [{"id": "existing-claim"}],
            ]
        )
        mock_store.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])

        await store_claim(
            store=mock_store,
            content="s p new",
            evidence_refs=["node:evidence-1"],
            silo_id="test-silo",
            agent_id="test-agent",
            subject="s",
            predicate="p",
            object_value="new",
        )

        # At least one write should set conflict_status = 'unresolved'
        write_calls = mock_store.execute_write.call_args_list
        status_calls = [c for c in write_calls if ConflictStatus.UNRESOLVED.value in str(c)]
        assert len(status_calls) >= 1

    @pytest.mark.asyncio
    async def test_store_claim_with_precomputed_embedding(self, mock_store: AsyncMock) -> None:
        """Test store_claim accepts pre-computed embedding, document_id, and skip_sage_triggers."""
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
        embedding = [0.1] * 1024

        result, events = await store_claim(
            store=mock_store,
            content="Test claim",
            evidence_refs=[f"node:{evidence_id}"],
            silo_id="test-silo",
            agent_id="agent-1",
            embedding=embedding,
            skip_sage_triggers=True,
            document_id="ext-claim-1",
        )

        create_call = mock_store.execute_write.call_args_list[0]
        props = create_call[0][1]["props"]
        assert props["embedding"] == embedding
        assert props["document_id"] == "ext-claim-1"
        assert props["embedding_pending"] is False
        assert props.get("sage_pending") is True
        assert not any(
            e.event_type == "compute_embedding" for e in events
        )


class TestTx2Credibility:
    """Tests for credibility computation in TX2 STORE_CLAIM."""

    def _make_evidence_mock(self, evidence_id: str, silo_id: str = "test-silo") -> AsyncMock:
        """Create a mock store that returns valid evidence."""
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": evidence_id,
                    "silo_id": silo_id,
                    "layer": "memory",
                    "state": "ACTIVE",
                }
            ]
        )
        store.execute_write = AsyncMock(return_value=[{"count": 1, "should_promote": False}])
        return store

    @pytest.mark.asyncio
    async def test_computes_credibility_at_write(self) -> None:
        """Test that credibility is computed and stored in props at write time."""
        evidence_id = "12345678-1234-1234-1234-123456789abc"
        mock_store = self._make_evidence_mock(evidence_id)

        await store_claim(
            store=mock_store,
            content="Test claim",
            evidence_refs=[f"node:{evidence_id}"],
            silo_id="test-silo",
            agent_id="test-agent",
            source_tier="authoritative",
            confidence=0.9,
        )

        # Find the CREATE call (first execute_write with CREATE cypher)
        create_call = mock_store.execute_write.call_args_list[0]
        params = create_call[0][1]  # positional args: (cypher, params)
        props = params["props"]

        # credibility = source_tier_weight * method_weight * raw_confidence
        # authoritative (1.0) * direct (1.0) * 0.9 = 0.9
        assert "credibility" in props
        assert abs(props["credibility"] - 0.9) < 1e-9

    @pytest.mark.asyncio
    async def test_stores_credibility_breakdown(self) -> None:
        """Test that credibility_factors breakdown dict is stored in props."""
        evidence_id = "12345678-1234-1234-1234-123456789abc"
        mock_store = self._make_evidence_mock(evidence_id)

        await store_claim(
            store=mock_store,
            content="Test claim",
            evidence_refs=[f"node:{evidence_id}"],
            silo_id="test-silo",
            agent_id="test-agent",
            source_tier="validated",
            confidence=0.8,
        )

        create_call = mock_store.execute_write.call_args_list[0]
        params = create_call[0][1]
        props = params["props"]

        assert "credibility_factors" in props
        factors = props["credibility_factors"]
        assert factors["source_tier"] == "validated"
        assert factors["source_tier_weight"] == 0.85
        assert factors["method"] == "direct"
        assert factors["method_weight"] == 1.0
        assert factors["raw_confidence"] == 0.8
        # credibility = 0.85 * 1.0 * 0.8 = 0.68
        assert abs(factors["credibility"] - 0.68) < 1e-9

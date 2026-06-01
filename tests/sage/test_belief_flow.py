"""Tests for Phase 3 belief flow transactions (TX4, TX5, TX8, TX14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    BrainError,
    ClusterState,
    CommitResult,
    CrystallizeResult,
    InvariantViolation,
    NodeState,
    ReviseBeliefResult,
    SynthesizeResult,
    tx4_synthesize,
    tx5_revise_belief,
    tx8_commit,
    tx14_crystallize,
)


@pytest.fixture
def mock_llm() -> AsyncMock:
    """Create a mock LLM provider."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Synthesized belief content")
    return llm


@pytest.fixture
def mock_embedder() -> AsyncMock:
    """Create a mock embedding service."""
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 768)
    return embedder


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


class TestTx4Synthesize:
    """Tests for TX4 SYNTHESIZE."""

    @pytest.mark.asyncio
    async def test_creates_belief_from_cluster(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX4 creates a belief from a ready cluster."""
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "READY", "current_belief_id": None, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.8}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx4_synthesize(
            store=mock_store,
            cluster_id=cluster_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert isinstance(result, SynthesizeResult)
        assert result.belief_id is not None
        assert result.cluster_state == ClusterState.SYNTHESIZED
        assert result.fact_count == 3
        assert not result.timed_out

    @pytest.mark.asyncio
    async def test_skips_sparse_cluster(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX4 skips clusters with fewer than SYNTHESIS_THRESHOLD facts."""
        cluster_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "READY", "current_belief_id": None, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER - only 2 facts
            [{"id": make_uuid(), "content": "Fact 1", "confidence": 0.8},
             {"id": make_uuid(), "content": "Fact 2", "confidence": 0.8}],
        ])

        result, events = await tx4_synthesize(
            store=mock_store,
            cluster_id=cluster_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.belief_id is None
        assert result.cluster_state == ClusterState.SPARSE
        mock_llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_low_confidence(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX4 skips when aggregate confidence is below threshold."""
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "READY", "current_belief_id": None, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER - low confidence facts
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.2}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx4_synthesize(
            store=mock_store,
            cluster_id=cluster_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.belief_id is None
        assert result.confidence is not None
        assert result.confidence < 0.6
        mock_llm.complete.assert_not_called()


class TestTx8Commit:
    """Tests for TX8 COMMIT."""

    @pytest.mark.asyncio
    async def test_creates_commitment_with_about_edges(self, mock_store: AsyncMock) -> None:
        """Test that TX8 creates a commitment with ABOUT edges."""
        about_ref = make_uuid()
        mock_store.execute_query = AsyncMock(return_value=[{"id": about_ref, "state": "ACTIVE"}])

        result, events = await tx8_commit(
            store=mock_store,
            content="I believe X based on evidence",
            about_refs=[about_ref],
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, CommitResult)
        assert result.silo_id == "test-silo"
        assert isinstance(result.commitment_id, uuid.UUID)
        assert isinstance(result.created_at, datetime)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_rejects_empty_about_refs(self, mock_store: AsyncMock) -> None:
        """Test that TX8 rejects empty about_refs (INV: commitment must be about something)."""
        with pytest.raises(InvariantViolation) as exc_info:
            await tx8_commit(
                store=mock_store,
                content="Belief without references",
                about_refs=[],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "EMPTY_ABOUT_REFS"

    @pytest.mark.asyncio
    async def test_rejects_tombstoned_refs(self, mock_store: AsyncMock) -> None:
        """Test that TX8 rejects tombstoned about_refs."""
        tombstoned_ref = make_uuid()
        mock_store.execute_query = AsyncMock(
            return_value=[{"id": tombstoned_ref, "state": "TOMBSTONED"}]
        )

        with pytest.raises(InvariantViolation) as exc_info:
            await tx8_commit(
                store=mock_store,
                content="Belief about tombstoned node",
                about_refs=[tombstoned_ref],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "ABOUT_REF_TOMBSTONED"

    @pytest.mark.asyncio
    async def test_rejects_missing_refs(self, mock_store: AsyncMock) -> None:
        """Test that TX8 rejects about_refs that don't exist."""
        missing_ref = make_uuid()
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx8_commit(
                store=mock_store,
                content="Belief about missing node",
                about_refs=[missing_ref],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "ABOUT_REF_NOT_FOUND"


class TestTx14Crystallize:
    """Tests for TX14 CRYSTALLIZE."""

    @pytest.mark.asyncio
    async def test_converts_hypothesis_to_commitment(self, mock_store: AsyncMock) -> None:
        """Test that TX14 converts a WorkingHypothesis to a Commitment."""
        hypothesis_id = make_uuid()
        about_ref = make_uuid()

        mock_store.execute_query = AsyncMock(
            side_effect=[
                # GET_HYPOTHESIS_FOR_CRYSTALLIZE
                [
                    {
                        "id": hypothesis_id,
                        "content": "My hypothesis",
                        "confidence": 0.9,
                        "crystallized": False,
                        "state": "ACTIVE",
                    }
                ],
                # GET_HYPOTHESIS_ABOUT_REFS
                [{"id": about_ref, "state": "ACTIVE"}],
            ]
        )

        result, events = await tx14_crystallize(
            store=mock_store,
            hypothesis_id=hypothesis_id,
            silo_id="test-silo",
            agent_id="test-agent",
            session_id="test-session",
        )

        assert isinstance(result, CrystallizeResult)
        assert result.hypothesis_id == uuid.UUID(hypothesis_id)
        assert result.silo_id == "test-silo"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_rejects_already_crystallized(self, mock_store: AsyncMock) -> None:
        """Test that TX14 rejects already crystallized hypotheses."""
        hypothesis_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": hypothesis_id,
                    "content": "Already done",
                    "confidence": 0.9,
                    "crystallized": True,
                    "state": "ACTIVE",
                }
            ]
        )

        with pytest.raises(InvariantViolation) as exc_info:
            await tx14_crystallize(
                store=mock_store,
                hypothesis_id=hypothesis_id,
                silo_id="test-silo",
                agent_id="test-agent",
                session_id="test-session",
            )

        assert exc_info.value.code == "ALREADY_CRYSTALLIZED"

    @pytest.mark.asyncio
    async def test_rejects_missing_hypothesis(self, mock_store: AsyncMock) -> None:
        """Test that TX14 rejects non-existent hypotheses."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx14_crystallize(
                store=mock_store,
                hypothesis_id=make_uuid(),
                silo_id="test-silo",
                agent_id="test-agent",
                session_id="test-session",
            )

        assert exc_info.value.code == "HYPOTHESIS_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_rejects_tombstoned_hypothesis(self, mock_store: AsyncMock) -> None:
        """Test that TX14 rejects tombstoned hypotheses."""
        hypothesis_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": hypothesis_id,
                    "content": "Deleted",
                    "confidence": 0.9,
                    "crystallized": False,
                    "state": "TOMBSTONED",
                }
            ]
        )

        with pytest.raises(InvariantViolation) as exc_info:
            await tx14_crystallize(
                store=mock_store,
                hypothesis_id=hypothesis_id,
                silo_id="test-silo",
                agent_id="test-agent",
                session_id="test-session",
            )

        assert exc_info.value.code == "HYPOTHESIS_TOMBSTONED"


class TestTx5ReviseBelief:
    """Tests for TX5 REVISE_BELIEF."""

    @pytest.mark.asyncio
    async def test_creates_new_belief_on_content_change(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX5 creates a new belief when content changes."""
        belief_id = make_uuid()
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_llm.complete = AsyncMock(return_value="New revised belief content")

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_BELIEF_FOR_REVISION
            [{"id": belief_id, "content": "Old belief", "state": "ACTIVE",
              "synthesis_state": "STALE", "source_cluster_id": cluster_id,
              "revision_in_progress": False, "confidence": 0.8}],
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "STALE", "current_belief_id": belief_id, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.8}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx5_revise_belief(
            store=mock_store,
            belief_id=belief_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert isinstance(result, ReviseBeliefResult)
        assert result.new_belief_id is not None
        assert result.old_belief_id == uuid.UUID(belief_id)
        assert result.content_changed is True
        assert result.invalidated is False

    @pytest.mark.asyncio
    async def test_skips_unchanged_content(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX5 skips creating new belief if content unchanged."""
        belief_id = make_uuid()
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_llm.complete = AsyncMock(return_value="Old belief")  # Same content

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_BELIEF_FOR_REVISION
            [{"id": belief_id, "content": "Old belief", "state": "ACTIVE",
              "synthesis_state": "STALE", "source_cluster_id": cluster_id,
              "revision_in_progress": False, "confidence": 0.8}],
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "STALE", "current_belief_id": belief_id, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.8}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx5_revise_belief(
            store=mock_store,
            belief_id=belief_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.new_belief_id is None
        assert result.content_changed is False

    @pytest.mark.asyncio
    async def test_invalidates_unsupported_belief(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX5 invalidates belief when facts drop below threshold."""
        belief_id = make_uuid()
        cluster_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_BELIEF_FOR_REVISION
            [{"id": belief_id, "content": "Old belief", "state": "ACTIVE",
              "synthesis_state": "STALE", "source_cluster_id": cluster_id,
              "revision_in_progress": False, "confidence": 0.8}],
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "STALE", "current_belief_id": belief_id, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER - only 1 fact now
            [{"id": make_uuid(), "content": "Lonely fact", "confidence": 0.8}],
        ])

        result, events = await tx5_revise_belief(
            store=mock_store,
            belief_id=belief_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.new_belief_id is None
        assert result.invalidated is True
        mock_llm.complete.assert_not_called()

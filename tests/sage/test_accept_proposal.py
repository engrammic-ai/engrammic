"""Tests for accept_proposal transaction."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    AcceptProposalResult,
    InvariantViolation,
    accept_proposal,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_write = AsyncMock(return_value=[])
    store.execute_query = AsyncMock(return_value=[])
    return store


def make_uuid() -> str:
    """Generate a valid UUID string for tests."""
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_accept_proposal_success(mock_store: AsyncMock) -> None:
    """Accept creates Belief from ProposedBelief."""
    proposal_id = make_uuid()
    belief_id = make_uuid()
    silo_id = "test-silo"

    # GET_PROPOSED_BELIEF returns pending proposal with sufficient derivation chain
    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "pending",
                "content": "Test synthesis",
                "confidence": 0.85,
                "source_fact_ids": [make_uuid(), make_uuid(), make_uuid()],
            }
        ]
    )
    # ACCEPT_PROPOSED_BELIEF returns the created belief
    mock_store.execute_write = AsyncMock(
        return_value=[{"belief_id": belief_id, "confidence": 0.85}]
    )

    result, events = await accept_proposal(
        store=mock_store,
        proposal_id=proposal_id,
        silo_id=silo_id,
        agent_id="test-agent",
        reason="Verified against sources",
        emit=False,
    )

    assert isinstance(result, AcceptProposalResult)
    assert result.accepted is True
    assert result.belief_id is not None
    assert result.proposal_id == uuid.UUID(proposal_id)
    assert result.confidence == pytest.approx(0.85)
    assert isinstance(result.accepted_at, datetime)
    # Reaction events should be generated (COMPUTE_EMBEDDING, UPDATE_HEAT, PROPAGATE_CONFIDENCE)
    assert len(events) == 3


@pytest.mark.asyncio
async def test_accept_proposal_not_found(mock_store: AsyncMock) -> None:
    """Accept fails for non-existent proposal."""
    mock_store.execute_query = AsyncMock(return_value=[])

    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=mock_store,
            proposal_id=make_uuid(),
            silo_id="test-silo",
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "PROPOSAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_accept_proposal_already_rejected(mock_store: AsyncMock) -> None:
    """Accept fails for already rejected proposal."""
    proposal_id = make_uuid()
    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "rejected",
                "content": "test",
                "confidence": 0.8,
            }
        ]
    )

    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=mock_store,
            proposal_id=proposal_id,
            silo_id="test-silo",
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "PROPOSAL_REJECTED"


@pytest.mark.asyncio
async def test_accept_proposal_already_accepted_idempotent(mock_store: AsyncMock) -> None:
    """Accept is idempotent for already accepted proposals."""
    proposal_id = make_uuid()
    existing_belief_id = make_uuid()

    # First call: GET_PROPOSED_BELIEF returns accepted status
    # Second call: query for existing Belief
    mock_store.execute_query = AsyncMock(
        side_effect=[
            # GET_PROPOSED_BELIEF
            [{"proposed_belief_id": proposal_id, "status": "accepted", "confidence": 0.85}],
            # MATCH Belief PROMOTED_FROM ProposedBelief
            [{"belief_id": existing_belief_id, "confidence": 0.85}],
        ]
    )

    result, events = await accept_proposal(
        store=mock_store,
        proposal_id=proposal_id,
        silo_id="test-silo",
        agent_id="test-agent",
        emit=False,
    )

    assert result.accepted is True
    assert result.belief_id == uuid.UUID(existing_belief_id)
    assert events == []


@pytest.mark.asyncio
async def test_accept_proposal_insufficient_derivation(mock_store: AsyncMock) -> None:
    """Accept fails when proposal has < 3 SYNTHESIZED_FROM edges (GAP-007)."""
    proposal_id = make_uuid()

    # Only 2 source facts - below SYNTHESIS_THRESHOLD of 3
    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "pending",
                "content": "Test synthesis",
                "confidence": 0.85,
                "source_fact_ids": [make_uuid(), make_uuid()],
            }
        ]
    )

    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=mock_store,
            proposal_id=proposal_id,
            silo_id="test-silo",
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "INSUFFICIENT_DERIVATION"
    assert "2 SYNTHESIZED_FROM edges" in str(exc.value)
    assert "requires 3" in str(exc.value)


@pytest.mark.asyncio
async def test_accept_proposal_invalid_status(mock_store: AsyncMock) -> None:
    """Accept fails for proposal with unexpected status."""
    proposal_id = make_uuid()
    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "expired",
                "content": "test",
                "confidence": 0.8,
            }
        ]
    )

    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=mock_store,
            proposal_id=proposal_id,
            silo_id="test-silo",
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "INVALID_STATUS"


@pytest.mark.asyncio
async def test_accept_proposal_with_override_confidence(mock_store: AsyncMock) -> None:
    """Accept uses override_confidence when provided."""
    proposal_id = make_uuid()
    belief_id = make_uuid()

    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "pending",
                "content": "Test synthesis",
                "confidence": 0.5,
                "source_fact_ids": [make_uuid(), make_uuid(), make_uuid()],
            }
        ]
    )
    mock_store.execute_write = AsyncMock(
        return_value=[{"belief_id": belief_id, "confidence": 0.95}]
    )

    result, events = await accept_proposal(
        store=mock_store,
        proposal_id=proposal_id,
        silo_id="test-silo",
        agent_id="test-agent",
        override_confidence=0.95,
        emit=False,
    )

    assert result.accepted is True
    assert result.confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_accept_proposal_accept_failed(mock_store: AsyncMock) -> None:
    """Accept raises InvariantViolation when write returns empty."""
    proposal_id = make_uuid()

    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "pending",
                "content": "Test synthesis",
                "confidence": 0.85,
                "source_fact_ids": [make_uuid(), make_uuid(), make_uuid()],
            }
        ]
    )
    # ACCEPT_PROPOSED_BELIEF returns nothing (race condition, node was already accepted)
    mock_store.execute_write = AsyncMock(return_value=[])

    with pytest.raises(InvariantViolation) as exc:
        await accept_proposal(
            store=mock_store,
            proposal_id=proposal_id,
            silo_id="test-silo",
            agent_id="test-agent",
            emit=False,
        )
    assert exc.value.code == "ACCEPT_FAILED"


@pytest.mark.asyncio
async def test_accept_proposal_reason_stored(mock_store: AsyncMock) -> None:
    """When reason is provided, a write is made to store it."""
    proposal_id = make_uuid()
    belief_id = make_uuid()

    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "pending",
                "content": "Test synthesis",
                "confidence": 0.85,
                "source_fact_ids": [make_uuid(), make_uuid(), make_uuid()],
            }
        ]
    )
    mock_store.execute_write = AsyncMock(
        return_value=[{"belief_id": belief_id, "confidence": 0.85}]
    )

    await accept_proposal(
        store=mock_store,
        proposal_id=proposal_id,
        silo_id="test-silo",
        agent_id="test-agent",
        reason="Strong evidence",
        emit=False,
    )

    # Should have called execute_write at least twice: once for ACCEPT, once for reason SET
    assert mock_store.execute_write.call_count >= 2


@pytest.mark.asyncio
async def test_accept_proposal_no_reason_single_write(mock_store: AsyncMock) -> None:
    """When no reason, only the ACCEPT write is made."""
    proposal_id = make_uuid()
    belief_id = make_uuid()

    mock_store.execute_query = AsyncMock(
        return_value=[
            {
                "proposed_belief_id": proposal_id,
                "status": "pending",
                "content": "Test synthesis",
                "confidence": 0.85,
                "source_fact_ids": [make_uuid(), make_uuid(), make_uuid()],
            }
        ]
    )
    mock_store.execute_write = AsyncMock(
        return_value=[{"belief_id": belief_id, "confidence": 0.85}]
    )

    await accept_proposal(
        store=mock_store,
        proposal_id=proposal_id,
        silo_id="test-silo",
        agent_id="test-agent",
        emit=False,
    )

    # Only the ACCEPT write, no reason write
    assert mock_store.execute_write.call_count == 1

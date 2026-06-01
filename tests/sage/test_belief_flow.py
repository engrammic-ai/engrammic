"""Tests for Phase 3 belief flow transactions (TX4, TX5, TX8, TX14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    BrainError,
    CommitResult,
    InvariantViolation,
    NodeState,
    tx8_commit,
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


class TestTx8Commit:
    """Tests for TX8 COMMIT."""

    @pytest.mark.asyncio
    async def test_creates_commitment_with_about_edges(self, mock_store: AsyncMock) -> None:
        """Test that TX8 creates a commitment with ABOUT edges."""
        about_ref = make_uuid()
        mock_store.execute_query = AsyncMock(return_value=[
            {"id": about_ref, "state": "ACTIVE"}
        ])

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
        mock_store.execute_query = AsyncMock(return_value=[
            {"id": tombstoned_ref, "state": "TOMBSTONED"}
        ])

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

"""Tests for Phase 5 layer movement transactions (TX18 PROMOTE, TX19 DEMOTE)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    PROMOTION_THRESHOLD,
    DemoteResult,
    InvariantViolation,
    PromoteResult,
    demote,
    promote,
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


class TestTx18Promote:
    """Tests for TX18 PROMOTE."""

    @pytest.mark.asyncio
    async def test_promotes_claim_with_sufficient_corroboration(
        self, mock_store: AsyncMock
    ) -> None:
        """Test that TX18 promotes a claim meeting corroboration threshold."""
        claim_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": claim_id,
                    "state": "ACTIVE",
                    "claim_status": "UNPROMOTED",
                    "corroboration_count": PROMOTION_THRESHOLD,
                    "confidence": 0.8,
                }
            ]
        )
        mock_store.execute_write = AsyncMock(
            return_value=[
                {
                    "id": claim_id,
                    "claim_status": "PROMOTED",
                }
            ]
        )

        result, events = await promote(
            store=mock_store,
            claim_id=claim_id,
            silo_id="test-silo",
        )

        assert isinstance(result, PromoteResult)
        assert result.corroboration_count >= PROMOTION_THRESHOLD

    @pytest.mark.asyncio
    async def test_rejects_insufficient_corroboration(self, mock_store: AsyncMock) -> None:
        """Test that TX18 rejects claims below corroboration threshold."""
        claim_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": claim_id,
                    "state": "ACTIVE",
                    "claim_status": "UNPROMOTED",
                    "corroboration_count": PROMOTION_THRESHOLD - 1,
                    "confidence": 0.8,
                }
            ]
        )

        with pytest.raises(InvariantViolation) as exc_info:
            await promote(
                store=mock_store,
                claim_id=claim_id,
                silo_id="test-silo",
            )

        assert exc_info.value.code == "INSUFFICIENT_CORROBORATION"

    @pytest.mark.asyncio
    async def test_idempotent_for_already_promoted(self, mock_store: AsyncMock) -> None:
        """Test that TX18 is idempotent for already promoted claims."""
        claim_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": claim_id,
                    "state": "ACTIVE",
                    "claim_status": "PROMOTED",
                    "corroboration_count": PROMOTION_THRESHOLD,
                    "confidence": 0.9,
                }
            ]
        )

        result, events = await promote(
            store=mock_store,
            claim_id=claim_id,
            silo_id="test-silo",
        )

        assert isinstance(result, PromoteResult)
        mock_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_missing_claim(self, mock_store: AsyncMock) -> None:
        """Test that TX18 rejects non-existent claims."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await promote(
                store=mock_store,
                claim_id=make_uuid(),
                silo_id="test-silo",
            )

        assert exc_info.value.code == "CLAIM_NOT_FOUND"


class TestTx19Demote:
    """Tests for TX19 DEMOTE."""

    @pytest.mark.asyncio
    async def test_demotes_fact_with_insufficient_corroboration(
        self, mock_store: AsyncMock
    ) -> None:
        """Test that TX19 demotes a fact below corroboration threshold."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": fact_id,
                        "state": "ACTIVE",
                        "claim_status": "PROMOTED",
                        "corroboration_count": PROMOTION_THRESHOLD - 1,
                        "confidence": 0.9,
                    }
                ],
                [{"corroboration_count": PROMOTION_THRESHOLD - 1}],
            ]
        )
        mock_store.execute_write = AsyncMock(
            return_value=[
                {
                    "id": fact_id,
                    "claim_status": "UNPROMOTED",
                }
            ]
        )

        result, events = await demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        assert isinstance(result, DemoteResult)
        assert result.corroboration_count < PROMOTION_THRESHOLD

    @pytest.mark.asyncio
    async def test_skips_demote_if_still_corroborated(self, mock_store: AsyncMock) -> None:
        """Test that TX19 skips demotion if corroboration is still sufficient."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": fact_id,
                        "state": "ACTIVE",
                        "claim_status": "PROMOTED",
                        "corroboration_count": PROMOTION_THRESHOLD,
                        "confidence": 0.9,
                    }
                ],
                [{"corroboration_count": PROMOTION_THRESHOLD}],
            ]
        )

        result, events = await demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        assert isinstance(result, DemoteResult)
        mock_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_for_already_demoted(self, mock_store: AsyncMock) -> None:
        """Test that TX19 is idempotent for already demoted facts."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": fact_id,
                    "state": "ACTIVE",
                    "claim_status": "UNPROMOTED",
                    "corroboration_count": 1,
                    "confidence": 0.7,
                }
            ]
        )

        result, events = await demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        assert isinstance(result, DemoteResult)
        mock_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_missing_fact(self, mock_store: AsyncMock) -> None:
        """Test that TX19 rejects non-existent facts."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await demote(
                store=mock_store,
                fact_id=make_uuid(),
                silo_id="test-silo",
            )

        assert exc_info.value.code == "FACT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_triggers_cascade_staleness(self, mock_store: AsyncMock) -> None:
        """Test that TX19 emits cascade_staleness event."""
        fact_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": fact_id,
                        "state": "ACTIVE",
                        "claim_status": "PROMOTED",
                        "corroboration_count": 1,
                        "confidence": 0.9,
                    }
                ],
                [{"corroboration_count": 1}],
            ]
        )
        mock_store.execute_write = AsyncMock(
            return_value=[
                {
                    "id": fact_id,
                    "claim_status": "UNPROMOTED",
                }
            ]
        )

        result, events = await demote(
            store=mock_store,
            fact_id=fact_id,
            silo_id="test-silo",
        )

        event_types = [e.event_type for e in events]
        assert "cascade_staleness" in event_types

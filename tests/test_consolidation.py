"""Tests for ConclusionConsolidator.

TDD: write tests first, then implement consolidation.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.custodian.consolidation import ConclusionConsolidator


@pytest.fixture
def mock_memgraph() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)
    redis = MagicMock()
    redis.lock.return_value = lock
    return redis


@pytest.fixture
def consolidator(mock_memgraph: AsyncMock, mock_redis: MagicMock) -> ConclusionConsolidator:
    return ConclusionConsolidator(mock_memgraph, mock_redis)


@pytest.mark.asyncio
async def test_consolidate_skips_single_conclusion(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """No consolidation when only one conclusion exists."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.9}
    ]

    result = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert result is None


@pytest.mark.asyncio
async def test_consolidate_skips_empty_conclusions(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """No consolidation when there are no conclusions."""
    mock_memgraph.get_conclusions_by_hash.return_value = []

    result = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert result is None


@pytest.mark.asyncio
async def test_consolidate_creates_canonical(
    consolidator: ConclusionConsolidator,
    mock_memgraph: AsyncMock,
    mock_redis: MagicMock,
) -> None:
    """Creates canonical when 2+ conclusions share hash."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.8, "content": "Answer A"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer A"},
    ]

    result = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert result is not None
    mock_memgraph.upsert_conclusion.assert_called_once()


@pytest.mark.asyncio
async def test_consolidate_applies_agreement_boost(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """Merged confidence is higher than plain average due to agreement boost."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.8, "content": "Answer A"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer A"},
    ]

    await consolidator.consolidate_by_hash("silo-1", "hash-1")

    call_kwargs = mock_memgraph.upsert_conclusion.call_args.kwargs
    # Average is 0.85; agreement boost should push it above 0.85
    assert call_kwargs["confidence"] > 0.85


@pytest.mark.asyncio
async def test_consolidate_uses_highest_confidence_content(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """Canonical conclusion uses content from highest-confidence original."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.6, "content": "Weaker answer"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Better answer"},
    ]

    await consolidator.consolidate_by_hash("silo-1", "hash-1")

    call_kwargs = mock_memgraph.upsert_conclusion.call_args.kwargs
    assert call_kwargs["content"] == "Better answer"


@pytest.mark.asyncio
async def test_consolidate_marks_originals_consolidated(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """After consolidation, all original conclusions are marked consolidated."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.8, "content": "Answer"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer"},
    ]

    await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert mock_memgraph.mark_conclusion_consolidated.call_count == 2
    called_ids = {
        call.args[0] for call in mock_memgraph.mark_conclusion_consolidated.call_args_list
    }
    assert called_ids == {"c1", "c2"}


@pytest.mark.asyncio
async def test_consolidate_creates_consolidates_edges(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """CONSOLIDATES edges are created from canonical to each original."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.8, "content": "Answer"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer"},
    ]

    canonical_id = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert mock_memgraph.create_consolidates_edge.call_count == 2
    for call in mock_memgraph.create_consolidates_edge.call_args_list:
        assert call.args[0] == canonical_id


@pytest.mark.asyncio
async def test_consolidate_acquires_lock(
    consolidator: ConclusionConsolidator,
    mock_memgraph: AsyncMock,
    mock_redis: MagicMock,
) -> None:
    """Consolidation acquires a Redis lock keyed by silo+hash."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.8, "content": "Answer"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer"},
    ]

    await consolidator.consolidate_by_hash("silo-1", "hash-1")

    mock_redis.lock.assert_called_once()
    lock_key = mock_redis.lock.call_args.args[0]
    assert "silo-1" in lock_key
    assert "hash-1" in lock_key


@pytest.mark.asyncio
async def test_consolidate_idempotent_skips_already_consolidated(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """Skips consolidation if any conclusion already has consolidated status."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "consolidated", "confidence": 0.8, "content": "Answer"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer"},
        {"id": "c3", "status": "active", "confidence": 0.85, "content": "Answer"},
    ]

    result = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert result is None
    mock_memgraph.upsert_conclusion.assert_not_called()


@pytest.mark.asyncio
async def test_confidence_capped_at_one(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """Merged confidence never exceeds 1.0 even with large agreement boost."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": f"c{i}", "status": "active", "confidence": 0.99, "content": "Answer"}
        for i in range(10)
    ]

    await consolidator.consolidate_by_hash("silo-1", "hash-1")

    call_kwargs = mock_memgraph.upsert_conclusion.call_args.kwargs
    assert call_kwargs["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_repair_orphaned_consolidations(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """repair_orphaned_consolidations marks all orphaned conclusions consolidated."""
    mock_memgraph.find_orphaned_active_conclusions.return_value = ["c1", "c2", "c3"]

    count = await consolidator.repair_orphaned_consolidations("silo-1")

    assert count == 3
    assert mock_memgraph.mark_conclusion_consolidated.call_count == 3


@pytest.mark.asyncio
async def test_repair_returns_zero_when_no_orphans(
    consolidator: ConclusionConsolidator, mock_memgraph: AsyncMock
) -> None:
    """Returns 0 when there are no orphaned conclusions."""
    mock_memgraph.find_orphaned_active_conclusions.return_value = []

    count = await consolidator.repair_orphaned_consolidations("silo-1")

    assert count == 0
    mock_memgraph.mark_conclusion_consolidated.assert_not_called()

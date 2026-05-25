"""Tests for proposal_detection constraints: per-silo cap and cooldown."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Settings field tests
# ---------------------------------------------------------------------------


def test_proposal_cooldown_hours_default():
    from context_service.config.settings import Settings

    s = Settings()
    assert s.proposal_cooldown_hours == 24


def test_max_proposals_per_silo_default():
    from context_service.config.settings import Settings

    s = Settings()
    assert s.max_proposals_per_silo == 10


def test_proposal_threshold_is_half():
    """Threshold should remain at 0.5 (already set)."""
    from context_service.config.settings import Settings

    s = Settings()
    assert s.validator_proposal_threshold == 0.5


# ---------------------------------------------------------------------------
# was_recently_rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_was_recently_rejected_returns_true_when_count_positive():
    from context_service.custodian.proposal_worker import was_recently_rejected

    graph_store = AsyncMock()
    graph_store.execute_query.return_value = [{"rejected_count": 1}]

    result = await was_recently_rejected(graph_store, "cluster-1", "silo-a", cooldown_hours=24)

    assert result is True
    graph_store.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_was_recently_rejected_returns_false_when_count_zero():
    from context_service.custodian.proposal_worker import was_recently_rejected

    graph_store = AsyncMock()
    graph_store.execute_query.return_value = [{"rejected_count": 0}]

    result = await was_recently_rejected(graph_store, "cluster-1", "silo-a", cooldown_hours=24)

    assert result is False


@pytest.mark.asyncio
async def test_was_recently_rejected_returns_false_on_empty_result():
    from context_service.custodian.proposal_worker import was_recently_rejected

    graph_store = AsyncMock()
    graph_store.execute_query.return_value = []

    result = await was_recently_rejected(graph_store, "cluster-1", "silo-a", cooldown_hours=24)

    assert result is False


@pytest.mark.asyncio
async def test_was_recently_rejected_uses_correct_cutoff():
    """Cutoff passed to query should be within ~1 second of expected."""
    from context_service.custodian.proposal_worker import was_recently_rejected
    from context_service.db.queries import GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER

    graph_store = AsyncMock()
    graph_store.execute_query.return_value = [{"rejected_count": 0}]

    before = datetime.now(UTC) - timedelta(hours=12, seconds=2)
    await was_recently_rejected(graph_store, "cluster-x", "silo-b", cooldown_hours=12)
    after = datetime.now(UTC) - timedelta(hours=12, seconds=-2)

    call_kwargs = graph_store.execute_query.call_args[0][1]
    assert call_kwargs["cluster_id"] == "cluster-x"
    assert call_kwargs["silo_id"] == "silo-b"
    cutoff = datetime.fromisoformat(call_kwargs["cutoff"])
    assert before <= cutoff <= after
    assert graph_store.execute_query.call_args[0][0] == GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER


# ---------------------------------------------------------------------------
# create_proposal — cap and cooldown gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_proposal_skips_when_at_cap():
    from context_service.custodian.proposal_worker import create_proposal

    graph_store = AsyncMock()
    # pending count at cap
    graph_store.execute_query.return_value = [{"pending_count": 10}]

    result = await create_proposal(
        graph_store,
        cluster_id="cluster-1",
        silo_id="silo-a",
        confidence=0.55,
        max_pending=10,
        cooldown_hours=24,
    )

    assert result is None


@pytest.mark.asyncio
async def test_create_proposal_skips_when_cooldown_active():
    from context_service.custodian.proposal_worker import create_proposal

    graph_store = AsyncMock()

    def _query_side_effect(query: str, params: dict):  # type: ignore[return]
        from context_service.db.queries import (
            GET_PENDING_PROPOSAL_COUNT_FOR_SILO,
            GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER,
        )

        if query == GET_PENDING_PROPOSAL_COUNT_FOR_SILO:
            return [{"pending_count": 0}]
        if query == GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER:
            return [{"rejected_count": 1}]

    graph_store.execute_query = AsyncMock(side_effect=_query_side_effect)

    result = await create_proposal(
        graph_store,
        cluster_id="cluster-1",
        silo_id="silo-a",
        confidence=0.55,
        max_pending=10,
        cooldown_hours=24,
    )

    assert result is None


@pytest.mark.asyncio
async def test_create_proposal_creates_when_under_cap_and_no_cooldown():
    from context_service.custodian.proposal_worker import create_proposal

    graph_store = AsyncMock()

    def _query_side_effect(query: str, params: dict):  # type: ignore[return]
        from context_service.db.queries import (
            CREATE_PROPOSED_BELIEF,
            GET_PENDING_PROPOSAL_COUNT_FOR_SILO,
            GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER,
        )

        if query == GET_PENDING_PROPOSAL_COUNT_FOR_SILO:
            return [{"pending_count": 3}]
        if query == GET_RECENTLY_REJECTED_PROPOSAL_FOR_CLUSTER:
            return [{"rejected_count": 0}]
        if query == CREATE_PROPOSED_BELIEF:
            return [{"proposed_belief_id": params["id"]}]
        return []

    graph_store.execute_query = AsyncMock(side_effect=_query_side_effect)

    with (
        patch(
            "context_service.custodian.proposal_worker.get_cluster_facts",
            return_value=[{"fact_id": "f1", "content": "test fact", "confidence": 0.8}],
        ),
        patch(
            "context_service.custodian.proposal_worker.synthesize_proposal_content",
            return_value="A test belief",
        ),
    ):
        result = await create_proposal(
            graph_store,
            cluster_id="cluster-1",
            silo_id="silo-a",
            confidence=0.55,
            max_pending=10,
            cooldown_hours=24,
        )

    assert result is not None


# ---------------------------------------------------------------------------
# Dagster asset surface
# ---------------------------------------------------------------------------


def test_proposal_detection_asset_exists():
    from context_service.pipelines.assets.proposal_detection import proposal_detection

    assert proposal_detection is not None


def test_proposal_detection_asset_name():
    from context_service.pipelines.assets.proposal_detection import proposal_detection

    keys = list(proposal_detection.keys)
    assert len(keys) == 1
    assert keys[0].path[-1] == "proposal_detection"

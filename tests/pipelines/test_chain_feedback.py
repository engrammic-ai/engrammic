"""Tests for chain_feedback Dagster asset.

Mocks all database and store calls so tests run without a live stack.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from context_service.pipelines.assets.chain_feedback import (
    check_new_chain_created,
    compute_chain_usefulness,
    get_chain_step_embeddings,
    get_session_steps_after,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHAIN_ID = "00000000-0000-0000-0000-000000000001"
SESSION_ID = "00000000-0000-0000-0000-000000000002"

_DELIVERY: dict = {
    "session_id": SESSION_ID,
    "chain_id": CHAIN_ID,
    "query": "how do I solve X?",
    "delivered_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
}

# Simple 2-D embeddings for testing DTW.
_CHAIN_STEPS = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
_MATCHING_STEPS = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]  # identical -> overlap ~1.0
_DIFFERENT_STEPS = [[0.9, 0.8], [0.7, 0.6], [0.5, 0.4]]  # divergent


# ---------------------------------------------------------------------------
# Unit tests: pure logic helpers
# ---------------------------------------------------------------------------


def test_chain_usefulness_signals_asset_exists():
    from context_service.pipelines.assets.chain_feedback import chain_usefulness_signals

    assert chain_usefulness_signals is not None


def test_chain_usefulness_signals_group():
    from context_service.pipelines.assets.chain_feedback import chain_usefulness_signals

    spec = chain_usefulness_signals.specs_by_key[list(chain_usefulness_signals.keys)[0]]
    assert spec.group_name == "chain_feedback"


# ---------------------------------------------------------------------------
# Async tests: compute_chain_usefulness signal logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_useful_signal_when_high_dtw_overlap():
    """Signal is 'useful' when DTW overlap exceeds 0.7."""
    with (
        patch(
            "context_service.pipelines.assets.chain_feedback.get_session_steps_after",
            new=AsyncMock(return_value=_MATCHING_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.get_chain_step_embeddings",
            new=AsyncMock(return_value=_CHAIN_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.check_new_chain_created",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.store_feedback",
            new=AsyncMock(),
        ) as mock_store,
    ):
        signal = await compute_chain_usefulness(_DELIVERY)

    assert signal == "useful"
    mock_store.assert_awaited_once_with(CHAIN_ID, signal="useful")


@pytest.mark.asyncio
async def test_not_useful_signal_when_new_chain_created():
    """Signal is 'not_useful' when overlap is low and a new chain was created."""
    with (
        patch(
            "context_service.pipelines.assets.chain_feedback.get_session_steps_after",
            new=AsyncMock(return_value=_DIFFERENT_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.get_chain_step_embeddings",
            new=AsyncMock(return_value=_CHAIN_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.check_new_chain_created",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.store_feedback",
            new=AsyncMock(),
        ) as mock_store,
    ):
        signal = await compute_chain_usefulness(_DELIVERY)

    assert signal == "not_useful"
    mock_store.assert_awaited_once_with(CHAIN_ID, signal="not_useful")


@pytest.mark.asyncio
async def test_unclear_signal_when_low_overlap_no_new_chain():
    """Signal is 'unclear' when overlap is low and no new chain was created."""
    with (
        patch(
            "context_service.pipelines.assets.chain_feedback.get_session_steps_after",
            new=AsyncMock(return_value=_DIFFERENT_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.get_chain_step_embeddings",
            new=AsyncMock(return_value=_CHAIN_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.check_new_chain_created",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.store_feedback",
            new=AsyncMock(),
        ) as mock_store,
    ):
        signal = await compute_chain_usefulness(_DELIVERY)

    assert signal == "unclear"
    mock_store.assert_awaited_once_with(CHAIN_ID, signal="unclear")


@pytest.mark.asyncio
async def test_skip_when_insufficient_steps():
    """Returns None when fewer than min_subsequent_steps are available."""
    # Default min_subsequent_steps is 3; return only 2 steps.
    with (
        patch(
            "context_service.pipelines.assets.chain_feedback.get_session_steps_after",
            new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]]),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.store_feedback",
            new=AsyncMock(),
        ) as mock_store,
    ):
        signal = await compute_chain_usefulness(_DELIVERY)

    assert signal is None
    mock_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_skip_when_no_chain_steps():
    """Returns None when the chain has no stored step embeddings."""
    with (
        patch(
            "context_service.pipelines.assets.chain_feedback.get_session_steps_after",
            new=AsyncMock(return_value=_MATCHING_STEPS),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.get_chain_step_embeddings",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "context_service.pipelines.assets.chain_feedback.store_feedback",
            new=AsyncMock(),
        ) as mock_store,
    ):
        signal = await compute_chain_usefulness(_DELIVERY)

    assert signal is None
    mock_store.assert_not_awaited()


# ---------------------------------------------------------------------------
# Stub return-type tests (no live infra required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_steps_after_stub_returns_list():
    result = await get_session_steps_after(
        session_id=SESSION_ID,
        after=datetime.now(UTC),
        limit=5,
    )
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_chain_step_embeddings_stub_returns_list():
    result = await get_chain_step_embeddings(CHAIN_ID)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_check_new_chain_created_stub_returns_bool():
    result = await check_new_chain_created(
        session_id=SESSION_ID,
        after=datetime.now(UTC),
        query="test query",
    )
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


def test_chain_feedback_config_defaults():
    from context_service.config.settings import get_settings

    config = get_settings().chain_feedback
    assert config.evaluation_delay_minutes == 5
    assert config.min_subsequent_steps == 3
    assert config.max_wait_minutes == 30

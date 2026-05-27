"""Tests for engine/session_state.py -- Redis-backed session state for tick() engagement."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.engine.session_state import (
    SessionState,
    get_or_create_session,
    increment_turn,
)


@pytest.mark.asyncio
async def test_get_or_create_session_creates_new():
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    session = await get_or_create_session(
        redis=mock_redis,
        session_id=None,
        silo_id="test_silo",
    )

    assert session.session_id.startswith("sess_")
    assert session.turn_count == 0
    assert session.last_store_turn == 0
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_session_loads_existing():
    mock_redis = MagicMock()
    existing_state = {
        "session_id": "sess_existing",
        "turn_count": 5,
        "last_store_turn": 3,
        "shown_nudges": {"form_belief": [2, 4]},
        "ignored_nudges": {"form_belief": 1},
        "created_at": datetime.now(UTC).isoformat(),
    }
    mock_redis.get = AsyncMock(return_value=json.dumps(existing_state))

    session = await get_or_create_session(
        redis=mock_redis,
        session_id="sess_existing",
        silo_id="test_silo",
    )

    assert session.session_id == "sess_existing"
    assert session.turn_count == 5
    assert session.shown_nudges["form_belief"] == [2, 4]


def test_should_show_nudge_debounces():
    session = SessionState(session_id="test", turn_count=5)
    session.record_nudge_shown("form_belief")  # shown at turn 5

    session.turn_count = 6
    assert not session.should_show_nudge("form_belief")  # too soon (within 3 turns)

    session.turn_count = 8
    assert session.should_show_nudge("form_belief")  # now ok (3 turns later)


def test_should_show_nudge_suppresses_after_ignores():
    session = SessionState(session_id="test", turn_count=0)
    session.record_nudge_ignored("form_belief")
    session.record_nudge_ignored("form_belief")
    assert session.should_show_nudge("form_belief")  # 2 ignores, still ok

    session.record_nudge_ignored("form_belief")
    assert not session.should_show_nudge("form_belief")  # 3 ignores, suppressed


def test_record_nudge_shown_caps_history():
    session = SessionState(session_id="test", turn_count=0)
    for i in range(15):
        session.turn_count = i
        session.record_nudge_shown("test_nudge")

    assert len(session.shown_nudges["test_nudge"]) == 10  # capped at 10


@pytest.mark.asyncio
async def test_increment_turn_mutates_in_place():
    mock_redis = MagicMock()
    mock_redis.setex = AsyncMock()

    session = SessionState(session_id="sess_test", turn_count=2)
    result = await increment_turn(redis=mock_redis, session=session, silo_id="test_silo")

    assert session.turn_count == 3
    assert result is session  # same object returned
    mock_redis.setex.assert_called_once()

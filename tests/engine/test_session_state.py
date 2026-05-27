"""Tests for engine/session_state.py -- Redis-backed session state for tick() engagement."""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_get_or_create_session_creates_new():
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    from context_service.engine.session_state import get_or_create_session

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
    }
    mock_redis.get = AsyncMock(return_value=json.dumps(existing_state))

    from context_service.engine.session_state import get_or_create_session

    session = await get_or_create_session(
        redis=mock_redis,
        session_id="sess_existing",
        silo_id="test_silo",
    )

    assert session.session_id == "sess_existing"
    assert session.turn_count == 5
    assert session.shown_nudges["form_belief"] == [2, 4]

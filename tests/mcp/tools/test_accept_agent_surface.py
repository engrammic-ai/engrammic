# tests/mcp/tools/test_accept_agent_surface.py
"""Agent-surface integration tests for the accept tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from context_service.mcp.tools import context_accept_belief


@pytest.mark.asyncio
async def test_accept_registers_with_agent_facing_name() -> None:
    """The accept tool registers with the name 'accept', not 'context_accept_belief'."""
    mcp = FastMCP("test")
    context_accept_belief.register(mcp)

    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "accept" in tool_names, f"Expected 'accept' in tools; got {tool_names}"
    assert "context_accept_belief" not in tool_names, (
        "Old name 'context_accept_belief' should no longer be registered"
    )


@pytest.mark.asyncio
async def test_accept_returns_created_belief_id_on_success() -> None:
    """Calling _context_accept_belief with a valid proposed_belief_id returns the new belief_id."""
    from context_service.mcp.tools.context_accept_belief import _context_accept_belief

    silo_id = str(uuid.uuid4())
    proposed_belief_id = str(uuid.uuid4())
    expected_belief_id = str(uuid.uuid4())

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = [{"belief_id": expected_belief_id, "confidence": 0.85}]

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_accept_belief(
            proposed_belief_id=proposed_belief_id,
            silo_id=silo_id,
        )

    assert result["status"] == "accepted"
    assert result["proposed_belief_id"] == proposed_belief_id
    assert result["created_belief_id"] == expected_belief_id
    assert result["confidence"] == 0.85
    assert "accepted_at" in result


@pytest.mark.asyncio
async def test_accept_returns_not_found_when_no_rows() -> None:
    """If the underlying query returns no rows, the tool returns the not_found error envelope."""
    from context_service.mcp.tools.context_accept_belief import _context_accept_belief

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = []

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_accept_belief(
            proposed_belief_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid4()),
        )

    assert result["error"] == "not_found"


@pytest.mark.asyncio
async def test_accept_rejects_invalid_confidence() -> None:
    """Invalid confidence values are rejected at the boundary."""
    from context_service.mcp.tools.context_accept_belief import _context_accept_belief

    result = await _context_accept_belief(
        proposed_belief_id=str(uuid.uuid4()),
        silo_id=str(uuid.uuid4()),
        confidence=1.5,
    )

    assert result["error"] == "invalid_confidence"


@pytest.mark.asyncio
async def test_accept_clears_touch_counter_on_success() -> None:
    """clear_touches is called with the correct silo_id and proposed_belief_id after accept."""
    from context_service.mcp.tools.context_accept_belief import _context_accept_belief

    silo_id = str(uuid.uuid4())
    proposed_belief_id = str(uuid.uuid4())
    expected_belief_id = str(uuid.uuid4())

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = [{"belief_id": expected_belief_id, "confidence": 0.9}]

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    mock_raw_redis = AsyncMock()
    mock_redis_client = AsyncMock()
    mock_redis_client._redis = mock_raw_redis

    mock_clear = AsyncMock()

    with (
        patch("context_service.mcp.server.get_context_service", return_value=fake_service),
        patch("context_service.mcp.server.get_redis", return_value=mock_redis_client),
        patch("context_service.engine.touch_counter.clear_touches", mock_clear),
    ):
        result = await _context_accept_belief(
            proposed_belief_id=proposed_belief_id,
            silo_id=silo_id,
        )

    assert result["status"] == "accepted"
    mock_clear.assert_awaited_once_with(mock_raw_redis, silo_id, proposed_belief_id)


@pytest.mark.asyncio
async def test_accept_does_not_clear_touch_counter_on_not_found() -> None:
    """clear_touches is NOT called when the proposed belief is not found."""
    from context_service.mcp.tools.context_accept_belief import _context_accept_belief

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = []

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    mock_clear = AsyncMock()

    with (
        patch("context_service.mcp.server.get_context_service", return_value=fake_service),
        patch("context_service.engine.touch_counter.clear_touches", mock_clear),
    ):
        result = await _context_accept_belief(
            proposed_belief_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid4()),
        )

    assert result["error"] == "not_found"
    mock_clear.assert_not_awaited()

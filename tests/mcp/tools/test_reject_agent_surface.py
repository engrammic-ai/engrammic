# tests/mcp/tools/test_reject_agent_surface.py
"""Agent-surface integration tests for the reject tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from context_service.mcp.tools import context_reject_belief


@pytest.mark.asyncio
async def test_reject_registers_with_agent_facing_name() -> None:
    """The reject tool registers with the name 'reject', not 'context_reject_belief'."""
    mcp = FastMCP("test")
    context_reject_belief.register(mcp)

    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "reject" in tool_names, f"Expected 'reject' in tools; got {tool_names}"
    assert "context_reject_belief" not in tool_names, (
        "Old name 'context_reject_belief' should no longer be registered"
    )


@pytest.mark.asyncio
async def test_reject_returns_rejected_status_on_success() -> None:
    """Calling _context_reject_belief with a valid proposed_belief_id returns rejected status."""
    from context_service.mcp.tools.context_reject_belief import _context_reject_belief

    silo_id = str(uuid.uuid4())
    proposed_belief_id = str(uuid.uuid4())

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = [{"id": proposed_belief_id}]

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_reject_belief(
            proposed_belief_id=proposed_belief_id,
            silo_id=silo_id,
            reason="superseded by direct evidence",
        )

    assert result["status"] == "rejected"
    assert result["proposed_belief_id"] == proposed_belief_id
    assert result["reason"] == "superseded by direct evidence"
    assert "rejected_at" in result


@pytest.mark.asyncio
async def test_reject_returns_not_found_when_no_rows() -> None:
    """If the underlying query returns no rows, the tool returns the not_found error envelope."""
    from context_service.mcp.tools.context_reject_belief import _context_reject_belief

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = []

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=fake_service,
    ):
        result = await _context_reject_belief(
            proposed_belief_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid4()),
        )

    assert result["error"] == "not_found"


@pytest.mark.asyncio
async def test_reject_clears_touch_counter_on_success() -> None:
    """clear_touches is called with the correct silo_id and proposed_belief_id after reject."""
    from context_service.mcp.tools.context_reject_belief import _context_reject_belief

    silo_id = str(uuid.uuid4())
    proposed_belief_id = str(uuid.uuid4())

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = [{"id": proposed_belief_id}]

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
        result = await _context_reject_belief(
            proposed_belief_id=proposed_belief_id,
            silo_id=silo_id,
            reason="not valid",
        )

    assert result["status"] == "rejected"
    mock_clear.assert_awaited_once_with(mock_raw_redis, silo_id, proposed_belief_id)


@pytest.mark.asyncio
async def test_reject_does_not_clear_touch_counter_on_not_found() -> None:
    """clear_touches is NOT called when the proposed belief is not found."""
    from context_service.mcp.tools.context_reject_belief import _context_reject_belief

    fake_store = AsyncMock()
    fake_store.execute_write.return_value = []

    fake_service = AsyncMock()
    fake_service.graph_store = fake_store

    mock_clear = AsyncMock()

    with (
        patch("context_service.mcp.server.get_context_service", return_value=fake_service),
        patch("context_service.engine.touch_counter.clear_touches", mock_clear),
    ):
        result = await _context_reject_belief(
            proposed_belief_id=str(uuid.uuid4()),
            silo_id=str(uuid.uuid4()),
        )

    assert result["error"] == "not_found"
    mock_clear.assert_not_awaited()

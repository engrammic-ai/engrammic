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
    fake_store.execute_write.return_value = [{"belief_id": expected_belief_id}]

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

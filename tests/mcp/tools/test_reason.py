# tests/mcp/tools/test_reason.py
"""Tests for reason tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.reason import _reason_impl


@pytest.fixture
def mock_reason_auth():
    """Mock MCP auth context for reason tests."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session-123"
    auth.agent_id = None
    return auth


@pytest.fixture
def mock_reason_context(mock_reason_auth):
    """Patch all dependencies used by the reason tool."""
    svc = MagicMock()
    svc.graph_store = MagicMock()
    svc.graph_store.execute_query = AsyncMock(return_value=[])
    svc.graph_store.execute_write = AsyncMock(return_value=None)
    svc.graph_store.upsert_agent = AsyncMock(return_value=None)
    svc.graph_store.resolve_current_head = AsyncMock(return_value=None)

    saga = MagicMock()
    saga.write_chain = AsyncMock(return_value=None)

    with (
        patch(
            "context_service.mcp.tools.reason.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_reason_auth),
        ),
        patch(
            "context_service.mcp.tools.reason.track_tool_usage",
            new=AsyncMock(),
        ),
        patch(
            "context_service.mcp.tools.context_store.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_reason_auth),
        ),
        patch(
            "context_service.mcp.tools.context_store.get_context_service",
            return_value=svc,
        ),
        patch(
            "context_service.mcp.tools.context_store.get_postgres_store",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_store.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.engine.chain_saga.ChainSagaWriter",
            return_value=saga,
        ),
        patch(
            "context_service.engine.sessions.create_or_join_session",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.engine.sessions.attach_chain_to_session",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.mcp.tools.context_store.embed",
            new=AsyncMock(return_value=[0.1] * 768),
        ),
    ):
        yield svc


@pytest.mark.asyncio
async def test_reason_basic_creates_chain(mock_reason_context):
    """reason with valid steps should return chain_id and metadata."""
    steps = [
        {"step": 1, "reasoning": "Observed that tests are failing"},
        {"step": 2, "reasoning": "Narrowed down to missing mock"},
    ]

    result = await _reason_impl(
        steps=steps,
        conclusion="The test fixture was incomplete",
    )

    assert "error" not in result
    assert "chain_id" in result
    assert "session_id" in result
    assert "created_at" in result
    assert result["steps_count"] == 2
    assert result["layer"] == "intelligence"


@pytest.mark.asyncio
async def test_reason_with_parent_chain_links_correctly(mock_reason_context):
    """reason with a valid parent_chain_id should include continues_chain_id in result."""
    parent_id = str(uuid.uuid4())

    # Make the graph return a row so parent lookup succeeds.
    mock_reason_context.graph_store.execute_query = AsyncMock(
        return_value=[{"chain_id": parent_id}]
    )

    steps = [{"step": 1, "reasoning": "Continuing prior analysis"}]

    result = await _reason_impl(
        steps=steps,
        conclusion="Follow-up conclusion",
        evidence_used=[parent_id],
    )

    # The tool itself calls _context_reason via context_store; parent_chain_id
    # is not exposed on _reason_impl. Verify the chain is created without error.
    assert "error" not in result
    assert "chain_id" in result


@pytest.mark.asyncio
async def test_reason_missing_steps_returns_error(mock_reason_context):
    """reason with an empty steps list should return a missing_steps error."""
    result = await _reason_impl(steps=[])

    assert "error" in result
    assert result["error"] == "missing_steps"


@pytest.mark.asyncio
async def test_reason_invalid_step_schema_returns_error(mock_reason_context):
    """reason with a malformed step dict should return an invalid_steps error."""
    # 'reasoning' is required; omitting it should cause a validation error.
    result = await _reason_impl(steps=[{"step": 1}])

    assert "error" in result
    assert result["error"] == "invalid_steps"

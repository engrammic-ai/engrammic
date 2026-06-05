# tests/mcp/tools/test_forget.py
"""Tests for forget MCP tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.sage.transactions import ForgetResult, InvariantViolation, NodeState


def _make_forget_result(
    node_id: str = "node-1",
    cascade_count: int = 0,
) -> ForgetResult:
    now = datetime.now(UTC)
    return ForgetResult(
        node_id=uuid.UUID(node_id) if len(node_id) == 36 else uuid.uuid4(),
        state=NodeState.TOMBSTONED,
        tombstoned_at=now,
        cancel_window_expires=now + timedelta(hours=1),
        cascade_count=cascade_count,
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.agent_id = "test-agent"
    auth.session_id = "test-session"
    return auth


@pytest.fixture
def mock_ctx_svc():
    svc = MagicMock()
    svc.graph_store = AsyncMock()
    svc._cache = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_forget_tombstones_node(mock_auth, mock_ctx_svc):
    """forget tool should tombstone the requested node."""
    node_uuid = uuid.uuid4()
    forget_result = _make_forget_result(str(node_uuid))

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.forget.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.brain_forget",
            new=AsyncMock(return_value=(forget_result, [])),
        ),
        patch("context_service.mcp.tools.forget.emit_reaction", new=AsyncMock()),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl(str(node_uuid), reason="no longer needed", cascade=False)

    assert result["status"] == "tombstoned"
    assert result["node_id"] == str(node_uuid)
    assert "tombstoned_at" in result


@pytest.mark.asyncio
async def test_forget_not_found(mock_auth, mock_ctx_svc):
    """forget tool returns not_found when the node does not exist."""
    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.forget.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.brain_forget",
            new=AsyncMock(side_effect=InvariantViolation("NODE_NOT_FOUND", "Node not found")),
        ),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl("missing", cascade=False)

    assert result["status"] == "not_found"
    assert result["node_id"] == "missing"


@pytest.mark.asyncio
async def test_forget_already_tombstoned_returns_not_found(mock_auth, mock_ctx_svc):
    """forget tool maps ALREADY_TOMBSTONED to not_found."""
    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.forget.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.brain_forget",
            new=AsyncMock(
                side_effect=InvariantViolation("ALREADY_TOMBSTONED", "Node is already tombstoned")
            ),
        ),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl("node-1", cascade=False)

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_forget_cascade_marks_staleness(mock_auth, mock_ctx_svc):
    """cascade=True triggers CASCADE_STALENESS on dependents via brain_forget."""
    node_uuid = uuid.uuid4()
    forget_result = _make_forget_result(str(node_uuid), cascade_count=2)

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.forget.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.brain_forget",
            new=AsyncMock(return_value=(forget_result, [])),
        ) as mock_brain_forget,
        patch("context_service.mcp.tools.forget.emit_reaction", new=AsyncMock()),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl(str(node_uuid), cascade=True)

    assert result["status"] == "tombstoned"
    assert result.get("cascade_count") == 2
    call_kwargs = mock_brain_forget.call_args.kwargs
    assert call_kwargs["cascade"] is True


@pytest.mark.asyncio
async def test_forget_no_cascade_when_not_requested(mock_auth, mock_ctx_svc):
    """cascade=False passes cascade=False to brain_forget."""
    node_uuid = uuid.uuid4()
    forget_result = _make_forget_result(str(node_uuid))

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.forget.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.brain_forget",
            new=AsyncMock(return_value=(forget_result, [])),
        ) as mock_brain_forget,
        patch("context_service.mcp.tools.forget.emit_reaction", new=AsyncMock()),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl(str(node_uuid), cascade=False)

    assert "cascade_count" not in result
    call_kwargs = mock_brain_forget.call_args.kwargs
    assert call_kwargs["cascade"] is False

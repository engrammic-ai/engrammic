# tests/mcp/tools/test_forget.py
"""Tests for forget MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session"
    return auth


@pytest.fixture
def mock_graph_store():
    store = AsyncMock()
    store.execute_query.return_value = [{"id": "node-1", "downstream_count": 0}]
    return store


@pytest.fixture
def mock_ctx_svc(mock_graph_store):
    svc = MagicMock()
    svc.graph_store = mock_graph_store
    svc._qdrant = None
    return svc


@pytest.fixture
def mock_forget_service_factory(mock_graph_store):
    """Patch ForgetService to control its behavior in tests."""
    return mock_graph_store


@pytest.mark.asyncio
async def test_forget_tombstones_node(mock_auth, mock_ctx_svc, mock_graph_store):
    """forget tool should tombstone the requested node."""
    forget_svc = AsyncMock()
    forget_svc.forget.return_value = {
        "status": "tombstoned",
        "node_id": "node-1",
        "downstream_references": 0,
        "tombstoned_at": "2026-01-01T00:00:00+00:00",
    }

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch(
            "context_service.mcp.tools.forget.track_tool_usage",
            new=AsyncMock(),
        ),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.ForgetService",
            return_value=forget_svc,
        ),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl("node-1", reason="no longer needed", cascade=False)

    assert result["status"] == "tombstoned"
    assert result["node_id"] == "node-1"
    forget_svc.forget.assert_awaited_once()
    # Reason is passed through to ForgetService.forget
    call_args = forget_svc.forget.call_args
    assert call_args.args[2] == "no longer needed" or call_args.kwargs.get("reason") == "no longer needed"


@pytest.mark.asyncio
async def test_forget_not_found(mock_auth, mock_ctx_svc):
    """forget tool returns not_found when the node does not exist."""
    forget_svc = AsyncMock()
    forget_svc.forget.return_value = {"status": "not_found", "node_id": "missing"}

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch(
            "context_service.mcp.tools.forget.track_tool_usage",
            new=AsyncMock(),
        ),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.ForgetService",
            return_value=forget_svc,
        ),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl("missing", cascade=False)

    assert result["status"] == "not_found"
    assert result["node_id"] == "missing"


@pytest.mark.asyncio
async def test_forget_cascade_follows_downstream_references(mock_auth, mock_graph_store):
    """cascade=True should also tombstone downstream nodes that reference the target."""
    # ForgetService.forget uses execute_write for FORGET_NODE mutations
    mock_graph_store.execute_write.side_effect = [
        # First call: ForgetService.forget for node-1
        [{"id": "node-1", "downstream_count": 2}],
        # Second call: ForgetService.forget for node-2 (cascade)
        [{"id": "node-2", "downstream_count": 0}],
        # Third call: ForgetService.forget for node-3 (cascade)
        [{"id": "node-3", "downstream_count": 0}],
    ]
    # execute_query is used only for _FIND_DOWNSTREAM_NODES
    mock_graph_store.execute_query.side_effect = [
        # _FIND_DOWNSTREAM_NODES returns two referencing nodes
        [{"id": "node-2"}, {"id": "node-3"}],
    ]

    ctx_svc = MagicMock()
    ctx_svc.graph_store = mock_graph_store
    ctx_svc._qdrant = None

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch(
            "context_service.mcp.tools.forget.track_tool_usage",
            new=AsyncMock(),
        ),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=ctx_svc,
        ),
        patch("context_service.mcp.tools.forget.EngineQdrantStore"),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl("node-1", cascade=True)

    assert result["status"] == "tombstoned"
    assert "cascade_forgotten" in result
    assert set(result["cascade_forgotten"]) == {"node-2", "node-3"}


@pytest.mark.asyncio
async def test_forget_no_cascade_when_not_requested(mock_auth, mock_ctx_svc, mock_graph_store):
    """cascade=False should not query for downstream nodes."""
    forget_svc = AsyncMock()
    forget_svc.forget.return_value = {
        "status": "tombstoned",
        "node_id": "node-1",
        "downstream_references": 5,
        "tombstoned_at": "2026-01-01T00:00:00+00:00",
    }

    with (
        patch(
            "context_service.mcp.tools.forget.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch(
            "context_service.mcp.tools.forget.track_tool_usage",
            new=AsyncMock(),
        ),
        patch(
            "context_service.mcp.tools.forget.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.forget.ForgetService",
            return_value=forget_svc,
        ),
    ):
        from context_service.mcp.tools.forget import _forget_impl

        result = await _forget_impl("node-1", cascade=False)

    assert "cascade_forgotten" not in result
    # graph_store.execute_query should not be called for downstream discovery
    mock_graph_store.execute_query.assert_not_called()

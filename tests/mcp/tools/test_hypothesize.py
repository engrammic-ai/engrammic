# tests/mcp/tools/test_hypothesize.py
"""Tests for hypothesize MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session-123"
    return auth


@pytest.fixture
def mock_ctx_svc():
    svc = MagicMock()
    svc.graph_store = MagicMock()
    svc.graph_store.execute_write = AsyncMock(return_value=None)
    svc.graph_store.execute_query = AsyncMock(return_value=[])
    return svc


@pytest.mark.asyncio
async def test_hypothesize_creates_working_hypothesis(mock_auth, mock_ctx_svc):
    """Basic hypothesize call should return a belief_id and session_id."""
    with (
        patch(
            "context_service.mcp.tools.hypothesize.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.hypothesize.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.context_store.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_store.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.engine.sessions.create_or_join_session",
            new=AsyncMock(return_value=None),
        ),
        patch("context_service.api.metrics.record_store_latency"),
    ):
        from context_service.mcp.tools.hypothesize import _hypothesize_impl

        result = await _hypothesize_impl(
            hypothesis="The system bottleneck is the embedding step",
            about=["node-abc", "node-def"],
            confidence=0.75,
        )

    assert "error" not in result
    assert "belief_id" in result
    assert result["session_id"] == "test-session-123"
    assert "created_at" in result
    assert result["layer"] == "belief"


@pytest.mark.asyncio
async def test_hypothesize_no_session_returns_error(mock_ctx_svc):
    """hypothesize should return an error when no session is available."""
    auth_no_session = MagicMock()
    auth_no_session.org_id = "test-org"
    auth_no_session.session_id = None

    with (
        patch(
            "context_service.mcp.tools.hypothesize.get_mcp_auth_context",
            new=AsyncMock(return_value=auth_no_session),
        ),
        patch("context_service.mcp.tools.hypothesize.track_tool_usage", new=AsyncMock()),
    ):
        from context_service.mcp.tools.hypothesize import _hypothesize_impl

        result = await _hypothesize_impl(
            hypothesis="Some tentative belief",
            about=["node-abc"],
            confidence=0.8,
            session_id=None,
        )

    assert result["error"] == "no_session"


@pytest.mark.asyncio
async def test_hypothesize_invalid_confidence_returns_error(mock_auth, mock_ctx_svc):
    """hypothesize should return an error when confidence is outside 0.0-1.0."""
    with (
        patch(
            "context_service.mcp.tools.hypothesize.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.hypothesize.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.context_store.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.engine.sessions.create_or_join_session",
            new=AsyncMock(return_value=None),
        ),
    ):
        from context_service.mcp.tools.hypothesize import _hypothesize_impl

        result = await _hypothesize_impl(
            hypothesis="Some tentative belief",
            about=["node-abc"],
            confidence=1.5,
        )

    assert result["error"] == "invalid_confidence"

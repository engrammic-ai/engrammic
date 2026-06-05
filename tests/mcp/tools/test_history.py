# tests/mcp/tools/test_history.py
"""Tests for history tool."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.history import _history_impl
from context_service.services.context_meta import HistoryEntry, HistoryResult


@pytest.fixture
def mock_history_auth():
    """Mock MCP auth context for history tests."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session-123"
    return auth


@pytest.fixture
def mock_history_context(mock_history_auth):
    """Patch dependencies for history tool."""
    svc = MagicMock()
    svc.history = AsyncMock(
        return_value=HistoryResult(
            timeline=[
                HistoryEntry(
                    node_id="oldest-abc",
                    content="API uses basic auth",
                    valid_from=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
                    valid_to=datetime(2026, 3, 20, 14, 30, 0, tzinfo=UTC),
                    confidence=0.8,
                    supersession_reason=None,
                ),
                HistoryEntry(
                    node_id="current-def",
                    content="API uses OAuth2",
                    valid_from=datetime(2026, 3, 20, 14, 30, 0, tzinfo=UTC),
                    valid_to=None,
                    confidence=0.9,
                    supersession_reason="Found OAuth2 config in codebase",
                ),
            ],
            current=None,
        )
    )

    with (
        patch(
            "context_service.mcp.tools.history.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_history_auth),
        ),
        patch(
            "context_service.mcp.tools.history.track_tool_usage",
            new=AsyncMock(),
        ),
        patch("context_service.mcp.tools.history.get_context_service", return_value=svc),
    ):
        yield svc


@pytest.mark.asyncio
async def test_history_requires_node_id(mock_history_context):
    """history should require node_id parameter."""
    result = await _history_impl(node_id="")

    assert "error" in result
    assert result["error"] == "missing_node_id"


@pytest.mark.asyncio
async def test_history_returns_timeline(mock_history_context):
    """history should return timeline array."""
    result = await _history_impl(node_id="test-node-id")

    assert "timeline" in result
    timeline = result["timeline"]
    assert len(timeline) == 2
    assert timeline[0]["node_id"] == "oldest-abc"
    assert timeline[1]["node_id"] == "current-def"


@pytest.mark.asyncio
async def test_history_formats_timestamps(mock_history_context):
    """history should format timestamps as ISO 8601."""
    result = await _history_impl(node_id="test-node-id")

    timeline = result["timeline"]
    assert timeline[0]["valid_from"] == "2026-01-15T10:00:00+00:00"
    assert timeline[0]["valid_to"] == "2026-03-20T14:30:00+00:00"
    assert timeline[1]["valid_to"] is None


@pytest.mark.asyncio
async def test_history_omits_supersession_reason_on_root(mock_history_context):
    """history should omit supersession_reason on root node (first entry)."""
    result = await _history_impl(node_id="test-node-id")

    timeline = result["timeline"]
    assert "supersession_reason" not in timeline[0]
    assert timeline[1]["supersession_reason"] == "Found OAuth2 config in codebase"


@pytest.mark.asyncio
async def test_history_not_found(mock_history_context, mock_history_auth):
    """history should return error for non-existent node."""
    mock_history_context.history = AsyncMock(return_value=HistoryResult(timeline=[], current=None))

    result = await _history_impl(node_id="nonexistent-node")

    assert "error" in result
    assert result["error"] == "not_found"
    assert result["node_id"] == "nonexistent-node"

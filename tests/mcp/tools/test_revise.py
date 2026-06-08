# tests/mcp/tools/test_revise.py
"""Tests for revise MCP tool."""

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
    store = MagicMock()
    # Return a non-empty row list to simulate a found hypothesis.
    store.execute_write = AsyncMock(return_value=[{"updated_at": "2026-01-01T00:00:00+00:00"}])
    return store


@pytest.fixture
def mock_ctx_svc(mock_graph_store):
    svc = MagicMock()
    svc.graph_store = mock_graph_store
    return svc


def _patch_revise(mock_auth, mock_ctx_svc):
    """Return a context manager that patches all external dependencies of _revise_impl."""
    return (
        patch(
            "context_service.mcp.tools.revise.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.revise.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx_svc,
        ),
    )


@pytest.mark.asyncio
async def test_revise_updates_hypothesis(mock_auth, mock_ctx_svc):
    """revise should return updated_at and echo the belief_id and confidence."""
    from context_service.mcp.tools.revise import _revise_impl

    belief_id = "hyp-abc-123"

    with (
        patch(
            "context_service.mcp.tools.revise.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.revise.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx_svc,
        ),
    ):
        result = await _revise_impl(
            belief_id=belief_id,
            confidence=0.7,
            content=None,
            reason="Refined after new observation",
        )

    assert result.get("belief_id") == belief_id
    assert result.get("confidence") == 0.7
    assert "updated_at" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_revise_with_new_content_updates_content(mock_auth, mock_ctx_svc):
    """revise should propagate new content when provided."""
    from context_service.mcp.tools.revise import _revise_impl

    belief_id = "hyp-abc-456"
    new_content = "Updated hypothesis text"

    with (
        patch(
            "context_service.mcp.tools.revise.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.revise.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx_svc,
        ),
    ):
        result = await _revise_impl(
            belief_id=belief_id,
            confidence=0.85,
            content=new_content,
            reason="Content was imprecise",
        )

    assert result.get("content") == new_content
    assert result.get("belief_id") == belief_id
    assert "error" not in result


@pytest.mark.asyncio
async def test_revise_with_invalid_belief_id_returns_error(mock_auth, mock_ctx_svc):
    """revise should return not_found error when the hypothesis does not exist."""
    from context_service.mcp.tools.revise import _revise_impl

    # Return empty rows to simulate a missing hypothesis.
    mock_ctx_svc.graph_store.execute_write = AsyncMock(return_value=[])

    with (
        patch(
            "context_service.mcp.tools.revise.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.revise.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=mock_ctx_svc,
        ),
    ):
        result = await _revise_impl(
            belief_id="nonexistent-hyp-id",
            confidence=0.5,
            content=None,
            reason="Testing error path",
        )

    assert result.get("error") == "not_found"
    assert "nonexistent-hyp-id" in result.get("message", "")

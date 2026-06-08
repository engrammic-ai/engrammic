# tests/mcp/tools/test_decide.py
"""Tests for decide MCP tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_auth():
    """Mock MCP auth context."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.agent_id = "test-agent"
    auth.session_id = "test-session"
    return auth


@pytest.mark.asyncio
async def test_decide_creates_commitment(mock_auth) -> None:
    """decide creates a Commitment with ABOUT edges."""
    from context_service.mcp.tools.decide import _decide_impl

    from context_service.sage.transactions import CommitResult

    about_node = str(uuid.uuid4())

    mock_result = CommitResult(
        commitment_id=uuid.uuid4(),
        silo_id="test-silo",
        created_at=datetime.now(UTC),
        confidence=0.9,
    )

    with (
        patch("context_service.mcp.tools.decide.get_mcp_auth_context", new_callable=AsyncMock, return_value=mock_auth),
        patch("context_service.mcp.tools.decide.track_tool_usage", new_callable=AsyncMock),
        patch("context_service.mcp.tools.decide.get_context_service") as mock_ctx,
        patch("context_service.mcp.tools.decide.tx_commit", new_callable=AsyncMock, return_value=(mock_result, [])),
    ):
        mock_ctx.return_value.graph_store = MagicMock()

        result = await _decide_impl(
            decision="We will use PostgreSQL for persistence",
            about=[about_node],
            confidence=0.9,
        )

        assert "commitment_id" in result
        assert "error" not in result


@pytest.mark.asyncio
async def test_decide_requires_about(mock_auth) -> None:
    """decide fails without about nodes."""
    from context_service.mcp.tools.decide import _decide_impl

    with (
        patch("context_service.mcp.tools.decide.get_mcp_auth_context", new_callable=AsyncMock, return_value=mock_auth),
        patch("context_service.mcp.tools.decide.track_tool_usage", new_callable=AsyncMock),
    ):
        result = await _decide_impl(
            decision="Some decision",
            about=[],
        )

        assert result["error"] == "missing_about"

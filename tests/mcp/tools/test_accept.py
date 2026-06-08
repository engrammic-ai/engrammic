"""Tests for accept MCP tool."""

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
    return auth


@pytest.mark.asyncio
async def test_accept_promotes_proposal(mock_auth) -> None:
    """accept promotes ProposedBelief to Belief."""
    from context_service.mcp.tools.accept import _accept_impl
    from context_service.sage.transactions import AcceptProposalResult

    proposal_id = str(uuid.uuid4())
    belief_id = uuid.uuid4()

    mock_result = AcceptProposalResult(
        belief_id=belief_id,
        proposal_id=uuid.UUID(proposal_id),
        accepted=True,
        accepted_at=datetime.now(UTC),
        confidence=0.85,
    )

    with (
        patch(
            "context_service.mcp.tools.accept.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth,
        ),
        patch("context_service.mcp.tools.accept.track_tool_usage", new_callable=AsyncMock),
        patch("context_service.mcp.tools.accept.get_context_service") as mock_ctx,
        patch(
            "context_service.mcp.tools.accept.accept_proposal",
            new_callable=AsyncMock,
            return_value=(mock_result, []),
        ),
    ):
        mock_ctx.return_value.graph_store = MagicMock()

        result = await _accept_impl(
            proposal_id=proposal_id,
            reason="Verified",
        )

        assert result["belief_id"] == str(belief_id)
        assert result["accepted"] is True
        assert "error" not in result


@pytest.mark.asyncio
async def test_accept_returns_error_for_not_found(mock_auth) -> None:
    """accept returns error for non-existent proposal."""
    from context_service.mcp.tools.accept import _accept_impl
    from context_service.sage.transactions import InvariantViolation

    with (
        patch(
            "context_service.mcp.tools.accept.get_mcp_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth,
        ),
        patch("context_service.mcp.tools.accept.track_tool_usage", new_callable=AsyncMock),
        patch("context_service.mcp.tools.accept.get_context_service") as mock_ctx,
        patch(
            "context_service.mcp.tools.accept.accept_proposal", new_callable=AsyncMock
        ) as mock_accept,
    ):
        mock_accept.side_effect = InvariantViolation("PROPOSAL_NOT_FOUND", "Not found")
        mock_ctx.return_value.graph_store = MagicMock()

        result = await _accept_impl(
            proposal_id=str(uuid.uuid4()),
        )

        assert result["error"] == "PROPOSAL_NOT_FOUND"

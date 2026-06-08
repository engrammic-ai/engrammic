# tests/mcp/tools/test_commit.py
"""Tests for commit MCP tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.sage.transactions import CrystallizeResult, InvariantViolation


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.agent_id = None
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
async def test_commit_crystallizes_hypotheses(mock_auth, mock_ctx_svc):
    """commit should crystallize hypotheses and return committed IDs with confidences."""
    commitment_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    hypothesis_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    crystallize_result = CrystallizeResult(
        commitment_id=commitment_id,
        hypothesis_id=hypothesis_id,
        silo_id="test-silo",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=0.85,
    )

    with (
        patch(
            "context_service.mcp.tools.commit.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.commit.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.commit.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.commit.crystallize",
            new=AsyncMock(return_value=(crystallize_result, [])),
        ),
        patch("context_service.mcp.tools.commit.emit_reaction", new=AsyncMock()),
        patch("context_service.mcp.tools.commit.record_belief_confidence"),
        patch("context_service.mcp.tools.commit.record_mcp_tool"),
    ):
        from context_service.mcp.tools.commit import _commit_impl

        result = await _commit_impl(
            belief_ids=["00000000-0000-0000-0000-000000000001"],
        )

    assert "committed" in result
    assert "confidences" in result
    assert str(commitment_id) in result["committed"]
    assert 0.85 in result["confidences"]
    assert "errors" not in result


@pytest.mark.asyncio
async def test_commit_with_no_hypotheses_returns_empty(mock_auth, mock_ctx_svc):
    """commit with an empty belief_ids list should return empty committed and confidences."""
    with (
        patch(
            "context_service.mcp.tools.commit.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_auth),
        ),
        patch("context_service.mcp.tools.commit.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.commit.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch("context_service.mcp.tools.commit.emit_reaction", new=AsyncMock()),
        patch("context_service.mcp.tools.commit.record_belief_confidence"),
        patch("context_service.mcp.tools.commit.record_mcp_tool"),
    ):
        from context_service.mcp.tools.commit import _commit_impl

        result = await _commit_impl(belief_ids=[])

    assert result["committed"] == []
    assert result["confidences"] == []
    assert "errors" not in result


@pytest.mark.asyncio
async def test_commit_without_session_returns_error(mock_ctx_svc):
    """commit with no session_id should surface HYPOTHESIS_NOT_FOUND in errors."""
    auth_no_session = MagicMock()
    auth_no_session.org_id = "test-org"
    auth_no_session.agent_id = None
    auth_no_session.session_id = None

    belief_id = "00000000-0000-0000-0000-000000000001"

    with (
        patch(
            "context_service.mcp.tools.commit.get_mcp_auth_context",
            new=AsyncMock(return_value=auth_no_session),
        ),
        patch("context_service.mcp.tools.commit.track_tool_usage", new=AsyncMock()),
        patch(
            "context_service.mcp.tools.commit.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.commit.crystallize",
            new=AsyncMock(
                side_effect=InvariantViolation(
                    "HYPOTHESIS_NOT_FOUND",
                    "Hypothesis not found",
                )
            ),
        ),
        patch("context_service.mcp.tools.commit.emit_reaction", new=AsyncMock()),
        patch("context_service.mcp.tools.commit.record_belief_confidence"),
        patch("context_service.mcp.tools.commit.record_mcp_tool"),
    ):
        from context_service.mcp.tools.commit import _commit_impl

        result = await _commit_impl(belief_ids=[belief_id])

    assert result["committed"] == []
    assert "errors" in result
    assert len(result["errors"]) == 1
    assert result["errors"][0]["belief_id"] == belief_id
    assert result["errors"][0]["error"] == "HYPOTHESIS_NOT_FOUND"

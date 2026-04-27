"""Tests for context_commit tool."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_deps():
    with (
        patch("context_service.mcp.tools.context_commit.get_mcp_auth") as auth_mock,
        patch("context_service.mcp.tools.context_commit.get_context_service") as svc_mock,
        patch(
            "context_service.mcp.tools.context_commit.get_silo_service", return_value=MagicMock()
        ),
        patch(
            "context_service.mcp.tools.context_commit.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth.agent_id = "agent-123"
        auth_mock.return_value = auth

        svc = AsyncMock()
        node = MagicMock()
        node.id = uuid.uuid4()
        svc.commit_belief.return_value = node
        svc_mock.return_value = svc

        yield {"auth": auth, "svc": svc}


@pytest.mark.asyncio
async def test_commit_basic(mock_deps):
    from context_service.mcp.tools.context_commit import _context_commit

    result = await _context_commit(
        silo_id=_SILO_ID,
        belief="This team ships on Fridays",
        about=["node:claim-1", "node:claim-2"],
    )

    assert result["layer"] == "wisdom"
    assert result["declared_by"] == "agent-123"
    mock_deps["svc"].commit_belief.assert_called_once()


@pytest.mark.asyncio
async def test_commit_with_reasoning(mock_deps):
    from context_service.mcp.tools.context_commit import _context_commit

    result = await _context_commit(
        silo_id=_SILO_ID,
        belief="Deploy on Friday is risky",
        about=["node:claim-1"],
        reasoning="Based on 3 outages in past month",
        confidence=0.9,
    )

    assert result["layer"] == "wisdom"


@pytest.mark.asyncio
async def test_commit_missing_about(mock_deps):
    from context_service.mcp.tools.context_commit import _context_commit

    result = await _context_commit(
        silo_id=_SILO_ID,
        belief="Some belief",
        about=[],
    )

    assert result["error"] == "missing_about"


@pytest.mark.asyncio
async def test_commit_invalid_silo(mock_deps):
    from context_service.mcp.tools.context_commit import _context_commit

    with patch(
        "context_service.mcp.tools.context_commit.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_commit(
            silo_id="bad-id",
            belief="Some belief",
            about=["node:x"],
        )

    assert result["error"] == "invalid_silo_id"

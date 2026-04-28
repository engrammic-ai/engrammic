"""Tests for context_reflect tool."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_deps():
    with (
        patch(
            "context_service.mcp.tools.context_reflect.get_mcp_auth_context",
            new_callable=AsyncMock,
        ) as auth_mock,
        patch("context_service.mcp.tools.context_reflect.get_context_service") as svc_mock,
        patch(
            "context_service.mcp.tools.context_reflect.get_silo_service", return_value=MagicMock()
        ),
        patch(
            "context_service.mcp.tools.context_reflect.validate_silo_ownership",
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
        svc.reflect.return_value = node
        svc_mock.return_value = svc

        yield {"auth": auth, "svc": svc}


@pytest.mark.asyncio
async def test_reflect_basic(mock_deps):
    from context_service.mcp.tools.context_reflect import _context_reflect

    result = await _context_reflect(
        silo_id=_SILO_ID,
        observation="I changed my belief about X",
        observation_type="belief_change",
        about=["node:claim-1"],
    )

    assert "node_id" in result
    assert result["observation_type"] == "belief_change"
    assert result["about_nodes"] == ["node:claim-1"]
    mock_deps["svc"].reflect.assert_called_once()


@pytest.mark.asyncio
async def test_reflect_invalid_observation_type(mock_deps):
    from context_service.mcp.tools.context_reflect import _context_reflect

    result = await _context_reflect(
        silo_id=_SILO_ID,
        observation="Some observation",
        observation_type="not_a_type",
        about=["node:x"],
    )

    assert result["error"] == "invalid_observation_type"


@pytest.mark.asyncio
async def test_reflect_invalid_silo(mock_deps):
    from context_service.mcp.tools.context_reflect import _context_reflect

    with patch(
        "context_service.mcp.tools.context_reflect.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_reflect(
            silo_id="not-a-uuid",
            observation="Some observation",
            observation_type="insight",
            about=["node:x"],
        )

    assert result["error"] == "invalid_silo_id"

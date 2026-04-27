"""Tests for context_remember tool."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_auth():
    with patch("context_service.mcp.tools.context_remember.get_mcp_auth") as m:
        auth = MagicMock()
        auth.org_id = "test-org"
        m.return_value = auth
        yield m


@pytest.fixture
def mock_silo_valid():
    with patch(
        "context_service.mcp.tools.context_remember.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "context_service.mcp.tools.context_remember.get_silo_service",
        return_value=MagicMock(),
    ):
        yield


@pytest.fixture
def mock_context_service():
    with patch("context_service.mcp.tools.context_remember.get_context_service") as m:
        svc = AsyncMock()
        node = MagicMock()
        node.id = uuid.uuid4()
        svc.remember.return_value = node
        m.return_value = svc
        yield svc


@pytest.mark.asyncio
async def test_remember_basic(mock_auth, mock_context_service, mock_silo_valid):
    from context_service.mcp.tools.context_remember import _context_remember

    result = await _context_remember(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        content="Test observation",
    )

    assert result["layer"] == "memory"
    assert "node_id" in result
    assert "created_at" in result
    mock_context_service.remember.assert_called_once()


@pytest.mark.asyncio
async def test_remember_with_decay_class(mock_auth, mock_context_service, mock_silo_valid):
    from context_service.mcp.tools.context_remember import _context_remember

    result = await _context_remember(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        content="Ephemeral note",
        decay_class="ephemeral",
    )

    assert result["decay_class"] == "ephemeral"


@pytest.mark.asyncio
async def test_remember_invalid_silo(mock_auth):
    with patch(
        "context_service.mcp.tools.context_remember.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ), patch("context_service.mcp.tools.context_remember.get_silo_service"):
        from context_service.mcp.tools.context_remember import _context_remember

        result = await _context_remember(
            silo_id="not-a-uuid",
            content="Test",
        )

        assert result["error"] == "invalid_silo_id"

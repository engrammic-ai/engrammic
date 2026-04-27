"""Tests for context_assert tool."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_deps():
    with (
        patch("context_service.mcp.tools.context_assert.get_mcp_auth") as auth_mock,
        patch("context_service.mcp.tools.context_assert.get_context_service") as svc_mock,
        patch("context_service.mcp.tools.context_assert.get_evidence_validator") as ev_mock,
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        node = MagicMock()
        node.id = uuid.uuid4()
        svc = MagicMock()
        svc.assert_claim = AsyncMock(return_value=node)
        svc_mock.return_value = svc

        ev = AsyncMock()
        ev.validate.return_value = MagicMock(status="valid", confidence=1.0, node_id="ev-123")
        ev_mock.return_value = ev

        yield {"auth": auth, "svc": svc, "ev": ev}


@pytest.mark.asyncio
async def test_assert_with_node_evidence(mock_deps):
    from context_service.mcp.tools.context_assert import _context_assert

    result = await _context_assert(
        silo_id=_SILO_ID,
        claim="OAuth tokens expire in 30 days",
        evidence="node:abc-123",
        source_type="document",
    )

    assert result["layer"] == "knowledge"
    assert result["evidence_status"] == "verified"
    mock_deps["svc"].assert_claim.assert_called_once()


@pytest.mark.asyncio
async def test_assert_with_invalid_evidence(mock_deps):
    mock_deps["ev"].validate.return_value = MagicMock(status="invalid", reason="Not found")

    from context_service.mcp.tools.context_assert import _context_assert

    result = await _context_assert(
        silo_id=_SILO_ID,
        claim="Some claim",
        evidence="node:missing",
        source_type="document",
    )

    assert result["error"] == "invalid_evidence"


@pytest.mark.asyncio
async def test_assert_structured_claim(mock_deps):
    from context_service.mcp.tools.context_assert import _context_assert

    result = await _context_assert(
        silo_id=_SILO_ID,
        claim={"subject": "OAuth", "predicate": "expires_in", "object": "30 days"},
        evidence="node:abc-123",
        source_type="user",
    )

    assert result["claim_type"] == "structured"


@pytest.mark.asyncio
async def test_assert_invalid_silo(mock_deps):
    from context_service.mcp.tools.context_assert import _context_assert

    result = await _context_assert(
        silo_id="not-a-uuid",
        claim="Test claim",
        evidence="node:abc-123",
        source_type="document",
    )

    assert result["error"] == "invalid_silo_id"

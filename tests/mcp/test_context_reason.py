"""Tests for context_reason tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.context_meta import ReasoningChainResult

SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_auth():
    with patch("context_service.mcp.auth.get_mcp_auth") as m:
        auth = MagicMock()
        auth.org_id = "test-org"
        m.return_value = auth
        yield auth


@pytest.fixture
def mock_context_service():
    with patch("context_service.mcp.server.get_context_service") as m:
        svc = AsyncMock()
        svc.reason.return_value = ReasoningChainResult(chain_id=uuid.uuid4())
        m.return_value = svc
        yield svc


BASIC_STEPS = [
    {"step": 1, "reasoning": "The docs say tokens expire in 30 days."},
    {"step": 2, "reasoning": "No contradicting evidence found."},
]


@pytest.mark.asyncio
async def test_reason_basic(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
    )

    assert result["layer"] == "intelligence"
    assert result["steps_count"] == 2
    assert "chain_id" in result
    assert "session_id" in result
    mock_context_service.reason.assert_called_once()


@pytest.mark.asyncio
async def test_reason_with_conclusion(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_reason import _context_reason

    await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
        conclusion="OAuth tokens expire in 30 days per policy.",
    )

    call_kwargs = mock_context_service.reason.call_args
    assert call_kwargs.kwargs["conclusion"] == "OAuth tokens expire in 30 days per policy."


@pytest.mark.asyncio
async def test_reason_with_crystallizations(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
        crystallizations=[
            {"claim": "OAuth tokens expire in 30 days", "confidence": 0.9},
        ],
    )

    assert result["crystallizations_queued"] == 1


@pytest.mark.asyncio
async def test_reason_with_evidence(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_reason import _context_reason

    await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
        evidence_used=["node:abc-123", "https://docs.example.com/oauth"],
    )

    call_kwargs = mock_context_service.reason.call_args
    assert call_kwargs.kwargs["evidence_used"] == ["node:abc-123", "https://docs.example.com/oauth"]


@pytest.mark.asyncio
async def test_reason_invalid_silo(mock_auth):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id="not-a-uuid",
        steps=BASIC_STEPS,
    )

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_reason_empty_steps(mock_auth):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=[],
    )

    assert result["error"] == "missing_steps"


@pytest.mark.asyncio
async def test_reason_invalid_step_schema(mock_auth):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=[{"bad_field": "no step or reasoning here"}],
    )

    assert result["error"] == "invalid_steps"

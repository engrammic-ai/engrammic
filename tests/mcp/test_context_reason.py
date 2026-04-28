"""Tests for context_reason tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.context_meta import ReasoningChainResult

SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_deps():
    with (
        patch("context_service.mcp.server.get_mcp_auth_context") as auth_mock,
        patch("context_service.mcp.server.get_context_service") as svc_mock,
        patch("context_service.mcp.server.get_silo_service") as silo_svc_mock,
        patch(
            "context_service.mcp.tools.context_reason.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        svc = AsyncMock()
        svc.reason.return_value = ReasoningChainResult(chain_id=uuid.uuid4())
        svc_mock.return_value = svc

        silo_svc_mock.return_value = MagicMock()

        yield {"auth": auth, "svc": svc}


BASIC_STEPS = [
    {"step": 1, "reasoning": "The docs say tokens expire in 30 days."},
    {"step": 2, "reasoning": "No contradicting evidence found."},
]


@pytest.mark.asyncio
async def test_reason_basic(mock_deps):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
    )

    assert result["layer"] == "intelligence"
    assert result["steps_count"] == 2
    assert "chain_id" in result
    assert "session_id" in result
    mock_deps["svc"].reason.assert_called_once()


@pytest.mark.asyncio
async def test_reason_with_conclusion(mock_deps):
    from context_service.mcp.tools.context_reason import _context_reason

    await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
        conclusion="OAuth tokens expire in 30 days per policy.",
    )

    call_kwargs = mock_deps["svc"].reason.call_args
    assert call_kwargs.kwargs["conclusion"] == "OAuth tokens expire in 30 days per policy."


@pytest.mark.asyncio
async def test_reason_with_crystallizations(mock_deps):
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
async def test_reason_with_evidence(mock_deps):
    from context_service.mcp.tools.context_reason import _context_reason

    await _context_reason(
        silo_id=SILO_ID,
        steps=BASIC_STEPS,
        evidence_used=["node:abc-123", "https://docs.example.com/oauth"],
    )

    call_kwargs = mock_deps["svc"].reason.call_args
    assert call_kwargs.kwargs["evidence_used"] == ["node:abc-123", "https://docs.example.com/oauth"]


@pytest.mark.asyncio
async def test_reason_invalid_silo(mock_deps):
    from context_service.mcp.tools.context_reason import _context_reason

    with patch(
        "context_service.mcp.tools.context_reason.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_reason(
            silo_id="not-a-uuid",
            steps=BASIC_STEPS,
        )

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_reason_empty_steps(mock_deps):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=[],
    )

    assert result["error"] == "missing_steps"


@pytest.mark.asyncio
async def test_reason_invalid_step_schema(mock_deps):
    from context_service.mcp.tools.context_reason import _context_reason

    result = await _context_reason(
        silo_id=SILO_ID,
        steps=[{"bad_field": "no step or reasoning here"}],
    )

    assert result["error"] == "invalid_steps"

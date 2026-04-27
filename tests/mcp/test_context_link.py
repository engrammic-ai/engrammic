"""Tests for context_link tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_deps():
    with (
        patch("context_service.mcp.tools.context_link.get_mcp_auth") as auth_mock,
        patch("context_service.mcp.tools.context_link.get_context_service") as svc_mock,
        patch("context_service.mcp.tools.context_link.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_link.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        svc = AsyncMock()
        svc.link.return_value = str(uuid.uuid4())
        svc_mock.return_value = svc

        yield {"auth": auth, "svc": svc}


@pytest.mark.asyncio
async def test_link_creates_relationship(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=from_id,
        to_node=to_id,
        relationship="REFERENCES",
    )

    assert "edge_id" in result
    assert result["from_node"] == from_id
    assert result["to_node"] == to_id
    assert result["relationship"] == "REFERENCES"
    assert "created_at" in result
    mock_deps["svc"].link.assert_called_once()


@pytest.mark.asyncio
async def test_link_all_relationship_types(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    silo = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
    for rel in ["REFERENCES", "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "RELATED_TO"]:
        result = await _context_link(
            silo_id=silo,
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship=rel,
        )
        assert "error" not in result, f"Failed for {rel}: {result}"


@pytest.mark.asyncio
async def test_link_invalid_relationship(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="INVALID_REL",
    )

    assert result["error"] == "invalid_relationship"
    assert "valid" in result


@pytest.mark.asyncio
async def test_link_invalid_silo_id(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    with patch(
        "context_service.mcp.tools.context_link.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_link(
            silo_id="not-a-uuid",
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship="REFERENCES",
        )

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_link_wrong_silo_id(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    with patch(
        "context_service.mcp.tools.context_link.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "silo_not_found", "silo_id": str(uuid.uuid4())},
    ):
        result = await _context_link(
            silo_id=str(uuid.uuid4()),
            from_node=str(uuid.uuid4()),
            to_node=str(uuid.uuid4()),
            relationship="REFERENCES",
        )

    assert result["error"] == "silo_not_found"


@pytest.mark.asyncio
async def test_link_with_weight_and_note(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="SUPPORTS",
        weight=0.7,
        note="Strong structural support",
    )

    assert "error" not in result
    call_kwargs = mock_deps["svc"].link.call_args.kwargs
    assert call_kwargs["weight"] == 0.7
    assert call_kwargs["note"] == "Strong structural support"


@pytest.mark.asyncio
async def test_link_invalid_weight(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    result = await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node=str(uuid.uuid4()),
        to_node=str(uuid.uuid4()),
        relationship="REFERENCES",
        weight=99.9,
    )

    assert result["error"] == "invalid_weight"


@pytest.mark.asyncio
async def test_link_passes_correct_relationship_to_service(mock_deps):
    from context_service.mcp.tools.context_link import _context_link

    await _context_link(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        from_node="node-a",
        to_node="node-b",
        relationship="CONTRADICTS",
    )

    call_kwargs = mock_deps["svc"].link.call_args.kwargs
    assert call_kwargs["relationship"] == "CONTRADICTS"
    assert call_kwargs["from_node"] == "node-a"
    assert call_kwargs["to_node"] == "node-b"

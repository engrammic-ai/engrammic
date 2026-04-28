"""Tests for context_provenance tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.context_meta import ProvenanceResult, ProvenanceStep

SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


@pytest.fixture
def mock_auth():
    with patch("context_service.mcp.server.get_mcp_auth_context") as m:
        auth = MagicMock()
        auth.org_id = "test-org"
        m.return_value = auth
        yield auth


@pytest.fixture
def mock_context_service():
    with patch("context_service.mcp.server.get_context_service") as m:
        svc = AsyncMock()
        svc.provenance.return_value = ProvenanceResult(
            chain=[
                ProvenanceStep(
                    node_id="claim-1",
                    layer="Claim",
                    relationship="DERIVED_FROM",
                    confidence=0.9,
                ),
                ProvenanceStep(
                    node_id="passage-1",
                    layer="Passage",
                    relationship="PROMOTED_FROM",
                    confidence=1.0,
                ),
            ],
            root_sources=[
                {
                    "node_id": "passage-1",
                    "layer": "Passage",
                    "content": "Original passage",
                    "confidence": 1.0,
                }
            ],
        )
        m.return_value = svc
        yield svc


@pytest.mark.asyncio
async def test_provenance_returns_chain(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_provenance import _context_provenance

    result = await _context_provenance(
        silo_id=SILO_ID,
        node_id="some-node-id",
    )

    assert "chain" in result
    assert "root_sources" in result
    assert result["chain_length"] == 2
    mock_context_service.provenance.assert_called_once()


@pytest.mark.asyncio
async def test_provenance_passes_correct_args(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_provenance import _context_provenance

    node_id = "target-node"
    await _context_provenance(
        silo_id=SILO_ID,
        node_id=node_id,
        max_depth=5,
    )

    call_kwargs = mock_context_service.provenance.call_args
    assert call_kwargs.kwargs["node_id"] == node_id
    assert call_kwargs.kwargs["max_depth"] == 5


@pytest.mark.asyncio
async def test_provenance_invalid_silo(mock_auth):
    from context_service.mcp.tools.context_provenance import _context_provenance

    result = await _context_provenance(
        silo_id="not-a-uuid",
        node_id="some-node",
    )

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_provenance_missing_node_id(mock_auth):
    from context_service.mcp.tools.context_provenance import _context_provenance

    result = await _context_provenance(
        silo_id=SILO_ID,
        node_id="",
    )

    assert result["error"] == "missing_node_id"


@pytest.mark.asyncio
async def test_provenance_empty_chain(mock_auth, mock_context_service):
    from context_service.mcp.tools.context_provenance import _context_provenance

    mock_context_service.provenance.return_value = ProvenanceResult(
        chain=[],
        root_sources=[],
    )

    result = await _context_provenance(
        silo_id=SILO_ID,
        node_id="leaf-node",
    )

    assert result["chain"] == []
    assert result["root_sources"] == []
    assert result["chain_length"] == 0

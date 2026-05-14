"""Shared fixtures for MCP tool tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_mcp_auth_context():
    """Mock MCP auth context."""
    auth = MagicMock()
    auth.org_id = "test-org"
    auth.session_id = "test-session-123"
    return auth


@pytest.fixture
def mock_mcp_context(mock_mcp_auth_context):
    """Patch get_mcp_auth_context to return mock."""
    with patch(
        "context_service.mcp.server.get_mcp_auth_context",
        new=AsyncMock(return_value=mock_mcp_auth_context),
    ):
        yield mock_mcp_auth_context


@pytest.fixture
def mock_context_service():
    """Mock context service with common methods."""
    svc = MagicMock()
    svc.store = AsyncMock(return_value={"node_id": "test-node-id", "created_at": "2026-01-01T00:00:00Z"})
    svc.provenance = AsyncMock(return_value=MagicMock(chain=[], root_sources=[]))
    svc.graph_store = MagicMock()
    svc.graph_store.execute_query = AsyncMock(return_value=[])

    with patch("context_service.mcp.server.get_context_service", return_value=svc):
        yield svc


@pytest.fixture
def mock_evidence_validator():
    """Mock evidence validator."""
    validator = MagicMock()
    validator.validate = AsyncMock(return_value={"valid": True, "resolved": []})

    with patch("context_service.mcp.server.get_evidence_validator", return_value=validator):
        yield validator

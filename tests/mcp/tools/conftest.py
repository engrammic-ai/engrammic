"""Shared fixtures for MCP tool tests."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def reset_preset_cache() -> Generator[None, None, None]:
    """Reset the preset config cache before and after a test.

    Non-autouse: opt in when a test needs to load synthetic preset config
    (e.g. by patching the YAML path). Prevents the module-level cache from
    leaking real or synthetic config across tests.
    """
    import context_service.mcp.tools.preset_registry as preset_mod

    preset_mod._cached_config = None
    yield
    preset_mod._cached_config = None


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
    with (
        patch(
            "context_service.mcp.tools.context_store.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_mcp_auth_context),
        ),
        patch(
            "context_service.mcp.tools.trace.get_mcp_auth_context",
            new=AsyncMock(return_value=mock_mcp_auth_context),
        ),
    ):
        yield mock_mcp_auth_context


@pytest.fixture
def mock_context_service():
    """Mock context service with common methods."""
    node = MagicMock()
    node.id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    svc = MagicMock()
    svc.store = AsyncMock(
        return_value={"node_id": "test-node-id", "created_at": "2026-01-01T00:00:00Z"}
    )
    svc.remember = AsyncMock(return_value=node)
    svc.assert_claim = AsyncMock(return_value=node)
    svc.commit = AsyncMock(return_value=node)
    svc.commit_belief = AsyncMock(return_value=node)
    svc.provenance = AsyncMock(return_value=MagicMock(chain=[], root_sources=[]))
    svc.graph_store = MagicMock()
    svc.graph_store.execute_query = AsyncMock(return_value=[])

    with (
        patch("context_service.mcp.tools.context_store.get_context_service", return_value=svc),
        patch("context_service.mcp.tools.trace.get_context_service", return_value=svc),
    ):
        yield svc


@pytest.fixture
def mock_evidence_validator():
    """Mock evidence validator."""
    validation_result = MagicMock()
    validation_result.status = "valid"
    validation_result.reason = None
    validation_result.node_id = "test-node-id"

    validator = MagicMock()
    validator.validate = AsyncMock(return_value=validation_result)

    with patch(
        "context_service.mcp.tools.context_store.get_evidence_validator", return_value=validator
    ):
        yield validator

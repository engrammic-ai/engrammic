"""Shared fixtures for retrieval unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from context_service.retrieval.fusion import FusionRetriever


@pytest.fixture
def scope_context() -> MagicMock:
    """Minimal ScopeContext mock with a fixed silo_id."""
    ctx = MagicMock()
    ctx.silo_id = UUID("00000000-0000-0000-0000-000000000001")
    return ctx


@pytest.fixture
def fusion_retriever() -> FusionRetriever:
    """FusionRetriever with a stub ContextService (no real stores needed)."""
    ctx_svc = MagicMock()
    ctx_svc.query = AsyncMock(return_value=[])
    ctx_svc.graph_traversal = AsyncMock(return_value=MagicMock(nodes=[]))
    return FusionRetriever(ctx_svc=ctx_svc, k=60)

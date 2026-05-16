"""Tests for PostgresBindingSource."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from context_service.mcp.postgres_binding_source import PostgresBindingSource


def _make_mock_session(scalar_result: str | None) -> MagicMock:
    """Build an async-context-manager session mock that returns scalar_result."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_session)
    return mock_factory


@pytest.mark.asyncio
async def test_returns_preset_for_bound_silo():
    silo_id = str(uuid4())
    mock_factory = _make_mock_session("b2b-ops")

    with patch("context_service.db.postgres._session_factory", mock_factory):
        src = PostgresBindingSource()
        result = await src.get_silo_preset_name(silo_id)

    assert result == "b2b-ops"


@pytest.mark.asyncio
async def test_returns_none_for_unbound_or_missing_silo():
    silo_id = str(uuid4())
    mock_factory = _make_mock_session(None)

    with patch("context_service.db.postgres._session_factory", mock_factory):
        src = PostgresBindingSource()
        result = await src.get_silo_preset_name(silo_id)

    assert result is None

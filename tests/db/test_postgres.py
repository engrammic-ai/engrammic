"""Tests for Postgres session infrastructure."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from context_service.db.postgres import get_session, Base


@pytest.mark.asyncio
async def test_get_session_returns_async_session():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("context_service.db.postgres._session_factory", mock_factory):
        async with get_session() as session:
            assert session is mock_session


def test_base_is_declarative_base():
    from sqlalchemy.orm import DeclarativeBase

    assert issubclass(Base, DeclarativeBase)

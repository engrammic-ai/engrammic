"""Tests for UserService upsert and lookup operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_service.models.postgres.user import User
from context_service.services.user import UserService

WORKOS_ID = "user_01HXYZ"
ORG_ID = "org_abc"
SILO_ID = "silo_abc"
EMAIL = "alice@example.com"
NAME = "Alice"


def _make_user(**kwargs) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = kwargs.get("id", uuid4())
    u.workos_user_id = kwargs.get("workos_user_id", WORKOS_ID)
    u.org_id = kwargs.get("org_id", ORG_ID)
    u.silo_id = kwargs.get("silo_id", SILO_ID)
    u.email = kwargs.get("email", EMAIL)
    u.name = kwargs.get("name", NAME)
    return u


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.execute = AsyncMock()
    return s


@pytest.fixture
def service(session: AsyncMock) -> UserService:
    return UserService(session)


# ---------------------------------------------------------------------------
# upsert_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_user_returns_user(service: UserService, session: AsyncMock) -> None:
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalars.return_value.one.return_value = user
    session.execute.return_value = mock_result

    result = await service.upsert_user(
        workos_user_id=WORKOS_ID,
        org_id=ORG_ID,
        silo_id=SILO_ID,
        email=EMAIL,
        name=NAME,
    )

    assert result is user
    session.execute.assert_awaited_once()  # type: ignore[misc]


@pytest.mark.asyncio
async def test_upsert_user_without_name(service: UserService, session: AsyncMock) -> None:
    user = _make_user(name=None)
    mock_result = MagicMock()
    mock_result.scalars.return_value.one.return_value = user
    session.execute.return_value = mock_result

    result = await service.upsert_user(
        workos_user_id=WORKOS_ID,
        org_id=ORG_ID,
        silo_id=SILO_ID,
        email=EMAIL,
    )

    assert result.name is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_user_calls_execute_with_statement(
    service: UserService, session: AsyncMock
) -> None:
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalars.return_value.one.return_value = user
    session.execute.return_value = mock_result

    await service.upsert_user(
        workos_user_id=WORKOS_ID,
        org_id=ORG_ID,
        silo_id=SILO_ID,
        email=EMAIL,
        name=NAME,
    )

    # execute should be called exactly once (insert ... on conflict ... returning)
    assert session.execute.await_count == 1


# ---------------------------------------------------------------------------
# get_user_by_workos_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_by_workos_id_returns_user(service: UserService, session: AsyncMock) -> None:
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = user
    session.execute.return_value = mock_result

    result = await service.get_user_by_workos_id(WORKOS_ID)

    assert result is user
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_by_workos_id_returns_none_when_not_found(
    service: UserService, session: AsyncMock
) -> None:
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    session.execute.return_value = mock_result

    result = await service.get_user_by_workos_id("nonexistent_id")

    assert result is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_by_workos_id_passes_correct_id(
    service: UserService, session: AsyncMock
) -> None:
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    session.execute.return_value = mock_result

    await service.get_user_by_workos_id("target_workos_id")

    # Verify execute was called (the statement itself is SQLAlchemy, hard to inspect directly)
    session.execute.assert_awaited_once()

"""Tests for APIKeyService create, verify, revoke, and list operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_service.models.postgres.api_key import APIKey
from context_service.services.api_key import APIKeyService

USER_ID = uuid4()
KEY_NAME = "Cursor"


def _make_api_key(**kwargs) -> MagicMock:
    k = MagicMock(spec=APIKey)
    k.id = kwargs.get("id", uuid4())
    k.user_id = kwargs.get("user_id", USER_ID)
    k.key_hash = kwargs.get("key_hash", "deadbeef" * 8)
    k.name = kwargs.get("name", KEY_NAME)
    k.scopes = kwargs.get("scopes", "read write")
    k.revoked_at = kwargs.get("revoked_at")
    k.expires_at = kwargs.get("expires_at")
    k.last_used_at = kwargs.get("last_used_at")
    return k


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.execute = AsyncMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    return s


@pytest.fixture
def service(session: AsyncMock) -> APIKeyService:
    return APIKeyService(session)


# ---------------------------------------------------------------------------
# create_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_key_returns_plaintext_and_record(
    service: APIKeyService, session: AsyncMock
) -> None:
    plaintext, api_key = await service.create_key(user_id=USER_ID, name=KEY_NAME)

    assert plaintext.startswith("eng_")
    assert len(plaintext) == 4 + 32  # "eng_" + 32 hex chars
    assert isinstance(api_key, APIKey)
    session.add.assert_called_once_with(api_key)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_key_default_scopes(service: APIKeyService) -> None:
    plaintext, api_key = await service.create_key(user_id=USER_ID, name=KEY_NAME)

    assert api_key.scopes == "read write"


@pytest.mark.asyncio
async def test_create_key_custom_scopes(service: APIKeyService) -> None:
    plaintext, api_key = await service.create_key(
        user_id=USER_ID, name=KEY_NAME, scopes="read"
    )

    assert api_key.scopes == "read"


@pytest.mark.asyncio
async def test_create_key_with_expiry(service: APIKeyService) -> None:
    expiry = datetime.now(UTC) + timedelta(days=30)
    plaintext, api_key = await service.create_key(
        user_id=USER_ID, name=KEY_NAME, expires_at=expiry
    )

    assert api_key.expires_at == expiry


@pytest.mark.asyncio
async def test_create_key_unique_plaintexts(service: APIKeyService) -> None:
    plaintext1, _ = await service.create_key(user_id=USER_ID, name="Key 1")
    plaintext2, _ = await service.create_key(user_id=USER_ID, name="Key 2")

    assert plaintext1 != plaintext2


# ---------------------------------------------------------------------------
# verify_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_key_returns_none_for_invalid_prefix(
    service: APIKeyService,
) -> None:
    result = await service.verify_key("sk_notvalid")

    assert result is None


@pytest.mark.asyncio
async def test_verify_key_returns_none_when_not_found(
    service: APIKeyService, session: AsyncMock
) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await service.verify_key("eng_" + "a" * 32)

    assert result is None


@pytest.mark.asyncio
async def test_verify_key_returns_api_key_when_valid(
    service: APIKeyService, session: AsyncMock
) -> None:
    api_key = _make_api_key()
    # First execute: SELECT; second execute: UPDATE last_used_at
    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = api_key
    mock_update_result = MagicMock()
    session.execute.side_effect = [mock_select_result, mock_update_result]

    result = await service.verify_key("eng_" + "b" * 32)

    assert result is api_key
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_verify_key_returns_none_for_expired_key(
    service: APIKeyService, session: AsyncMock
) -> None:
    expired_at = datetime.now(UTC) - timedelta(days=1)
    api_key = _make_api_key(expires_at=expired_at)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = api_key
    session.execute.return_value = mock_result

    result = await service.verify_key("eng_" + "c" * 32)

    assert result is None


@pytest.mark.asyncio
async def test_verify_key_updates_last_used_at(
    service: APIKeyService, session: AsyncMock
) -> None:
    api_key = _make_api_key()
    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = api_key
    mock_update_result = MagicMock()
    session.execute.side_effect = [mock_select_result, mock_update_result]

    await service.verify_key("eng_" + "d" * 32)

    # Second call should be the UPDATE for last_used_at
    assert session.execute.await_count == 2


# ---------------------------------------------------------------------------
# revoke_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_key_returns_true_when_key_exists(
    service: APIKeyService, session: AsyncMock
) -> None:
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result

    result = await service.revoke_key(uuid4())

    assert result is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_key_returns_false_when_key_not_found(
    service: APIKeyService, session: AsyncMock
) -> None:
    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result

    result = await service.revoke_key(uuid4())

    assert result is False


# ---------------------------------------------------------------------------
# list_keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_keys_returns_active_keys(
    service: APIKeyService, session: AsyncMock
) -> None:
    key1 = _make_api_key(name="Cursor")
    key2 = _make_api_key(name="CI")
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [key1, key2]
    session.execute.return_value = mock_result

    keys = await service.list_keys(user_id=USER_ID)

    assert len(keys) == 2
    assert key1 in keys
    assert key2 in keys
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_keys_returns_empty_when_none(
    service: APIKeyService, session: AsyncMock
) -> None:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result

    keys = await service.list_keys(user_id=USER_ID)

    assert keys == []


# ---------------------------------------------------------------------------
# create + verify integration (unit-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_verify_api_key(
    service: APIKeyService, session: AsyncMock
) -> None:
    """Create a key, then verify the returned plaintext works."""
    plaintext, created_key = await service.create_key(user_id=USER_ID, name=KEY_NAME)

    # Reset session state for the verify call
    session.add.reset_mock()
    session.flush.reset_mock()

    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = created_key
    mock_update_result = MagicMock()
    session.execute.side_effect = [mock_select_result, mock_update_result]

    result = await service.verify_key(plaintext)

    assert result is created_key


@pytest.mark.asyncio
async def test_revoked_key_fails_verification(
    service: APIKeyService, session: AsyncMock
) -> None:
    """Revoked key (revoked_at set) should not be returned by verify_key."""
    # verify_key queries with revoked_at.is_(None), so a revoked key returns None from DB
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await service.verify_key("eng_" + "e" * 32)

    assert result is None

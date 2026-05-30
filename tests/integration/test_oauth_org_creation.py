"""Callback provisions a real org for no-org self-serve signup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.api.routes.oauth import callback


@asynccontextmanager
async def _fake_session() -> AsyncIterator[AsyncMock]:
    yield AsyncMock()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_signup_creates_org_when_user_has_none() -> None:
    user_info = {
        "id": "wos-user-1",
        "email": "alice@example.com",
        "organization_id": None,
        "name": "Alice Example",
    }
    with (
        patch(
            "context_service.api.routes.oauth.exchange_code_for_user",
            AsyncMock(return_value=user_info),
        ),
        patch("context_service.api.routes.oauth.get_session", _fake_session),
        patch(
            "context_service.api.routes.oauth.resolve_or_create_org",
            AsyncMock(return_value="org-new"),
        ) as resolve_mock,
        patch("context_service.api.routes.oauth.UserService") as MockSvc,
    ):
        MockSvc.return_value.upsert_user = AsyncMock(return_value=MagicMock())
        resp = await callback(code="code-1", state=None, error=None, error_description=None)

    resolve_mock.assert_awaited_once()
    kwargs = resolve_mock.await_args.kwargs
    assert kwargs["workos_user_id"] == "wos-user-1"
    assert kwargs["session_org_id"] is None
    assert kwargs["name"] == "Alice Example"
    # upsert receives the real org id (not the user-id fallback)
    upsert_kwargs = MockSvc.return_value.upsert_user.await_args.kwargs
    assert upsert_kwargs["org_id"] == "org-new"
    assert resp.status_code == 200

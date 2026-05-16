"""Tests for admin route authentication (S-01 fix)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from context_service.api.routes.admin import _require_admin_key


def _make_settings(
    is_production: bool = False,
    admin_api_key: str | None = None,
) -> MagicMock:
    settings = MagicMock()
    settings.is_production = is_production
    if admin_api_key is None:
        settings.security.admin_api_key = None
    else:
        settings.security.admin_api_key = MagicMock()
        settings.security.admin_api_key.get_secret_value.return_value = admin_api_key
    return settings


class TestAdminAuthProduction:
    def test_production_without_admin_key_configured_raises_503(self) -> None:
        """In production with no admin_api_key configured, should raise 503."""
        settings = _make_settings(is_production=True, admin_api_key=None)
        with (
            patch(
                "context_service.api.routes.admin.get_settings",
                return_value=settings,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            _require_admin_key(credentials=None)
        assert exc_info.value.status_code == 503
        assert "admin_api_key required in production" in exc_info.value.detail

    def test_dev_without_admin_key_configured_allows_access(self) -> None:
        """In development with no admin_api_key configured, should allow access."""
        settings = _make_settings(is_production=False, admin_api_key=None)
        with patch(
            "context_service.api.routes.admin.get_settings",
            return_value=settings,
        ):
            # Should not raise
            _require_admin_key(credentials=None)

    def test_production_with_valid_key_allows_access(self) -> None:
        """In production with valid admin key, should allow access."""
        settings = _make_settings(is_production=True, admin_api_key="secret-key")
        credentials = MagicMock()
        credentials.credentials = "secret-key"
        with patch(
            "context_service.api.routes.admin.get_settings",
            return_value=settings,
        ):
            # Should not raise
            _require_admin_key(credentials=credentials)

    def test_production_with_invalid_key_raises_401(self) -> None:
        """In production with invalid admin key, should raise 401."""
        settings = _make_settings(is_production=True, admin_api_key="secret-key")
        credentials = MagicMock()
        credentials.credentials = "wrong-key"
        with (
            patch(
                "context_service.api.routes.admin.get_settings",
                return_value=settings,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            _require_admin_key(credentials=credentials)
        assert exc_info.value.status_code == 401

"""Tests for tier management admin endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestGetSiloTier:
    async def test_returns_cached_tier(self) -> None:
        mock_redis = AsyncMock()
        mock_redis._redis = AsyncMock()
        mock_redis._redis.get = AsyncMock(return_value=b"pro")

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.default_tier = "free"

            from context_service.api.routes.admin import get_silo_tier

            result = await get_silo_tier(silo_id="test_silo", redis=mock_redis)

            assert result["tier"] == "pro"
            assert result["is_cached"] is True

    async def test_returns_default_when_not_cached(self) -> None:
        mock_redis = AsyncMock()
        mock_redis._redis = AsyncMock()
        mock_redis._redis.get = AsyncMock(return_value=None)

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.default_tier = "free"

            from context_service.api.routes.admin import get_silo_tier

            result = await get_silo_tier(silo_id="test_silo", redis=mock_redis)

            assert result["tier"] == "free"
            assert result["is_cached"] is False

    async def test_returns_silo_id_in_response(self) -> None:
        mock_redis = AsyncMock()
        mock_redis._redis = AsyncMock()
        mock_redis._redis.get = AsyncMock(return_value=b"starter")

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.default_tier = "free"

            from context_service.api.routes.admin import get_silo_tier

            result = await get_silo_tier(silo_id="my_silo", redis=mock_redis)

            assert result["silo_id"] == "my_silo"


class TestSetSiloTier:
    async def test_sets_tier_in_cache(self) -> None:
        mock_redis = AsyncMock()
        mock_redis._redis = AsyncMock()
        mock_redis._redis.set = AsyncMock(return_value=True)

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.tiers = {
                "free": {}, "starter": {}, "pro": {}, "enterprise": {}
            }
            mock_settings.return_value.security.rate_limit.tier_cache_ttl_seconds = 300

            from context_service.api.routes.admin import set_silo_tier

            result = await set_silo_tier(silo_id="test_silo", tier="pro", redis=mock_redis)

            assert result["tier"] == "pro"
            assert result["silo_id"] == "test_silo"
            assert result["cache_ttl_seconds"] == 300
            mock_redis._redis.set.assert_called_once()

    async def test_rejects_invalid_tier(self) -> None:
        mock_redis = AsyncMock()

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.tiers = {"free": {}, "pro": {}}

            from context_service.api.routes.admin import set_silo_tier

            with pytest.raises(HTTPException) as exc_info:
                await set_silo_tier(silo_id="test", tier="invalid", redis=mock_redis)

            assert exc_info.value.status_code == 400
            assert "invalid" in exc_info.value.detail
            assert "Valid tiers" in exc_info.value.detail

    async def test_cache_key_uses_tier_prefix(self) -> None:
        mock_redis = AsyncMock()
        mock_redis._redis = AsyncMock()
        mock_redis._redis.set = AsyncMock(return_value=True)

        with patch("context_service.api.routes.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.security.rate_limit.tiers = {"free": {}, "pro": {}}
            mock_settings.return_value.security.rate_limit.tier_cache_ttl_seconds = 600

            from context_service.api.routes.admin import set_silo_tier

            await set_silo_tier(silo_id="acme", tier="pro", redis=mock_redis)

            call_args = mock_redis._redis.set.call_args
            assert call_args[0][0] == "tier:acme"
            assert call_args[0][1] == b"pro"
            assert call_args[1]["ex"] == 600

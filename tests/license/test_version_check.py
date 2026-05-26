"""Tests for version check functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.license.version_check import check_version, VersionCheckResult


@pytest.fixture
def mock_httpx_response():
    """Factory for mock httpx responses."""
    def _make_response(data: dict, status_code: int = 200):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = data
        mock.raise_for_status = MagicMock()
        if status_code >= 400:
            mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return mock
    return _make_response


@pytest.mark.asyncio
async def test_check_version_current_is_latest(mock_httpx_response):
    """No warning when running latest version."""
    response = mock_httpx_response({
        "latest": "0.1.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.1.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.UP_TO_DATE


@pytest.mark.asyncio
async def test_check_version_newer_available(mock_httpx_response):
    """Info logged when newer version available."""
    response = mock_httpx_response({
        "latest": "0.2.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.1.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.UPDATE_AVAILABLE


@pytest.mark.asyncio
async def test_check_version_deprecated(mock_httpx_response):
    """Warning logged when running deprecated version."""
    response = mock_httpx_response({
        "latest": "0.3.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.2.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.5"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.DEPRECATED


@pytest.mark.asyncio
async def test_check_version_unsupported(mock_httpx_response):
    """Error raised when below minimum supported."""
    response = mock_httpx_response({
        "latest": "0.3.0",
        "minimum_supported": "0.2.0",
        "deprecation_threshold": "0.2.5",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            with pytest.raises(SystemExit) as exc_info:
                await check_version()

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_check_version_network_failure():
    """Graceful degradation when endpoint unreachable."""
    with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        result = await check_version()

    assert result == VersionCheckResult.CHECK_FAILED


@pytest.mark.asyncio
async def test_check_version_strips_dev_suffix(mock_httpx_response):
    """Dev suffix is stripped before comparison."""
    response = mock_httpx_response({
        "latest": "0.1.0",
        "minimum_supported": "0.1.0",
        "deprecation_threshold": "0.1.0",
    })

    with patch("context_service.license.version_check.__version__", "0.1.0-dev"):
        with patch("context_service.license.version_check.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = await check_version()

    assert result == VersionCheckResult.UP_TO_DATE

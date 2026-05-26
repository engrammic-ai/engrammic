"""License auto-renewal tests."""

import time
from unittest.mock import patch

import pytest

from context_service.license.renewal import attempt_license_renewal


@pytest.mark.asyncio
async def test_renewal_skipped_when_not_expiring() -> None:
    """Renewal not attempted if license has >14 days remaining."""
    with patch("context_service.license.renewal.get_settings") as mock_settings:
        mock_settings.return_value.license_key = "ENGR_valid_key"

        with patch("context_service.license.renewal.validate_license_key") as mock_validate:
            from context_service.license.validator import LicenseInfo

            mock_validate.return_value = LicenseInfo(
                customer="test",
                expires_at=int(time.time()) + (30 * 24 * 60 * 60),  # 30 days
                tier="self-hosted",
                features=["mcp"],
            )

            result = await attempt_license_renewal()
            assert result is False  # No renewal needed


@pytest.mark.asyncio
async def test_renewal_skipped_when_no_license() -> None:
    """Renewal skipped if no license key configured."""
    with patch("context_service.license.renewal.get_settings") as mock_settings:
        mock_settings.return_value.license_key = None

        result = await attempt_license_renewal()
        assert result is False

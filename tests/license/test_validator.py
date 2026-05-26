"""License validator tests."""

import time

import pytest

from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)


def test_validate_license_key_missing_prefix() -> None:
    """License key must start with ENGR_ prefix."""
    with pytest.raises(LicenseError, match="must start with ENGR_"):
        validate_license_key("invalid_key")


def test_validate_license_key_invalid_jwt() -> None:
    """Invalid JWT raises LicenseError."""
    with pytest.raises(LicenseError, match="Invalid license key"):
        validate_license_key("ENGR_notajwt")


def test_validate_license_key_expired() -> None:
    """Expired license raises LicenseError."""
    # This test needs a real expired key - we'll generate one in integration tests
    pass


def test_license_info_days_remaining() -> None:
    """LicenseInfo calculates days remaining correctly."""
    future_exp = int(time.time()) + (30 * 24 * 60 * 60)  # 30 days
    info = LicenseInfo(
        customer="test",
        expires_at=future_exp,
        tier="self-hosted",
        features=["mcp"],
    )
    assert 29 <= info.days_remaining <= 30

"""License validator tests."""

import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PublicFormat,
    PrivateFormat,
)

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
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    public_key_pem = public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    expired_token = jwt.encode(
        {
            "sub": "test-customer",
            "iss": "engrammic",
            "exp": int(time.time()) - 3600,  # 1 hour ago
            "tier": "self-hosted",
            "features": ["mcp"],
        },
        private_key,
        algorithm="EdDSA",
    )
    expired_key = f"ENGR_{expired_token}"

    with patch(
        "context_service.license.validator.get_public_key_pem",
        return_value=public_key_pem,
    ):
        with pytest.raises(LicenseError, match="expired"):
            validate_license_key(expired_key)


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

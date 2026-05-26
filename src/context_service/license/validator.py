"""License key validation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from context_service.license.keys import get_public_key_pem

KEY_PREFIX = "ENGR_"
ISSUER = "engrammic"


class LicenseError(Exception):
    """License validation failed."""

    pass


@dataclass
class LicenseInfo:
    """Validated license information."""

    customer: str
    expires_at: int  # Unix timestamp
    tier: str
    features: list[str] = field(default_factory=list)

    @property
    def days_remaining(self) -> int:
        """Days until license expires."""
        remaining_seconds = self.expires_at - int(time.time())
        return max(0, remaining_seconds // (24 * 60 * 60))

    @property
    def is_expiring_soon(self) -> bool:
        """True if license expires in less than 14 days."""
        return self.days_remaining < 14


def validate_license_key(key: str) -> LicenseInfo:
    """Validate license key and return license info.

    Args:
        key: License key string (with ENGR_ prefix)

    Returns:
        LicenseInfo with validated license details

    Raises:
        LicenseError: If license is invalid, expired, or malformed
    """
    if not key.startswith(KEY_PREFIX):
        raise LicenseError(f"License key must start with {KEY_PREFIX}")

    token = key[len(KEY_PREFIX):]

    public_key_pem = get_public_key_pem()
    raw_key = load_pem_public_key(public_key_pem.encode())
    if not isinstance(raw_key, Ed25519PublicKey):
        raise LicenseError("Embedded public key is not an Ed25519 key")
    public_key: Ed25519PublicKey = raw_key

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            issuer=ISSUER,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise LicenseError("License key has expired") from e
    except jwt.InvalidIssuerError as e:
        raise LicenseError("License key has invalid issuer") from e
    except jwt.DecodeError as e:
        raise LicenseError(f"Invalid license key: {e}") from e

    return LicenseInfo(
        customer=payload["sub"],
        expires_at=payload["exp"],
        tier=payload.get("tier", "self-hosted"),
        features=payload.get("features", []),
    )

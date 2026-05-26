"""License renewal endpoint for self-hosted customers."""

import os
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from context_service.config.logging import get_logger
from context_service.license.validator import LicenseError, validate_license_key

logger = get_logger(__name__)

router = APIRouter(prefix="/license", tags=["license"])

ISSUER = "engrammic"
KEY_PREFIX = "ENGR_"


class RenewalResponse(BaseModel):
    key: str


@router.post("/renew", response_model=RenewalResponse)
async def renew_license(authorization: str = Header(...)) -> RenewalResponse:
    """Renew a license key. Called by self-hosted containers."""
    private_key_pem = os.environ.get("LICENSE_PRIVATE_KEY")
    if not private_key_pem:
        raise HTTPException(status_code=503, detail="Renewal not configured")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization")

    old_key = authorization[7:]

    # Verify the license signature before renewing (prevents forged licenses)
    try:
        license_info = validate_license_key(old_key)
    except LicenseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    customer = license_info.customer

    # TODO: Check customer status in database (payment active, not revoked)
    # For MVP, always renew if key is cryptographically valid

    try:
        private_key = cast(
            Ed25519PrivateKey,
            serialization.load_pem_private_key(private_key_pem.encode(), password=None),
        )
    except Exception:
        logger.error("license_private_key_invalid")
        raise HTTPException(status_code=503, detail="Renewal not configured") from None

    now = datetime.now(UTC)
    new_payload = {
        "sub": customer,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=90)).timestamp()),
        "tier": license_info.tier,
        "features": license_info.features,
    }

    new_token = jwt.encode(new_payload, private_key, algorithm="EdDSA")
    logger.info("license_renewed", customer=customer)
    return RenewalResponse(key=f"{KEY_PREFIX}{new_token}")

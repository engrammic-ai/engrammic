"""License renewal endpoint for self-hosted customers."""

import os
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from context_service.config.logging import get_logger
from context_service.db.postgres import get_session
from context_service.license.validator import LicenseError, validate_license_key

logger = get_logger(__name__)

router = APIRouter(prefix="/license", tags=["license"])

ISSUER = "engrammic"
KEY_PREFIX = "ENGR_"


class RenewalResponse(BaseModel):
    key: str


async def check_license_status(customer_id: str) -> tuple[bool, str | None]:
    """Check if customer's license is eligible for renewal.

    Returns:
        (eligible, reason) - eligible is True if renewal allowed, reason explains denial
    """
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT status, subscription_end_date
                FROM licenses
                WHERE customer_id = :customer_id
            """),
            {"customer_id": customer_id},
        )
        row = result.fetchone()

        if row is None:
            logger.warning("license_customer_not_found", customer_id=customer_id)
            return False, "Customer not found in license database"

        status, subscription_end = row

        if status == "revoked":
            return False, "License has been revoked"
        if status == "suspended":
            return False, "License is suspended - contact support"
        if status == "expired":
            return False, "Subscription has expired - renew your subscription"

        if subscription_end and subscription_end < datetime.now(UTC):
            return False, "Subscription has expired - renew your subscription"

        return True, None


async def record_renewal(customer_id: str) -> None:
    """Record a successful license renewal."""
    async with get_session() as session:
        await session.execute(
            text("""
                UPDATE licenses
                SET last_renewal_at = now(),
                    renewal_count = renewal_count + 1,
                    updated_at = now()
                WHERE customer_id = :customer_id
            """),
            {"customer_id": customer_id},
        )
        await session.commit()


@router.post("/renew", response_model=RenewalResponse)
async def renew_license(authorization: str = Header(...)) -> RenewalResponse:
    """Renew a license key. Called by self-hosted containers."""
    private_key_pem = os.environ.get("LICENSE_PRIVATE_KEY")
    if not private_key_pem:
        raise HTTPException(status_code=503, detail="Renewal not configured")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization")

    old_key = authorization[7:]

    try:
        license_info = validate_license_key(old_key)
    except LicenseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    customer = license_info.customer

    eligible, reason = await check_license_status(customer)
    if not eligible:
        logger.warning("license_renewal_denied", customer=customer, reason=reason)
        raise HTTPException(status_code=403, detail=reason)

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

    await record_renewal(customer)
    logger.info("license_renewed", customer=customer)

    return RenewalResponse(key=f"{KEY_PREFIX}{new_token}")

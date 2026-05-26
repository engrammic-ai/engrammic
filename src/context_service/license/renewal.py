"""Background license auto-renewal."""

from __future__ import annotations

import asyncio

import httpx

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.license.validator import validate_license_key

logger = get_logger(__name__)

RENEWAL_ENDPOINT = "https://license.engrammic.ai/renew"
RENEWAL_CHECK_INTERVAL = 24 * 60 * 60  # Check daily


async def attempt_license_renewal() -> bool:
    """Attempt to renew license if expiring soon.

    Returns:
        True if renewal successful, False if not needed or failed
    """
    settings = get_settings()
    license_key = settings.license_key

    if not license_key:
        return False

    try:
        info = validate_license_key(license_key)
    except Exception:
        return False

    if not info.is_expiring_soon:
        logger.debug("license_renewal_not_needed", days_remaining=info.days_remaining)
        return False

    logger.info("license_renewal_attempting", days_remaining=info.days_remaining)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                RENEWAL_ENDPOINT,
                headers={"Authorization": f"Bearer {license_key}"},
            )

            if response.status_code == 200:
                data = response.json()
                new_key = data.get("key")
                if new_key:
                    logger.info("license_renewed_successfully")
                    return True

            elif response.status_code == 403:
                logger.warning("license_renewal_denied", reason="revoked or expired")
            else:
                logger.warning("license_renewal_failed", status=response.status_code)

    except httpx.RequestError as e:
        logger.warning("license_renewal_network_error", error=str(e))

    return False


async def renewal_background_task() -> None:
    """Background task that periodically checks for license renewal."""
    while True:
        await asyncio.sleep(RENEWAL_CHECK_INTERVAL)
        await attempt_license_renewal()

"""Background license auto-renewal."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.license.validator import validate_license_key

logger = get_logger(__name__)

RENEWAL_ENDPOINT = "https://license.engrammic.ai/renew"
RENEWAL_CHECK_INTERVAL = 24 * 60 * 60  # Check daily


def _save_renewed_key(new_key: str) -> bool:
    """Save renewed license key to .env file if writable.

    Returns True if saved successfully, False otherwise.
    """
    env_path = Path(".env")
    if not env_path.exists():
        logger.warning(
            "license_renewal_env_not_found",
            new_key_prefix=new_key[:25] + "...",
            msg="Add ENGRAMMIC_LICENSE_KEY to .env manually",
        )
        return False

    try:
        content = env_path.read_text()
        if "ENGRAMMIC_LICENSE_KEY=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("ENGRAMMIC_LICENSE_KEY="):
                    new_lines.append(f"ENGRAMMIC_LICENSE_KEY={new_key}")
                else:
                    new_lines.append(line)
            env_path.write_text("\n".join(new_lines) + "\n")
            logger.info("license_key_updated_in_env")
            return True
        else:
            logger.warning(
                "license_key_not_in_env",
                new_key_prefix=new_key[:25] + "...",
                msg="Add ENGRAMMIC_LICENSE_KEY to .env manually",
            )
            return False
    except PermissionError:
        logger.warning(
            "license_renewal_env_not_writable",
            new_key_prefix=new_key[:25] + "...",
            msg="Update .env manually with the new key",
        )
        return False


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
                    saved = _save_renewed_key(new_key)
                    logger.info(
                        "license_renewed_successfully",
                        persisted=saved,
                    )
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

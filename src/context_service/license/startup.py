"""License check at application startup."""

from __future__ import annotations

import sys

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)

logger = get_logger(__name__)


def check_license_on_startup() -> LicenseInfo | None:
    """Validate license key at startup.

    Returns:
        LicenseInfo if valid license, None if validation disabled

    Exits:
        sys.exit(1) if validation enabled and license invalid/missing
    """
    settings = get_settings()

    if not settings.license_validation_enabled:
        logger.info("license_validation_disabled")
        return None

    license_key = settings.license_key
    if not license_key:
        logger.error("license_key_missing", msg="ENGRAMMIC_LICENSE_KEY not set")
        print("\nError: License key required for self-hosted deployment.")
        print("Set ENGRAMMIC_LICENSE_KEY in your .env file.\n")
        sys.exit(1)

    try:
        info = validate_license_key(license_key)
    except LicenseError as e:
        logger.error("license_validation_failed", error=str(e))
        print(f"\nError: Invalid license key - {e}")
        print("Contact support@engrammic.ai for assistance.\n")
        sys.exit(1)

    logger.info(
        "license_validated",
        customer=info.customer,
        days_remaining=info.days_remaining,
        tier=info.tier,
    )

    if info.is_expiring_soon:
        logger.warning(
            "license_expiring_soon",
            days_remaining=info.days_remaining,
            customer=info.customer,
        )

    # Log SAGE mode based on LLM configuration
    if not settings.llm.api_key:
        logger.info(
            "sage_passive_mode",
            msg="SAGE running in passive mode (no LLM API key). Storage and recall available, synthesis disabled.",
        )

    return info

"""License validation module."""

from context_service.license.renewal import attempt_license_renewal, renewal_background_task
from context_service.license.startup import check_license_on_startup
from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)

__all__ = [
    "LicenseError",
    "LicenseInfo",
    "attempt_license_renewal",
    "check_license_on_startup",
    "renewal_background_task",
    "validate_license_key",
]

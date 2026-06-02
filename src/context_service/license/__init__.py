"""License validation module."""

from context_service.license.renewal import attempt_license_renewal, renewal_background_task
from context_service.license.startup import check_license_on_startup, is_selfhosted
from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)
from context_service.license.version_check import VersionCheckResult, check_version

__all__ = [
    "LicenseError",
    "LicenseInfo",
    "VersionCheckResult",
    "attempt_license_renewal",
    "check_license_on_startup",
    "check_version",
    "is_selfhosted",
    "renewal_background_task",
    "validate_license_key",
]

"""License validation module."""

from context_service.license.startup import check_license_on_startup
from context_service.license.validator import (
    LicenseError,
    LicenseInfo,
    validate_license_key,
)

__all__ = ["LicenseError", "LicenseInfo", "check_license_on_startup", "validate_license_key"]

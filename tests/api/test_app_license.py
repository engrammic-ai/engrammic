"""License validation at startup tests."""

import os
from unittest.mock import patch

import pytest


def test_startup_without_license_key_exits() -> None:
    """App exits if LICENSE_VALIDATION_ENABLED and no license key."""
    with patch.dict(
        os.environ,
        {
            "LICENSE_VALIDATION_ENABLED": "true",
        },
        clear=False,
    ):
        # Clear the license key
        os.environ.pop("ENGRAMMIC_LICENSE_KEY", None)

        # Reset settings cache
        import context_service.config.settings as settings_mod

        settings_mod._settings_cache = None

        with pytest.raises(SystemExit):
            from context_service.license.startup import check_license_on_startup

            check_license_on_startup()


def test_startup_license_validation_disabled() -> None:
    """App starts without license when validation disabled."""
    with patch.dict(
        os.environ,
        {
            "LICENSE_VALIDATION_ENABLED": "false",
        },
        clear=False,
    ):
        # Reset settings cache
        import context_service.config.settings as settings_mod

        settings_mod._settings_cache = None

        from context_service.license.startup import check_license_on_startup

        result = check_license_on_startup()
        assert result is None

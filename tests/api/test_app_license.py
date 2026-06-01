"""License validation at startup tests."""

import os
from unittest.mock import patch

import pytest


def test_selfhosted_without_license_key_exits() -> None:
    """Self-hosted deployment exits if no license key provided."""
    with patch.dict(
        os.environ,
        {
            "ENGRAMMIC_DEPLOYMENT_TYPE": "selfhosted",
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


def test_managed_deployment_skips_license_check() -> None:
    """Managed deployment skips license validation (uses WorkOS auth)."""
    with patch.dict(
        os.environ,
        {},
        clear=False,
    ):
        # Clear deployment type (managed is the default)
        os.environ.pop("ENGRAMMIC_DEPLOYMENT_TYPE", None)
        os.environ.pop("ENGRAMMIC_LICENSE_KEY", None)

        # Reset settings cache
        import context_service.config.settings as settings_mod

        settings_mod._settings_cache = None

        from context_service.license.startup import check_license_on_startup

        result = check_license_on_startup()
        assert result is None


def test_is_selfhosted_detection() -> None:
    """is_selfhosted correctly detects deployment type."""
    from context_service.license.startup import is_selfhosted

    with patch.dict(os.environ, {"ENGRAMMIC_DEPLOYMENT_TYPE": "selfhosted"}):
        assert is_selfhosted() is True

    with patch.dict(os.environ, {"ENGRAMMIC_DEPLOYMENT_TYPE": "managed"}):
        assert is_selfhosted() is False

    with patch.dict(os.environ, {}, clear=True):
        assert is_selfhosted() is False

def test_license_settings_defaults() -> None:
    """License settings have correct defaults."""
    import os
    from importlib import reload

    # Clear relevant env vars
    os.environ.pop("ENGRAMMIC_LICENSE_KEY", None)
    os.environ.pop("LICENSE_VALIDATION_ENABLED", None)

    # Reload to get fresh settings
    import context_service.config.settings as settings_module

    reload(settings_module)

    settings = settings_module.Settings()

    assert settings.license_key is None
    assert settings.license_validation_enabled is True

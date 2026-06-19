def test_license_settings_defaults(monkeypatch) -> None:
    """License settings have correct defaults."""
    # Clear relevant env vars using monkeypatch (safe for test isolation)
    monkeypatch.delenv("ENGRAMMIC_LICENSE_KEY", raising=False)

    from context_service.config.settings import Settings

    settings = Settings()

    assert settings.license_key is None

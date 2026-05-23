from context_service.config.settings import TelemetryConfig


def test_telemetry_config_defaults():
    cfg = TelemetryConfig()
    assert cfg.enabled is True
    assert cfg.silos == []
    assert cfg.beacon_url == "https://tel.engrammic.ai/v1/beacon"
    assert cfg.beacon_interval_hours == 1


def test_telemetry_config_beacon_secret() -> None:
    """Beacon secret can be configured via env."""
    import os

    os.environ["TELEMETRY__BEACON_SECRET"] = "test-secret-123"

    from context_service.config.settings import Settings

    settings = Settings()

    assert settings.telemetry.beacon_secret == "test-secret-123"

    del os.environ["TELEMETRY__BEACON_SECRET"]


def test_telemetry_config_default_interval_is_one_hour() -> None:
    """Default beacon interval is 1 hour."""
    config = TelemetryConfig()
    assert config.beacon_interval_hours == 1


def test_telemetry_silos_star_means_all():
    cfg = TelemetryConfig(silos=["*"])
    assert cfg.all_silos is True


def test_telemetry_silos_specific():
    cfg = TelemetryConfig(silos=["tenant-a", "tenant-b"])
    assert cfg.all_silos is False
    assert "tenant-a" in cfg.silos

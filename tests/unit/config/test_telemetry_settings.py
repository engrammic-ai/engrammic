from context_service.config.settings import TelemetryConfig


def test_telemetry_config_defaults():
    cfg = TelemetryConfig()
    assert cfg.enabled is True
    assert cfg.silos == []
    assert cfg.beacon_url == "https://tel.engrammic.com/v1/beacon"
    assert cfg.beacon_interval_hours == 24


def test_telemetry_silos_star_means_all():
    cfg = TelemetryConfig(silos=["*"])
    assert cfg.all_silos is True


def test_telemetry_silos_specific():
    cfg = TelemetryConfig(silos=["tenant-a", "tenant-b"])
    assert cfg.all_silos is False
    assert "tenant-a" in cfg.silos

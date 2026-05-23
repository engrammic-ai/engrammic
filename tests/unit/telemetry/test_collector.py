from prometheus_client import CollectorRegistry

from context_service.telemetry.collector import TelemetryCollector, TelemetryPayload


def test_collector_returns_payload():
    registry = CollectorRegistry()
    collector = TelemetryCollector(
        install_id="test-id",
        version="1.0.0",
        registry=registry,
    )
    payload = collector.collect()

    assert isinstance(payload, TelemetryPayload)
    assert payload.install_id == "test-id"
    assert payload.version == "1.0.0"
    assert payload.tier == 1
    assert payload.uptime_seconds >= 0


def test_collector_tier2_includes_silos():
    registry = CollectorRegistry()
    collector = TelemetryCollector(
        install_id="test-id",
        version="1.0.0",
        registry=registry,
        silos=["tenant-a"],
    )
    payload = collector.collect()

    assert payload.tier == 2
    assert "tenant-a" in payload.silo_metrics


def test_collector_all_silos_flag():
    registry = CollectorRegistry()
    collector = TelemetryCollector(
        install_id="test-id",
        version="1.0.0",
        registry=registry,
        all_silos=True,
    )
    payload = collector.collect()

    assert payload.tier == 2


def test_telemetry_payload_has_percentile_fields() -> None:
    """TelemetryPayload includes p50/p95 latency and tool_counts."""
    from context_service.telemetry.collector import TelemetryPayload

    payload = TelemetryPayload(
        install_id="test",
        version="0.1.0",
        tier=1,
        uptime_seconds=100.0,
        latency_p50_ms=50.0,
        latency_p95_ms=150.0,
        tool_counts={"remember": 10, "recall": 25},
    )

    assert payload.latency_p50_ms == 50.0
    assert payload.latency_p95_ms == 150.0
    assert payload.tool_counts == {"remember": 10, "recall": 25}

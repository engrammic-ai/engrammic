from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.telemetry.beacon import BeaconService
from context_service.telemetry.collector import TelemetryCollector, TelemetryPayload


@pytest.fixture
def mock_collector():
    collector = MagicMock(spec=TelemetryCollector)
    collector.collect.return_value = TelemetryPayload(
        install_id="test-id",
        version="1.0.0",
        tier=1,
        uptime_seconds=100.0,
    )
    return collector


@pytest.mark.asyncio
async def test_beacon_sends_heartbeat(mock_collector):
    with patch("context_service.telemetry.beacon.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value.status_code = 200
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        beacon = BeaconService(
            collector=mock_collector,
            beacon_url="https://test.example.com/beacon",
            interval_hours=24,
        )

        await beacon.send_heartbeat()

        mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_beacon_disabled_does_nothing():
    beacon = BeaconService(
        collector=None,
        beacon_url="https://test.example.com/beacon",
        interval_hours=24,
        enabled=False,
    )

    await beacon.send_heartbeat()
    # Should not raise, just no-op


@pytest.mark.asyncio
async def test_beacon_sends_secret_header() -> None:
    """BeaconService sends X-Beacon-Secret header with heartbeats."""
    from unittest.mock import MagicMock

    mock_collector = MagicMock(spec=TelemetryCollector)
    mock_collector.collect.return_value = TelemetryPayload(
        install_id="test",
        version="0.1.0",
        tier=1,
        uptime_seconds=100.0,
    )

    service = BeaconService(
        collector=mock_collector,
        beacon_url="https://test.example.com/beacon",
        beacon_secret="my-secret-123",
        interval_hours=1,
        enabled=True,
    )

    with patch("context_service.telemetry.beacon.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=AsyncMock(status_code=200))
        mock_client_cls.return_value = mock_client

        await service.send_heartbeat()

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs.get("headers", {}).get("X-Beacon-Secret") == "my-secret-123"


@pytest.mark.asyncio
async def test_beacon_logs_warning_on_4xx(mock_collector):
    with patch("context_service.telemetry.beacon.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value.status_code = 422
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        beacon = BeaconService(
            collector=mock_collector,
            beacon_url="https://test.example.com/beacon",
            interval_hours=24,
        )

        # Should not raise, just log warning
        await beacon.send_heartbeat()

        mock_client.post.assert_called_once()

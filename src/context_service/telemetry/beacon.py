from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from context_service.telemetry.collector import TelemetryCollector

logger = structlog.get_logger(__name__)


class BeaconService:
    def __init__(
        self,
        collector: TelemetryCollector | None,
        beacon_url: str,
        interval_hours: int,
        enabled: bool = True,
        beacon_secret: str = "",
    ) -> None:
        self._collector = collector
        self._beacon_url = beacon_url
        self._beacon_secret = beacon_secret
        self._interval_seconds = interval_hours * 3600
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._enabled or self._collector is None:
            logger.info("telemetry_beacon_disabled")
            return

        self._task = asyncio.create_task(self._run_loop())
        logger.info("telemetry_beacon_started", interval_hours=self._interval_seconds // 3600)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            await self.send_heartbeat()
            await asyncio.sleep(self._interval_seconds)

    async def send_heartbeat(self) -> None:
        if not self._enabled or self._collector is None:
            return

        try:
            payload = self._collector.collect()
            headers: dict[str, str] = {}
            if self._beacon_secret:
                headers["X-Beacon-Secret"] = self._beacon_secret
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._beacon_url,
                    json=asdict(payload),
                    headers=headers,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "telemetry_heartbeat_rejected",
                        status=resp.status_code,
                        tier=payload.tier,
                    )
                else:
                    logger.info(
                        "telemetry_heartbeat_sent",
                        status=resp.status_code,
                        tier=payload.tier,
                    )
        except Exception as e:
            logger.warning("telemetry_heartbeat_failed", error=str(e))

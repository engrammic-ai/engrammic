"""Dagster job for sending telemetry beacons from self-hosted instances."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg
import httpx
import structlog

from context_service.config.settings import get_settings
from context_service.telemetry.collector import TelemetryCollector

logger = structlog.get_logger(__name__)


@dg.op
def send_telemetry_beacon(context) -> dict[str, Any]:
    """Collect and send telemetry beacon to managed service."""
    from prometheus_client import REGISTRY

    settings = get_settings()
    telemetry_config = settings.telemetry

    if not telemetry_config.enabled:
        context.log.info("beacon_sender: telemetry disabled, skipping")
        return {"status": "disabled"}

    if not telemetry_config.beacon_secret:
        context.log.warning("beacon_sender: no beacon_secret configured, skipping")
        return {"status": "no_secret"}

    async def _run() -> dict[str, Any]:
        silos = telemetry_config.silos if telemetry_config.silos != ["*"] else []
        collector = TelemetryCollector(
            install_id=telemetry_config.install_id,
            version=settings.version,
            registry=REGISTRY,
            silos=silos,
            all_silos=telemetry_config.all_silos,
        )

        payload = collector.collect()
        beacon_data = {
            "event_type": "heartbeat",
            "install_id": payload.install_id,
            "version": payload.version,
            "tier": payload.tier,
            "uptime_seconds": payload.uptime_seconds,
            "total_silos": payload.total_silos,
            "total_nodes": payload.total_nodes,
            "total_store_ops": payload.total_store_ops,
            "total_recall_ops": payload.total_recall_ops,
            "error_rate": payload.error_rate,
            "latency_mean_ms": payload.latency_mean_ms,
            "tool_counts": payload.tool_counts,
        }

        if payload.tier == 2:
            beacon_data["silo_metrics"] = {
                sid: {
                    "store_count": m.store_count,
                    "recall_count": m.recall_count,
                }
                for sid, m in payload.silo_metrics.items()
            }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                telemetry_config.beacon_url,
                json=beacon_data,
                headers={"X-Beacon-Secret": telemetry_config.beacon_secret},
            )
            resp.raise_for_status()

        context.log.info(
            "beacon_sent",
            install_id=telemetry_config.install_id,
            tier=payload.tier,
            tool_counts=payload.tool_counts,
        )
        return {"status": "sent", "tier": payload.tier}

    return asyncio.run(_run())


@dg.job(name="beacon_sender", tags={"schedule_type": "telemetry"})
def beacon_sender_job() -> None:
    """Send telemetry beacon to managed service (self-hosted only)."""
    send_telemetry_beacon()

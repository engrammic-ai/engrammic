"""Beacon telemetry receiver service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from beacon_service.config import BeaconConfig


class VersionInfo(BaseModel):
    """Version information for self-hosted instances."""

    latest: str
    minimum_supported: str
    deprecation_threshold: str


log = structlog.get_logger()

SECRET_TO_SILO: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database connection pool lifecycle."""
    config = BeaconConfig.from_env()
    app.state.pool = await asyncpg.create_pool(config.database_url)

    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch("SELECT secret, silo_id FROM beacon_secrets")
        for row in rows:
            SECRET_TO_SILO[row["secret"]] = str(row["silo_id"])

    log.info("beacon_started", secrets_loaded=len(SECRET_TO_SILO))
    yield
    await app.state.pool.close()


app = FastAPI(title="Engrammic Beacon", lifespan=lifespan)


@app.post("/v1/beacon")
async def receive_beacon(
    request: Request,
    x_beacon_secret: str = Header(..., alias="X-Beacon-Secret"),
) -> dict[str, str]:
    """Receive and store telemetry beacon from self-hosted instances."""
    silo_id = SECRET_TO_SILO.get(x_beacon_secret)
    if not silo_id:
        raise HTTPException(status_code=401, detail="Invalid beacon secret")

    payload: dict[str, Any] = await request.json()
    event_type = payload.get("event_type", "unknown")

    async with request.app.state.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO beacon_events (silo_id, event_type, payload)
            VALUES ($1, $2, $3)
            """,
            silo_id,
            event_type,
            payload,
        )

    log.info("beacon_received", silo_id=silo_id, event_type=event_type)
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/versions")
async def get_versions() -> VersionInfo:
    """Return version thresholds for self-hosted instances."""
    config = BeaconConfig.from_env()
    return VersionInfo(
        latest=config.version_latest,
        minimum_supported=config.version_minimum,
        deprecation_threshold=config.version_deprecated,
    )

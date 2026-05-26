"""Health check endpoints."""

import time
from collections.abc import Awaitable
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from context_service import __version__
from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.db.postgres import get_session

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class ServiceStatus(BaseModel):
    """Status of individual services."""

    memgraph: Literal["connected", "disconnected"]
    redis: Literal["connected", "disconnected"]
    qdrant: Literal["connected", "disconnected"]
    postgres: Literal["connected", "disconnected"]


class ServiceLatency(BaseModel):
    """Latency of individual service health checks in milliseconds."""

    memgraph_ms: float
    redis_ms: float
    qdrant_ms: float
    postgres_ms: float


class LicenseStatus(BaseModel):
    """License status in health response."""

    valid: bool
    customer: str | None = None
    expires_at: str | None = None
    days_remaining: int | None = None


class MemoryUsage(BaseModel):
    """Memory usage for a service (placeholder for future Docker socket integration)."""

    used_mb: int | None = None
    limit_mb: int | None = None
    percent: int | None = None


class HealthResponse(BaseModel):
    """Health check response model."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    services: ServiceStatus
    latency: ServiceLatency | None = None
    uptime_seconds: float | None = None
    license: LicenseStatus | None = None
    sage_mode: Literal["active", "passive"] = "passive"
    memory: dict[str, MemoryUsage] | None = None
    recent_restarts: list[str] = Field(default_factory=list)


async def _timed_check(coro: Awaitable[bool]) -> tuple[bool, float]:
    """Run a health check and return (result, latency_ms)."""
    start = time.monotonic()
    result = await coro
    elapsed_ms = (time.monotonic() - start) * 1000
    return result, elapsed_ms


async def _postgres_health_check() -> bool:
    """Check postgres connection by running a simple query."""
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("postgres_health_check_failed", error=str(e))
        return False


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="health_check",
    summary="Health check",
)
async def health_check(
    request: Request,
    detail: bool = Query(default=False, description="Include latency and uptime"),
) -> HealthResponse:
    """Check service health status."""
    required_services = ["memgraph", "redis", "qdrant"]
    if not all(hasattr(request.app.state, s) for s in required_services):
        return HealthResponse(
            status="unhealthy",
            version=__version__,
            services=ServiceStatus(
                memgraph="disconnected",
                redis="disconnected",
                qdrant="disconnected",
                postgres="disconnected",
            ),
        )

    if detail:
        memgraph_healthy, memgraph_ms = await _timed_check(
            request.app.state.memgraph.health_check()
        )
        redis_healthy, redis_ms = await _timed_check(request.app.state.redis.health_check())
        qdrant_healthy, qdrant_ms = await _timed_check(request.app.state.qdrant.health_check())
        postgres_healthy, postgres_ms = await _timed_check(_postgres_health_check())
    else:
        memgraph_healthy = await request.app.state.memgraph.health_check()
        redis_healthy = await request.app.state.redis.health_check()
        qdrant_healthy = await request.app.state.qdrant.health_check()
        postgres_healthy = await _postgres_health_check()
        memgraph_ms = redis_ms = qdrant_ms = postgres_ms = 0.0

    healthy_count = sum([memgraph_healthy, redis_healthy, qdrant_healthy, postgres_healthy])

    if healthy_count == 4:
        status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    elif healthy_count > 0:
        status = "degraded"
    else:
        status = "unhealthy"

    # License info from app state
    license_info = getattr(request.app.state, "license_info", None)
    license_status = None
    if license_info:
        import datetime as dt

        license_status = LicenseStatus(
            valid=True,
            customer=license_info.customer,
            expires_at=dt.datetime.fromtimestamp(license_info.expires_at, tz=dt.UTC).isoformat(),
            days_remaining=license_info.days_remaining,
        )

    # SAGE mode based on LLM config
    settings = get_settings()
    sage_mode: Literal["active", "passive"] = "active" if settings.llm.api_key else "passive"

    response = HealthResponse(
        status=status,
        version=__version__,
        services=ServiceStatus(
            memgraph="connected" if memgraph_healthy else "disconnected",
            redis="connected" if redis_healthy else "disconnected",
            qdrant="connected" if qdrant_healthy else "disconnected",
            postgres="connected" if postgres_healthy else "disconnected",
        ),
        license=license_status,
        sage_mode=sage_mode,
    )

    if detail:
        response.latency = ServiceLatency(
            memgraph_ms=round(memgraph_ms, 2),
            redis_ms=round(redis_ms, 2),
            qdrant_ms=round(qdrant_ms, 2),
            postgres_ms=round(postgres_ms, 2),
        )
        start_time = getattr(request.app.state, "start_time", None)
        if start_time is not None:
            response.uptime_seconds = round(time.monotonic() - start_time, 2)

    return response


@router.get(
    "/health/stores",
    response_model=HealthResponse,
    operation_id="health_check_stores",
    summary="Health check with store details",
)
async def health_check_stores(request: Request) -> HealthResponse:
    """Check service health with store latency details."""
    return await health_check(request, detail=True)


@router.get(
    "/ready",
    operation_id="readiness_check",
    summary="Kubernetes readiness probe",
)
async def readiness_check(request: Request) -> dict[str, str]:
    """Kubernetes readiness probe."""
    required_services = ["memgraph", "redis", "qdrant"]
    if not all(hasattr(request.app.state, s) for s in required_services):
        return {"status": "not_ready"}

    memgraph_ok = await request.app.state.memgraph.health_check()
    redis_ok = await request.app.state.redis.health_check()
    qdrant_ok = await request.app.state.qdrant.health_check()
    postgres_ok = await _postgres_health_check()

    if all([memgraph_ok, redis_ok, qdrant_ok, postgres_ok]):
        return {"status": "ready"}
    return {"status": "not_ready"}

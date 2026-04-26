"""Health check endpoints."""

import time
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from context_service import __version__
from context_service.config.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class ServiceStatus(BaseModel):
    """Status of individual services."""

    memgraph: Literal["connected", "disconnected"]
    redis: Literal["connected", "disconnected"]
    qdrant: Literal["connected", "disconnected"]


class ServiceLatency(BaseModel):
    """Latency of individual service health checks in milliseconds."""

    memgraph_ms: float
    redis_ms: float
    qdrant_ms: float


class HealthResponse(BaseModel):
    """Health check response model."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    services: ServiceStatus
    latency: ServiceLatency | None = None
    uptime_seconds: float | None = None


async def _timed_check(coro) -> tuple[bool, float]:
    """Run a health check and return (result, latency_ms)."""
    start = time.monotonic()
    result = await coro
    elapsed_ms = (time.monotonic() - start) * 1000
    return result, elapsed_ms


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
            ),
        )

    if detail:
        memgraph_healthy, memgraph_ms = await _timed_check(
            request.app.state.memgraph.health_check()
        )
        redis_healthy, redis_ms = await _timed_check(
            request.app.state.redis.health_check()
        )
        qdrant_healthy, qdrant_ms = await _timed_check(
            request.app.state.qdrant.health_check()
        )
    else:
        memgraph_healthy = await request.app.state.memgraph.health_check()
        redis_healthy = await request.app.state.redis.health_check()
        qdrant_healthy = await request.app.state.qdrant.health_check()
        memgraph_ms = redis_ms = qdrant_ms = 0.0

    healthy_count = sum([memgraph_healthy, redis_healthy, qdrant_healthy])

    if healthy_count == 3:
        status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    elif healthy_count > 0:
        status = "degraded"
    else:
        status = "unhealthy"

    response = HealthResponse(
        status=status,
        version=__version__,
        services=ServiceStatus(
            memgraph="connected" if memgraph_healthy else "disconnected",
            redis="connected" if redis_healthy else "disconnected",
            qdrant="connected" if qdrant_healthy else "disconnected",
        ),
    )

    if detail:
        response.latency = ServiceLatency(
            memgraph_ms=round(memgraph_ms, 2),
            redis_ms=round(redis_ms, 2),
            qdrant_ms=round(qdrant_ms, 2),
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

    if all([memgraph_ok, redis_ok, qdrant_ok]):
        return {"status": "ready"}
    return {"status": "not_ready"}

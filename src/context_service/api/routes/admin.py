"""Admin API routes — manual ops triggers for privileged operators.

These endpoints are not part of the public agent surface and must not be
exposed in production without authentication.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from context_service.api.deps import get_redis
from context_service.api.rate_limit import RateLimiter
from context_service.config.settings import get_settings
from context_service.stores import RedisClient

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)


def _require_admin_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> None:
    """Validate the Authorization: Bearer <key> header against ADMIN_API_KEY."""
    settings = get_settings()
    configured_key = settings.security.admin_api_key
    if configured_key is None:
        if settings.is_production:
            raise HTTPException(status_code=503, detail="admin_api_key required in production")
        return
    if credentials is None or credentials.credentials != configured_key.get_secret_value():
        raise HTTPException(status_code=401, detail="Invalid or missing admin API key")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TombstoneRequest(BaseModel):
    """Filter criteria for a manual tombstone run.

    Either supply explicit ``edge_ids`` OR one of the filter fields.  The
    ``silo_id`` is always required for silo-boundary enforcement.
    """

    silo_id: str = Field(..., description="Silo scope — tombstoning is never cross-silo.")
    edge_ids: list[str] = Field(
        default_factory=list,
        description="Explicit edge IDs to tombstone. If provided, filter fields are ignored.",
    )
    edge_type: (
        Literal[
            "CAUSES",
            "CORROBORATES",
            "PREVENTS",
            "CONTRADICTS",
            "REFERENCES",
            "RELATED_TO",
            "DERIVES_FROM",
            "DEPENDS_ON",
            "COMPOSES",
            "SPECIALIZES",
            "INSTANTIATES",
        ]
        | None
    ) = Field(
        default=None,
        description="Filter by edge type.",
    )
    confidence_below: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Tombstone edges with confidence strictly below this threshold.",
    )
    created_before: datetime | None = Field(
        default=None,
        description="Tombstone edges created before this ISO-8601 timestamp.",
    )
    max_invalidation_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max cascade hops for derived-edge invalidation.",
    )


class TombstoneResponse(BaseModel):
    silo_id: str
    direct_tombstoned: int
    derived_tombstoned: int


class SeedProposalRequest(BaseModel):
    """Request to seed a ProposedBelief for testing.

    WARNING: This endpoint is for testing only. Do not use in production.
    """

    silo_id: str = Field(..., description="Target silo ID")
    content: str = Field(..., description="Proposal content")
    confidence: float = Field(default=0.6, ge=0.0, le=1.0, description="Confidence score")
    source_fact_ids: list[str] = Field(default_factory=list, description="Source fact node IDs")
    status: Literal["pending", "accepted", "rejected"] = Field(default="pending")


class SeedProposalResponse(BaseModel):
    proposal_id: str
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _require_test_endpoints_enabled() -> None:
    """Guard for test-only endpoints. Raises 404 if disabled."""
    settings = get_settings()
    if not settings.features.enable_test_endpoints:
        raise HTTPException(status_code=404, detail="Not found")


@router.post(
    "/tombstone",
    response_model=TombstoneResponse,
    operation_id="admin_tombstone",
    summary="Tombstone inferred CAUSES edges for a silo",
    dependencies=[Depends(_require_admin_key)],
)
async def admin_tombstone(body: TombstoneRequest, request: Request) -> TombstoneResponse:
    """Tombstone edges matching the supplied criteria within the given silo.

    Uses the same transitive invalidation logic as the causal_tombstone Dagster
    asset.  Silo boundaries are strictly enforced — no cross-silo writes.
    """
    from context_service.engine.tombstone import run_tombstone as _run_tombstone

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    client: Any = request.app.state.memgraph

    logger.info(
        "admin_tombstone_start",
        silo_id=body.silo_id,
        edge_ids_count=len(body.edge_ids),
        edge_type=body.edge_type,
        confidence_below=body.confidence_below,
    )

    counts = await _run_tombstone(
        client,
        body.silo_id,
        edge_ids=body.edge_ids if body.edge_ids else None,
        edge_type=body.edge_type,
        confidence_below=body.confidence_below,
        created_before=body.created_before,
        max_invalidation_depth=body.max_invalidation_depth,
    )

    logger.info(
        "admin_tombstone_done",
        silo_id=body.silo_id,
        direct=counts["direct"],
        derived=counts["derived"],
    )

    return TombstoneResponse(
        silo_id=body.silo_id,
        direct_tombstoned=counts["direct"],
        derived_tombstoned=counts["derived"],
    )


# ---------------------------------------------------------------------------
# Tier management endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/silos/{silo_id}/tier",
    operation_id="admin_get_silo_tier",
    summary="Get the current rate limit tier for a silo",
    dependencies=[Depends(_require_admin_key)],
)
async def get_silo_tier(
    silo_id: str,
    redis: RedisClient = Depends(get_redis),  # noqa: B008
) -> dict[str, Any]:
    """Get the current rate limit tier for a silo."""
    settings = get_settings()
    cache_key = f"{RateLimiter.TIER_CACHE_PREFIX}{silo_id}"

    cached = await redis._redis.get(cache_key)
    tier = cached.decode() if cached else settings.security.rate_limit.default_tier

    return {
        "silo_id": silo_id,
        "tier": tier,
        "is_cached": cached is not None,
    }


@router.patch(
    "/silos/{silo_id}/tier",
    operation_id="admin_set_silo_tier",
    summary="Set the rate limit tier for a silo",
    dependencies=[Depends(_require_admin_key)],
)
async def set_silo_tier(
    silo_id: str,
    tier: str,
    redis: RedisClient = Depends(get_redis),  # noqa: B008
) -> dict[str, Any]:
    """Set the rate limit tier for a silo.

    Updates Redis cache for fast lookup.
    """
    settings = get_settings()
    valid_tiers = set(settings.security.rate_limit.tiers.keys())

    if tier not in valid_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{tier}'. Valid tiers: {sorted(valid_tiers)}",
        )

    cache_key = f"{RateLimiter.TIER_CACHE_PREFIX}{silo_id}"
    ttl = settings.security.rate_limit.tier_cache_ttl_seconds
    await redis._redis.set(cache_key, tier.encode(), ex=ttl)

    return {
        "silo_id": silo_id,
        "tier": tier,
        "cache_ttl_seconds": ttl,
    }


# ---------------------------------------------------------------------------
# Test-only endpoints (disabled by default)
# ---------------------------------------------------------------------------


@router.post(
    "/test/seed-proposal",
    response_model=SeedProposalResponse,
    operation_id="admin_seed_proposal",
    summary="Seed a ProposedBelief for testing",
    dependencies=[Depends(_require_admin_key), Depends(_require_test_endpoints_enabled)],
)
async def admin_seed_proposal(body: SeedProposalRequest, request: Request) -> SeedProposalResponse:
    """Seed a ProposedBelief node for testing purposes.

    WARNING: This endpoint is strictly for testing. Do not use in production.
    It bypasses the normal Custodian synthesis pipeline and directly creates
    proposal nodes in the wisdom layer.

    Enable with FEATURES__ENABLE_TEST_ENDPOINTS=true in environment.
    """
    import uuid
    from datetime import datetime

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    client: Any = request.app.state.memgraph

    proposal_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Create ProposedBelief node in Memgraph
    query = """
    CREATE (p:Document:ProposedBelief {
        node_id: $node_id,
        silo_id: $silo_id,
        layer: 'wisdom',
        node_type: 'ProposedBelief',
        content: $content,
        confidence: $confidence,
        status: $status,
        source_fact_ids: $source_fact_ids,
        created_at: $created_at
    })
    RETURN p.node_id AS node_id
    """

    logger.warning(
        "admin_seed_proposal",
        silo_id=body.silo_id,
        proposal_id=proposal_id,
        content_preview=body.content[:50] if len(body.content) > 50 else body.content,
    )

    await client.execute_query(
        query,
        {
            "node_id": proposal_id,
            "silo_id": body.silo_id,
            "content": body.content,
            "confidence": body.confidence,
            "status": body.status,
            "source_fact_ids": body.source_fact_ids,
            "created_at": now,
        },
    )

    return SeedProposalResponse(proposal_id=proposal_id, status="created")

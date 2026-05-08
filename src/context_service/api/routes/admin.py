"""Admin API routes — manual ops triggers for privileged operators.

These endpoints are not part of the public agent surface and must not be
exposed in production without authentication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from context_service.config.settings import get_settings

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
    edge_type: Literal[
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
    ] | None = Field(
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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

"""GDPR erasure REST endpoint.

Provides the right-to-erasure endpoint (Article 17 GDPR) for privileged
operators. Requires the admin API key — same guard as other admin routes.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.api.routes.admin import _require_admin_key
from context_service.db.postgres import get_engine
from context_service.engine.qdrant_store import EngineQdrantStore
from context_service.retention.erasure_service import ErasureService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/gdpr", tags=["gdpr"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ErasureRequest(BaseModel):
    node_ids: list[str]
    silo_id: str
    requester_type: str  # 'user', 'admin', 'system'
    requester_id: str | None = None
    cascade: bool = False


class ErasureResponse(BaseModel):
    request_id: str
    status: str  # 'completed', 'partial', 'failed'
    erased_count: int
    failed_count: int
    cascade_count: int
    erased_ids: list[str]
    failed_ids: list[str]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/erase",
    response_model=ErasureResponse,
    operation_id="gdpr_erase",
    summary="GDPR right-to-erasure",
    dependencies=[Depends(_require_admin_key)],
)
async def erase_nodes(
    request_body: ErasureRequest,
    request: Request,
) -> ErasureResponse:
    """GDPR right-to-erasure endpoint.

    Permanently hard-deletes the specified nodes (and optionally any nodes that
    reference them) from all three stores: Memgraph, Qdrant, and Postgres.  An
    audit log entry is written to the ``erasure_audit_log`` table regardless of
    whether all deletions succeed.

    Requires the admin API key (``Authorization: Bearer <key>``).
    """
    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    if not request_body.node_ids:
        raise HTTPException(status_code=400, detail="node_ids must not be empty")

    store = request.app.state.memgraph

    qdrant_client = getattr(request.app.state, "qdrant", None)
    qdrant_store = EngineQdrantStore(qdrant_client) if qdrant_client is not None else None

    async with AsyncSession(get_engine(), expire_on_commit=False) as db_session:
        service = ErasureService(
            store=store,
            qdrant_store=qdrant_store,
            db_session=db_session,
        )

        logger.info(
            "gdpr_erase_request",
            silo_id=request_body.silo_id,
            node_count=len(request_body.node_ids),
            requester_type=request_body.requester_type,
            cascade=request_body.cascade,
        )

        result = await service.erase(
            node_ids=request_body.node_ids,
            silo_id=request_body.silo_id,
            requester_type=request_body.requester_type,
            requester_id=request_body.requester_id,
            cascade=request_body.cascade,
        )

    return ErasureResponse(**result)

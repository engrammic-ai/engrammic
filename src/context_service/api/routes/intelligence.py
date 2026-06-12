"""REST wrapper endpoints for intelligence layer operations.

Exposes reason and reflect over HTTP for benchmark harnesses and headless
integrations that cannot use the MCP transport.

Headers:
- X-Silo-ID: required for both endpoints
- X-Session-ID: required for both endpoints
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from context_service.api.routes._auth import get_silo_context
from context_service.mcp.server import get_context_service, get_postgres_store
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import store_memory
from context_service.services.models import derive_silo_id

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["intelligence"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ReasoningStepModel(BaseModel):
    step: int
    reasoning: str
    confidence: float | None = None


class ReasonRequest(BaseModel):
    steps: list[ReasoningStepModel]
    conclusion: str | None = None
    evidence_used: list[str] = Field(default_factory=list)
    parent_chain_id: str | None = None


class ReasonResponse(BaseModel):
    chain_id: str
    layer: str
    steps_count: int
    crystallized_claim_ids: list[str]
    session_id: str
    created_at: str
    continues_chain_id: str | None = None


class ReflectRequest(BaseModel):
    observation: str
    observation_type: str
    about: list[str]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ReflectResponse(BaseModel):
    node_id: str
    observation_type: str
    about_nodes: list[str]
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/reason",
    response_model=ReasonResponse,
    operation_id="intelligence_reason",
    summary="Record a reasoning chain to the intelligence layer",
)
async def reason(
    request_body: ReasonRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> ReasonResponse:
    """Record explicit reasoning steps to the intelligence layer.

    Creates a reasoning chain with the supplied steps. Each step must have a
    ``step`` index, a ``reasoning`` string, and an optional ``confidence``
    score. The ``conclusion`` field is embedded and used for applicability
    matching at recall time.
    """
    silo_id, session_id = await get_silo_context(x_silo_id, x_session_id, require_session=True)

    if not request_body.steps:
        raise HTTPException(status_code=400, detail="steps must be a non-empty list")

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    from context_service.db import queries as q
    from context_service.engine.chain_saga import ChainSagaWriter
    from context_service.engine.sessions import attach_chain_to_session, create_or_join_session
    from context_service.models.inference import ChainStep
    from context_service.services.models import derive_org_uuid

    try:
        ctx_svc = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    store = ctx_svc.graph_store
    silo_uuid = derive_silo_id(x_silo_id or silo_id)
    agent_id = session_id or x_silo_id or silo_id
    resolved_session_id = session_id or str(uuid.uuid4())

    # Validate parent_chain_id exists before creating chain.
    if request_body.parent_chain_id is not None:
        try:
            parent_rows = await store.execute_query(
                q.GET_REASONING_CHAIN_IN_SILO,
                {"chain_id": request_body.parent_chain_id, "silo_id": silo_id},
            )
        except Exception:
            parent_rows = []
        if not parent_rows:
            raise HTTPException(
                status_code=400,
                detail=f"parent_chain_id {request_body.parent_chain_id!r} not found in silo",
            )

    chain_steps = [
        ChainStep(
            step_index=s.step,
            operation=s.reasoning[:80] if len(s.reasoning) > 80 else s.reasoning,
            conclusion=s.reasoning,
            confidence=s.confidence if s.confidence is not None else 0.8,
        )
        for s in request_body.steps
    ]

    chain_id = uuid.uuid4()
    produced_by_agent_id = agent_id

    try:
        postgres_store = get_postgres_store()
        saga = ChainSagaWriter(postgres_store, store)

        _start = time.perf_counter()
        await create_or_join_session(store, resolved_session_id, silo_id)
        await saga.write_chain(
            chain_id=chain_id,
            silo_id=silo_uuid,
            steps=chain_steps,
            produced_by_model="unknown",
            produced_by_agent_id=produced_by_agent_id,
            status="draft",
            source="agent_explicit",
            conclusion=request_body.conclusion,
            evidence_used=request_body.evidence_used or None,
            org_id=derive_org_uuid(x_silo_id or silo_id),
        )
        elapsed = time.perf_counter() - _start
    except Exception as exc:
        logger.error(
            "rest_reason_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to store reasoning chain") from exc

    # Attach query embedding to chain for applicability matching (best-effort).
    if request_body.conclusion:
        try:
            from context_service.mcp.tools.context_store import _upsert_chain_embedding, embed

            query_embedding = await embed(request_body.conclusion)
            await _upsert_chain_embedding(
                chain_id,
                silo_id,
                query_embedding,
                evidence_used=request_body.evidence_used or None,
            )
        except Exception as exc:
            logger.warning(
                "rest_reason_chain_embedding_failed",
                chain_id=str(chain_id),
                error=str(exc),
            )

    try:
        await attach_chain_to_session(store, str(chain_id), resolved_session_id, silo_id)
    except Exception as exc:
        logger.warning(
            "rest_reason_session_attach_failed",
            chain_id=str(chain_id),
            error=str(exc),
        )

    continues_parent: str | None = None
    if request_body.parent_chain_id is not None:
        try:
            await store.execute_write(
                q.CREATE_CONTINUES_EDGE,
                {
                    "child_chain_id": str(chain_id),
                    "parent_chain_id": request_body.parent_chain_id,
                    "silo_id": silo_id,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            continues_parent = request_body.parent_chain_id
        except Exception as exc:
            logger.warning(
                "rest_reason_continues_edge_failed",
                chain_id=str(chain_id),
                error=str(exc),
            )

    logger.info(
        "rest_reason_ok",
        chain_id=str(chain_id),
        silo_id=silo_id,
        steps_count=len(request_body.steps),
        elapsed_ms=round(elapsed * 1000, 1),
    )

    response = ReasonResponse(
        chain_id=str(chain_id),
        layer="intelligence",
        steps_count=len(request_body.steps),
        crystallized_claim_ids=[],
        session_id=resolved_session_id,
        created_at=datetime.now(UTC).isoformat(),
        continues_chain_id=continues_parent,
    )
    return response


@router.post(
    "/reflect",
    response_model=ReflectResponse,
    operation_id="intelligence_reflect",
    summary="Record a meta-observation about existing knowledge",
)
async def reflect(
    request_body: ReflectRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> ReflectResponse:
    """Record a meta-observation about existing knowledge nodes.

    Stores an observation to the meta layer. The ``about`` field should
    contain node IDs that this observation concerns. Valid observation types
    include ``pattern``, ``contradiction``, ``uncertainty``, and ``drift``.
    """
    silo_id, session_id = await get_silo_context(x_silo_id, x_session_id, require_session=True)

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    try:
        ctx_svc = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    store = ctx_svc.graph_store
    agent_id = session_id or x_silo_id or silo_id

    try:
        _start = time.perf_counter()
        result, events = await store_memory(
            store=store,
            content=request_body.observation,
            silo_id=silo_id,
            agent_id=agent_id,
            layer="meta",
            metadata={"confidence": request_body.confidence},
        )
        elapsed = time.perf_counter() - _start
    except Exception as exc:
        logger.error(
            "rest_reflect_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to store meta-observation") from exc

    for event in events:
        try:
            await emit_reaction(event)
        except Exception as exc:
            logger.warning("rest_reflect_emit_failed", error=str(exc))

    logger.info(
        "rest_reflect_ok",
        node_id=str(result.node_id),
        silo_id=silo_id,
        elapsed_ms=round(elapsed * 1000, 1),
    )

    return ReflectResponse(
        node_id=str(result.node_id),
        observation_type=request_body.observation_type,
        about_nodes=request_body.about,
        created_at=result.created_at.isoformat(),
    )

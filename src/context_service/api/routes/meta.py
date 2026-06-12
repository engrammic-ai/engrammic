"""REST wrapper endpoints for meta/cross-cutting operations.

Exposes trace, history, patterns, forget, and tick over HTTP for benchmark
harnesses and headless integrations that cannot use the MCP transport.

Headers:
- X-Silo-ID: required for all endpoints; treated as org_id, silo UUID is derived
- X-Session-ID: required for forget and tick (write operations)
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from context_service.api.routes._auth import get_silo_context
from context_service.mcp.server import get_context_service, get_skill_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["meta"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TraceRequest(BaseModel):
    node_id: str
    max_depth: int = Field(default=10, ge=1, le=50)


class ProvenanceStepOut(BaseModel):
    node_id: str
    layer: str
    relationship: str
    confidence: float
    stub: bool = False


class TraceResponse(BaseModel):
    chain: list[ProvenanceStepOut]
    root_sources: list[dict[str, Any]]


class HistoryRequest(BaseModel):
    node_id: str | None = None
    subject: str | None = None


class HistoryEntryOut(BaseModel):
    node_id: str
    content: str
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: float
    supersession_reason: str | None = None


class HistoryResponse(BaseModel):
    timeline: list[HistoryEntryOut]
    current: dict[str, Any] | None = None


class PatternsRequest(BaseModel):
    action: Literal["list", "get", "search"] = "list"
    name: str | None = None
    query: str | None = None
    profile: str | None = None


class PatternsResponse(BaseModel):
    patterns: list[dict[str, Any]] = Field(default_factory=list)
    pattern: dict[str, Any] | None = None
    count: int | None = None
    error: str | None = None
    message: str | None = None


class ForgetRequest(BaseModel):
    node_id: str
    reason: str | None = None
    cascade: bool = False


class ForgetResponse(BaseModel):
    node_id: str
    state: str
    tombstoned_at: str
    cancel_window_expires: str
    cascade_count: int = 0


class TickRequest(BaseModel):
    about_hint: list[str] | None = None
    recent_context: str | None = None


class TickResponse(BaseModel):
    status: str
    session_id: str | None = None
    engagement: dict[str, Any] | None = None
    markers: list[dict[str, Any]] = Field(default_factory=list)
    nudges: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/trace",
    response_model=TraceResponse,
    operation_id="meta_trace",
    summary="Trace provenance chain for a node",
)
async def trace(
    request_body: TraceRequest,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> TraceResponse:
    """Trace the citation chain from a node back to Memory-layer sources.

    Does not require a session; read-only provenance traversal.
    """
    silo_id, _ = await get_silo_context(x_silo_id, require_session=False)

    try:
        ctx_svc = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    try:
        result = await ctx_svc.provenance(
            silo_id=silo_id,
            node_id=request_body.node_id,
            max_depth=request_body.max_depth,
        )
    except Exception as exc:
        logger.error(
            "rest_trace_failed",
            silo_id=silo_id,
            node_id=request_body.node_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to trace provenance") from exc

    logger.info(
        "rest_trace_ok",
        silo_id=silo_id,
        node_id=request_body.node_id,
        chain_len=len(result.chain),
    )

    return TraceResponse(
        chain=[
            ProvenanceStepOut(
                node_id=step.node_id,
                layer=step.layer,
                relationship=step.relationship,
                confidence=step.confidence,
                stub=step.stub,
            )
            for step in result.chain
        ],
        root_sources=result.root_sources,
    )


@router.post(
    "/history",
    response_model=HistoryResponse,
    operation_id="meta_history",
    summary="Get belief evolution history",
)
async def history(
    request_body: HistoryRequest,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> HistoryResponse:
    """Return the SUPERSEDES chain showing how a belief evolved over time.

    Pass either node_id (any node in the chain) or subject (topic string).
    Does not require a session; read-only history traversal.
    """
    if not request_body.node_id and not request_body.subject:
        raise HTTPException(
            status_code=400, detail="Either node_id or subject is required"
        )

    silo_id, _ = await get_silo_context(x_silo_id, require_session=False)

    try:
        ctx_svc = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    try:
        result = await ctx_svc.history(
            silo_id=silo_id,
            node_id=request_body.node_id,
            subject=request_body.subject,
        )
    except Exception as exc:
        logger.error(
            "rest_history_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve history") from exc

    def _fmt_ts(ts: Any) -> str | None:
        if ts is None:
            return None
        if hasattr(ts, "isoformat"):
            return str(ts.isoformat())
        return str(ts)

    logger.info(
        "rest_history_ok",
        silo_id=silo_id,
        timeline_len=len(result.timeline),
    )

    return HistoryResponse(
        timeline=[
            HistoryEntryOut(
                node_id=entry.node_id,
                content=entry.content,
                valid_from=_fmt_ts(entry.valid_from),
                valid_to=_fmt_ts(entry.valid_to),
                confidence=entry.confidence,
                supersession_reason=entry.supersession_reason,
            )
            for entry in result.timeline
        ],
        current=result.current,
    )


@router.post(
    "/patterns",
    response_model=PatternsResponse,
    operation_id="meta_patterns",
    summary="Discover workflow templates and skills",
)
async def patterns(
    request_body: PatternsRequest,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
) -> PatternsResponse:
    """List, get, or search agent workflow patterns (skills).

    Does not require a session; read-only skill registry access.
    """
    silo_id, _ = await get_silo_context(x_silo_id, require_session=False)

    try:
        skill_svc = get_skill_service()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503, detail="Patterns service not available"
        ) from exc

    try:
        if request_body.action == "list":
            skills = await skill_svc.list(
                silo_id,
                namespace=request_body.profile,
                limit=50,
                offset=0,
            )
            return PatternsResponse(
                patterns=[s.model_dump(exclude_none=True) for s in skills],
                count=len(skills),
            )

        elif request_body.action == "get":
            if not request_body.name:
                raise HTTPException(status_code=400, detail="name is required for get action")
            skill = await skill_svc.get(silo_id, request_body.name)
            if not skill:
                raise HTTPException(
                    status_code=404, detail=f"Pattern not found: {request_body.name}"
                )
            return PatternsResponse(pattern=skill.model_dump(exclude_none=True))

        else:  # search
            if not request_body.query:
                raise HTTPException(
                    status_code=400, detail="query is required for search action"
                )
            skills = await skill_svc.search(
                silo_id,
                request_body.query,
                namespace=request_body.profile,
                limit=50,
            )
            return PatternsResponse(
                patterns=[s.model_dump(exclude_none=True) for s in skills],
                count=len(skills),
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "rest_patterns_failed",
            silo_id=silo_id,
            action=request_body.action,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve patterns") from exc


@router.post(
    "/forget",
    response_model=ForgetResponse,
    operation_id="meta_forget",
    summary="Soft-delete a node with cancel window",
)
async def forget(
    request_body: ForgetRequest,
    request: Request,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> ForgetResponse:
    """Request soft-deletion of a node (TX15).

    Places the node in TOMBSTONED state with a cancel window. Requires both
    X-Silo-ID and X-Session-ID headers.
    """
    silo_id, session_id = await get_silo_context(
        x_silo_id, x_session_id, require_session=True
    )

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph

    from context_service.sage.transactions import InvariantViolation
    from context_service.sage.transactions import forget as brain_forget

    try:
        result_tx, _events = await brain_forget(
            store=store,
            node_id=request_body.node_id,
            silo_id=silo_id,
            agent_id=session_id or silo_id,
            reason=request_body.reason,
            cascade=request_body.cascade,
        )
    except InvariantViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "rest_forget_failed",
            silo_id=silo_id,
            node_id=request_body.node_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to forget node") from exc

    logger.info(
        "rest_forget_ok",
        node_id=str(result_tx.node_id),
        silo_id=silo_id,
    )

    return ForgetResponse(
        node_id=str(result_tx.node_id),
        state=str(result_tx.state.value) if hasattr(result_tx.state, "value") else str(result_tx.state),
        tombstoned_at=result_tx.tombstoned_at.isoformat(),
        cancel_window_expires=result_tx.cancel_window_expires.isoformat(),
        cascade_count=result_tx.cascade_count,
    )


@router.post(
    "/tick",
    response_model=TickResponse,
    operation_id="meta_tick",
    summary="Lightweight engagement check",
)
async def tick(
    request_body: TickRequest,
    x_silo_id: str | None = Header(default=None, alias="X-Silo-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> TickResponse:
    """Check for pending engagement markers without a full recall operation.

    Safe to call frequently; reads the precomputed marker index only and has
    near-zero side effects (session state update only). Requires both X-Silo-ID
    and X-Session-ID headers.
    """
    silo_id, session_id = await get_silo_context(
        x_silo_id, x_session_id, require_session=True
    )

    from context_service.mcp.tools.tick import _tick

    try:
        result = await _tick(
            about_hint=request_body.about_hint,
            silo_id=silo_id,
            session_id=session_id,
            recent_context=request_body.recent_context,
        )
    except Exception as exc:
        logger.error(
            "rest_tick_failed",
            silo_id=silo_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to execute tick") from exc

    if result.get("status") == "error":
        raise HTTPException(
            status_code=503,
            detail=result.get("message", "Tick service unavailable"),
        )

    logger.info(
        "rest_tick_ok",
        silo_id=silo_id,
        status=result.get("status"),
    )

    return TickResponse(
        status=result.get("status", "ok"),
        session_id=result.get("session_id"),
        engagement=result.get("engagement"),
        markers=result.get("markers", []),
        nudges=result.get("nudges", []),
        meta=result.get("meta", {}),
    )

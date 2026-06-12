"""REST wrapper endpoints for wisdom layer operations.

Exposes decide, accept, hypothesize, crystallize, dismiss, and revise over
HTTP for benchmark harnesses and headless integrations that cannot use the
MCP transport.

Headers:
- X-Session-ID: optional session identifier
- Authorization: Bearer token (required when AUTH_ENABLED=true)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from context_service.api.routes._auth import get_authenticated_silo
from context_service.mcp.tools.context_store import _context_store_belief
from context_service.mcp.tools.context_update_belief import _context_update_belief
from context_service.mcp.tools.dismiss import _dismiss_marker
from context_service.sage.transactions import accept_proposal, commit, crystallize

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["wisdom"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class DecideRequest(BaseModel):
    content: str
    about: list[str] = Field(description="Node IDs this decision is about")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class DecideResponse(BaseModel):
    commitment_id: str
    created_at: str
    confidence: float


class AcceptRequest(BaseModel):
    proposal_id: str
    reason: str | None = None
    override_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AcceptResponse(BaseModel):
    belief_id: str
    proposal_id: str
    accepted: bool
    accepted_at: str
    confidence: float


class HypothesizeRequest(BaseModel):
    content: str
    about: list[str] = Field(default_factory=list, description="Node IDs this hypothesis is about")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class HypothesizeResponse(BaseModel):
    belief_id: str
    session_id: str
    created_at: str
    potential_conflicts: list[str] = Field(default_factory=list)


class CrystallizeRequest(BaseModel):
    hypothesis_id: str


class CrystallizeResponse(BaseModel):
    commitment_id: str
    hypothesis_id: str
    created_at: str
    confidence: float


class DismissRequest(BaseModel):
    marker_id: str
    reason: str


class DismissResponse(BaseModel):
    marker_id: str | None = None
    proposal_id: str | None = None
    status: str
    reason: str | None = None


class ReviseRequest(BaseModel):
    belief_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    content: str | None = None


class ReviseResponse(BaseModel):
    belief_id: str
    confidence: float
    content: str | None = None
    updated_at: str
    reason: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/decide",
    response_model=DecideResponse,
    operation_id="wisdom_decide",
    summary="Declare a direct agent commitment",
)
async def decide(
    request_body: DecideRequest,
    request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> DecideResponse:
    """Declare a direct agent commitment to the wisdom layer.

    Creates a Commitment node with ABOUT edges to the referenced nodes.
    Equivalent to the MCP ``decide`` verb.
    """
    silo_id, session_id = auth_context

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph

    try:
        result_tx, _events = await commit(
            store=store,
            content=request_body.content,
            about_refs=request_body.about,
            silo_id=silo_id,
            agent_id=session_id or silo_id,
            confidence=request_body.confidence,
        )
    except Exception as exc:
        logger.error("rest_decide_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to store commitment: {exc}") from exc

    logger.info("rest_decide_ok", commitment_id=str(result_tx.commitment_id), silo_id=silo_id)

    return DecideResponse(
        commitment_id=str(result_tx.commitment_id),
        created_at=result_tx.created_at.isoformat(),
        confidence=result_tx.confidence,
    )


@router.post(
    "/accept",
    response_model=AcceptResponse,
    operation_id="wisdom_accept",
    summary="Promote a ProposedBelief to a full Belief",
)
async def accept(
    request_body: AcceptRequest,
    request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> AcceptResponse:
    """Accept a SAGE-synthesized ProposedBelief, promoting it to a full Belief.

    Equivalent to the MCP ``accept`` verb.
    """
    silo_id, session_id = auth_context

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph

    try:
        result_tx, _events = await accept_proposal(
            store=store,
            proposal_id=request_body.proposal_id,
            silo_id=silo_id,
            agent_id=session_id or silo_id,
            reason=request_body.reason,
            override_confidence=request_body.override_confidence,
        )
    except Exception as exc:
        logger.error("rest_accept_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to accept proposal: {exc}") from exc

    logger.info("rest_accept_ok", belief_id=str(result_tx.belief_id), silo_id=silo_id)

    return AcceptResponse(
        belief_id=str(result_tx.belief_id),
        proposal_id=str(result_tx.proposal_id),
        accepted=result_tx.accepted,
        accepted_at=result_tx.accepted_at.isoformat(),
        confidence=result_tx.confidence,
    )


@router.post(
    "/hypothesize",
    response_model=HypothesizeResponse,
    operation_id="wisdom_hypothesize",
    summary="Create a session-scoped working hypothesis",
)
async def hypothesize(
    request_body: HypothesizeRequest,
    request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> HypothesizeResponse:
    """Create a WorkingHypothesis scoped to the current session.

    Finalize with ``/crystallize`` to promote to a permanent Commitment.
    Equivalent to the MCP ``hypothesize`` verb.
    """
    silo_id, session_id = auth_context

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    try:
        result = await _context_store_belief(
            silo_id=silo_id,
            content=request_body.content,
            session_id=session_id or silo_id,
            about=request_body.about,
            confidence=request_body.confidence,
        )
    except Exception as exc:
        logger.error("rest_hypothesize_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to store hypothesis: {exc}") from exc

    if "error" in result:
        raise HTTPException(status_code=400, detail=result.get("message", result["error"]))

    logger.info("rest_hypothesize_ok", belief_id=result.get("belief_id"), silo_id=silo_id)

    return HypothesizeResponse(
        belief_id=result["belief_id"],
        session_id=result["session_id"],
        created_at=result["created_at"],
        potential_conflicts=result.get("potential_conflicts", []),
    )


@router.post(
    "/crystallize",
    response_model=CrystallizeResponse,
    operation_id="wisdom_crystallize",
    summary="Crystallize a working hypothesis into a permanent commitment",
)
async def crystallize_endpoint(
    request_body: CrystallizeRequest,
    request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> CrystallizeResponse:
    """Promote a WorkingHypothesis to a Commitment.

    Named ``/crystallize`` rather than ``/commit`` to avoid collision with the
    brain transaction function ``commit()`` imported from sage/transactions.py,
    which creates Commitments directly (the ``decide`` flow) rather than
    promoting hypotheses.

    Equivalent to the MCP ``commit`` verb.
    """
    silo_id, session_id = auth_context

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    store = request.app.state.memgraph

    try:
        result_tx, _events = await crystallize(
            store=store,
            hypothesis_id=request_body.hypothesis_id,
            silo_id=silo_id,
            agent_id=session_id or silo_id,
            session_id=session_id,
        )
    except Exception as exc:
        logger.error("rest_crystallize_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(
            status_code=500, detail=f"Failed to crystallize hypothesis: {exc}"
        ) from exc

    logger.info(
        "rest_crystallize_ok",
        commitment_id=str(result_tx.commitment_id),
        hypothesis_id=str(result_tx.hypothesis_id),
        silo_id=silo_id,
    )

    return CrystallizeResponse(
        commitment_id=str(result_tx.commitment_id),
        hypothesis_id=str(result_tx.hypothesis_id),
        created_at=result_tx.created_at.isoformat(),
        confidence=result_tx.confidence,
    )


@router.post(
    "/dismiss",
    response_model=DismissResponse,
    operation_id="wisdom_dismiss",
    summary="Dismiss a marker or reject a ProposedBelief",
)
async def dismiss(
    request_body: DismissRequest,
    request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> DismissResponse:
    """Dismiss a Contradiction/StaleCommitment marker or reject a ProposedBelief.

    Equivalent to the MCP ``dismiss`` verb.
    """
    silo_id, _session_id = auth_context

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    try:
        result = await _dismiss_marker(
            marker_id=request_body.marker_id,
            reason=request_body.reason,
            silo_id=silo_id,
        )
    except Exception as exc:
        logger.error("rest_dismiss_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to dismiss marker: {exc}") from exc

    if "error" in result:
        raise HTTPException(status_code=400, detail=result.get("message", result["error"]))

    logger.info("rest_dismiss_ok", marker_id=request_body.marker_id, silo_id=silo_id)

    return DismissResponse(
        marker_id=result.get("marker_id"),
        proposal_id=result.get("proposal_id"),
        status=result.get("status", "dismissed"),
        reason=result.get("reason"),
    )


@router.post(
    "/revise",
    response_model=ReviseResponse,
    operation_id="wisdom_revise",
    summary="Update a working hypothesis in-place",
)
async def revise(
    request_body: ReviseRequest,
    request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> ReviseResponse:
    """Mutate an existing WorkingHypothesis (confidence and/or content).

    Equivalent to the MCP ``revise`` verb.
    """
    silo_id, _session_id = auth_context

    if not hasattr(request.app.state, "memgraph"):
        raise HTTPException(status_code=503, detail="Memgraph not available")

    try:
        result = await _context_update_belief(
            belief_id=request_body.belief_id,
            confidence=request_body.confidence,
            reason=request_body.reason,
            silo_id=silo_id,
            content=request_body.content,
        )
    except Exception as exc:
        logger.error("rest_revise_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to revise hypothesis: {exc}") from exc

    if "error" in result:
        raise HTTPException(status_code=400, detail=result.get("message", result["error"]))

    logger.info("rest_revise_ok", belief_id=request_body.belief_id, silo_id=silo_id)

    return ReviseResponse(
        belief_id=result["belief_id"],
        confidence=result["confidence"],
        content=result.get("content"),
        updated_at=result["updated_at"],
        reason=result["reason"],
    )

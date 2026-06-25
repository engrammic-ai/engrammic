"""REST wrapper endpoints for MCP tools.

Exposes update, agents, conflicts, dismiss_conflict, escalate_conflict,
resolve_conflict over HTTP for testing and headless integrations.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from context_service.api.routes._auth import get_authenticated_silo

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tools"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class UpdateRequest(BaseModel):
    content: str
    evidence: list[str]
    query: str | None = None
    target: str | None = None
    source_tier: str | None = None
    confidence: float = 0.8


class AgentsRequest(BaseModel):
    pass


class ConflictsRequest(BaseModel):
    agent_id: str | None = None
    status: str = "unresolved"
    limit: int = 50


class DismissConflictRequest(BaseModel):
    conflict_id: str
    reason: str | None = None


class EscalateConflictRequest(BaseModel):
    conflict_id: str
    message: str | None = None


class ResolveConflictRequest(BaseModel):
    conflict_id: str
    winner_id: str
    supersede: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/update", operation_id="tools_update", summary="Update existing knowledge")
async def update(
    request_body: UpdateRequest,
    _request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> dict[str, Any]:
    """Update existing knowledge by superseding it with new content."""
    silo_id, session_id = auth_context
    if not session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header is required")

    from context_service.mcp.tools.update import _update_impl

    try:
        result = await _update_impl(
            content=request_body.content,
            evidence=request_body.evidence,
            query=request_body.query,
            target=request_body.target,
            source_tier=request_body.source_tier,
            confidence=request_body.confidence,
            silo_id=silo_id,
            _agent_id=session_id,
        )
        logger.info("rest_update_ok", silo_id=silo_id, status=result.get("status"))
        return result
    except Exception as exc:
        logger.error("rest_update_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}") from exc


@router.post("/agents", operation_id="tools_agents", summary="List agents in silo")
async def agents(
    _request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> dict[str, Any]:
    """List agents registered in the silo."""
    silo_id, _ = auth_context

    from context_service.mcp.tools.agents import _agents

    try:
        agent_list = await _agents(silo_id)
        return {"agents": agent_list, "count": len(agent_list)}
    except Exception as exc:
        logger.error("rest_agents_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Agents query failed: {exc}") from exc


@router.post("/conflicts", operation_id="tools_conflicts", summary="List conflicts")
async def conflicts(
    request_body: ConflictsRequest,
    _request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> dict[str, Any]:
    """List contradictions between nodes."""
    silo_id, _ = auth_context

    from context_service.mcp.tools.conflicts import _get_conflicts

    try:
        conflict_list = await _get_conflicts(
            silo_id=silo_id,
            agent_id=request_body.agent_id,
            status=request_body.status,
            limit=request_body.limit,
        )
        return {"conflicts": conflict_list, "count": len(conflict_list)}
    except Exception as exc:
        logger.error("rest_conflicts_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Conflicts query failed: {exc}") from exc


@router.post(
    "/dismiss_conflict",
    operation_id="tools_dismiss_conflict",
    summary="Dismiss a conflict",
)
async def dismiss_conflict(
    request_body: DismissConflictRequest,
    _request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> dict[str, Any]:
    """Mark a conflict as not-a-real-conflict."""
    silo_id, session_id = auth_context

    from context_service.mcp.tools.conflicts import _update_conflict_status

    try:
        ok = await _update_conflict_status(
            conflict_id=request_body.conflict_id,
            silo_id=silo_id,
            resolution_status="dismissed",
            resolved_by=session_id or "rest-api",
        )
        if not ok:
            return {"error": "not_found", "conflict_id": request_body.conflict_id}
        return {
            "conflict_id": request_body.conflict_id,
            "status": "dismissed",
            "reason": request_body.reason,
        }
    except Exception as exc:
        logger.error("rest_dismiss_conflict_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Dismiss failed: {exc}") from exc


@router.post(
    "/escalate_conflict",
    operation_id="tools_escalate_conflict",
    summary="Escalate a conflict for human review",
)
async def escalate_conflict(
    request_body: EscalateConflictRequest,
    _request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> dict[str, Any]:
    """Flag a conflict for human review."""
    silo_id, session_id = auth_context

    from context_service.mcp.tools.conflicts import _update_conflict_status

    try:
        ok = await _update_conflict_status(
            conflict_id=request_body.conflict_id,
            silo_id=silo_id,
            resolution_status="escalated",
            resolved_by=session_id or "rest-api",
        )
        if not ok:
            return {"error": "not_found", "conflict_id": request_body.conflict_id}
        return {
            "conflict_id": request_body.conflict_id,
            "status": "escalated",
            "message": request_body.message,
        }
    except Exception as exc:
        logger.error("rest_escalate_conflict_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Escalate failed: {exc}") from exc


@router.post(
    "/resolve_conflict",
    operation_id="tools_resolve_conflict",
    summary="Resolve a conflict by picking a winner",
)
async def resolve_conflict(
    request_body: ResolveConflictRequest,
    _request: Request,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> dict[str, Any]:
    """Pick a winner for a conflict."""
    silo_id, session_id = auth_context

    from context_service.mcp.tools.conflicts import _update_conflict_status

    try:
        resolution_status = "superseded" if request_body.supersede else "resolved"
        ok = await _update_conflict_status(
            conflict_id=request_body.conflict_id,
            silo_id=silo_id,
            resolution_status=resolution_status,
            resolved_by=session_id or "rest-api",
        )
        if not ok:
            return {"error": "not_found", "conflict_id": request_body.conflict_id}
        return {
            "conflict_id": request_body.conflict_id,
            "status": resolution_status,
            "winner_id": request_body.winner_id,
        }
    except Exception as exc:
        logger.error("rest_resolve_conflict_failed", silo_id=silo_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Resolve failed: {exc}") from exc

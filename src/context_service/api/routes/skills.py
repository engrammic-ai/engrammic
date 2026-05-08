"""REST API routes for skill registry."""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from context_service.schemas.skill import SkillCreate, SkillResponse, SkillUpdate

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])

_bearer = HTTPBearer(auto_error=True)


# Placeholder auth - integrate with real auth system
async def _get_silo_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],  # noqa: ARG001
) -> str:
    """Extract silo_id from auth token."""
    # TODO: Integrate with actual auth system
    return "default-silo"


async def _require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],  # noqa: ARG001
) -> None:
    """Validate user has admin role."""
    # TODO: Integrate with actual auth system
    pass


# Service getter - will be wired up in integration task
_skill_service = None


def set_skill_service(service: Any) -> None:
    global _skill_service
    _skill_service = service


def _get_skill_service() -> Any:
    if _skill_service is None:
        raise RuntimeError("SkillService not configured")
    return _skill_service


# Request model for import
class ImportRequest(BaseModel):
    source_url: str
    name: str
    token: str | None = None


# Routes - ORDER MATTERS: /search and /import before /{name}


@router.get("/search")
async def search_skills(
    q: str = Query(..., min_length=1),
    namespace: str | None = None,
    limit: int = Query(default=50, le=200),
    silo_id: str = Depends(_get_silo_id),
) -> dict[str, Any]:
    """Search skills by name/description."""
    service = _get_skill_service()
    skills = await service.search(silo_id, q, namespace=namespace, limit=limit)
    return {"skills": [s.model_dump(exclude_none=True) for s in skills], "count": len(skills)}


@router.post("/import", dependencies=[Depends(_require_admin)])
async def import_skill(
    request: ImportRequest,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Import a skill from a remote Engrammic instance."""
    service = _get_skill_service()
    try:
        result: SkillResponse = await service.import_from(silo_id, request.source_url, request.name, request.token)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("")
async def list_skills(
    namespace: str | None = None,
    source: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    silo_id: str = Depends(_get_silo_id),
) -> dict[str, Any]:
    """List all skills."""
    service = _get_skill_service()
    skills = await service.list(silo_id, namespace=namespace, limit=limit, offset=offset)
    if source:
        skills = [s for s in skills if s.source == source]
    return {"skills": [s.model_dump(exclude_none=True) for s in skills], "count": len(skills)}


@router.get("/{name:path}")
async def get_skill(
    name: str,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Get a specific skill by name."""
    service = _get_skill_service()
    skill: SkillResponse | None = await service.get(silo_id, name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return skill


@router.post("", dependencies=[Depends(_require_admin)])
async def create_skill(
    skill: SkillCreate,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Create a new user skill."""
    service = _get_skill_service()
    try:
        created: SkillResponse = await service.create(silo_id, skill)
        return created
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/{name:path}", dependencies=[Depends(_require_admin)])
async def update_skill(
    name: str,
    skill: SkillUpdate,
    silo_id: str = Depends(_get_silo_id),
) -> SkillResponse:
    """Update a user skill."""
    service = _get_skill_service()
    try:
        updated: SkillResponse = await service.update(silo_id, name, skill)
        return updated
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{name:path}", dependencies=[Depends(_require_admin)])
async def delete_skill(
    name: str,
    silo_id: str = Depends(_get_silo_id),
) -> dict[str, str]:
    """Delete a user skill."""
    service = _get_skill_service()
    try:
        await service.delete(silo_id, name)
        return {"status": "deleted", "name": name}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

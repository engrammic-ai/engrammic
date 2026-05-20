"""API key management endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from context_service.api.deps import get_current_user
from context_service.db.postgres import get_session
from context_service.models.postgres.user import User
from context_service.services.api_key import APIKeyService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name: str


class CreateKeyResponse(BaseModel):
    key: str  # Plaintext, shown once
    id: UUID
    name: str


class KeyInfo(BaseModel):
    id: UUID
    name: str
    created_at: str
    last_used_at: str | None


@router.post("", response_model=CreateKeyResponse, status_code=201)
async def create_api_key(
    request: CreateKeyRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> CreateKeyResponse:
    """Create a new API key. The key is shown once - save it securely."""
    async with get_session() as session:
        svc = APIKeyService(session)
        plaintext, api_key = await svc.create_key(
            user_id=current_user.id,
            name=request.name,
        )
        await session.commit()

    logger.info("api_keys.created", user_id=str(current_user.id), key_id=str(api_key.id))
    return CreateKeyResponse(
        key=plaintext,
        id=api_key.id,
        name=api_key.name,
    )


@router.get("", response_model=list[KeyInfo])
async def list_api_keys(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[KeyInfo]:
    """List your API keys (without the secret)."""
    async with get_session() as session:
        svc = APIKeyService(session)
        keys = await svc.list_keys(current_user.id)

    return [
        KeyInfo(
            id=k.id,
            name=k.name,
            created_at=k.created_at.isoformat(),
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        )
        for k in keys
    ]


@router.delete("/{key_id}", status_code=200)
async def revoke_api_key(
    key_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Revoke an API key."""
    async with get_session() as session:
        svc = APIKeyService(session)
        # Verify ownership before revoking
        keys = await svc.list_keys(current_user.id)
        if not any(k.id == key_id for k in keys):
            raise HTTPException(status_code=404, detail="Key not found")

        await svc.revoke_key(key_id)
        await session.commit()

    logger.info("api_keys.revoked", user_id=str(current_user.id), key_id=str(key_id))
    return {"status": "revoked"}

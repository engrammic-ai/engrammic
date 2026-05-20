"""Dependency injection for API routes."""

from typing import Annotated  # noqa: TC003 - used at runtime for FastAPI Depends

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from context_service.db.postgres import get_session
from context_service.engine.protocols import HyperGraphStore
from context_service.models.postgres.user import User
from context_service.services.oauth import OAuthService
from context_service.stores import QdrantClient, RedisClient

_bearer_security = HTTPBearer()


def get_memgraph(request: Request) -> HyperGraphStore:
    """Get graph store from app state, vended as the HyperGraphStore protocol."""
    store: HyperGraphStore = request.app.state.memgraph
    return store


def get_qdrant(request: Request) -> QdrantClient:
    """Get Qdrant client from app state."""
    client: QdrantClient = request.app.state.qdrant
    return client


def get_redis(request: Request) -> RedisClient:
    """Get Redis client from app state."""
    client: RedisClient = request.app.state.redis
    return client


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_security)],
) -> User:
    """Resolve current user from Bearer token (OAuth access token)."""
    token = credentials.credentials

    async with get_session() as session:
        oauth_svc = OAuthService(session)
        oauth_token = await oauth_svc.validate_access_token(token)

        if oauth_token is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user = await session.get(User, oauth_token.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")

        return user


MemgraphDep = Annotated[HyperGraphStore, Depends(get_memgraph)]
QdrantDep = Annotated[QdrantClient, Depends(get_qdrant)]
RedisDep = Annotated[RedisClient, Depends(get_redis)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]

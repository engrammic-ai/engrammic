"""Dependency injection for API routes."""

from typing import Annotated

from fastapi import Depends, Request

from context_service.engine.protocols import HyperGraphStore
from context_service.stores import QdrantClient, RedisClient


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


MemgraphDep = Annotated[HyperGraphStore, Depends(get_memgraph)]
QdrantDep = Annotated[QdrantClient, Depends(get_qdrant)]
RedisDep = Annotated[RedisClient, Depends(get_redis)]

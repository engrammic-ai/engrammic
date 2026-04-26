"""Dependency injection for API routes."""

from typing import Annotated

from fastapi import Depends, Request

from context_service.stores import MemgraphClient, QdrantClient, RedisClient


def get_memgraph(request: Request) -> MemgraphClient:
    """Get Memgraph client from app state."""
    client: MemgraphClient = request.app.state.memgraph
    return client


def get_qdrant(request: Request) -> QdrantClient:
    """Get Qdrant client from app state."""
    client: QdrantClient = request.app.state.qdrant
    return client


def get_redis(request: Request) -> RedisClient:
    """Get Redis client from app state."""
    client: RedisClient = request.app.state.redis
    return client


MemgraphDep = Annotated[MemgraphClient, Depends(get_memgraph)]
QdrantDep = Annotated[QdrantClient, Depends(get_qdrant)]
RedisDep = Annotated[RedisClient, Depends(get_redis)]

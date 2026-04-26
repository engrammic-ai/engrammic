"""Dependency injection for API routes."""

from typing import Annotated

from fastapi import Depends, Request

from context_service.stores import MemgraphClient, QdrantClient, RedisClient


def get_memgraph(request: Request) -> MemgraphClient:
    """Get Memgraph client from app state."""
    return request.app.state.memgraph


def get_qdrant(request: Request) -> QdrantClient:
    """Get Qdrant client from app state."""
    return request.app.state.qdrant


def get_redis(request: Request) -> RedisClient:
    """Get Redis client from app state."""
    return request.app.state.redis


MemgraphDep = Annotated[MemgraphClient, Depends(get_memgraph)]
QdrantDep = Annotated[QdrantClient, Depends(get_qdrant)]
RedisDep = Annotated[RedisClient, Depends(get_redis)]

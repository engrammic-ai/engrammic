"""Data store clients.

Ported from contextr: app/db/memgraph.py, app/db/qdrant.py, app/db/redis.py
"""

from context_service.stores.memgraph import (
    MemgraphClient,
    MemgraphOperationError,
    create_memgraph_driver,
)
from context_service.stores.qdrant import (
    QdrantClient,
    QdrantOperationError,
    SearchResult,
)
from context_service.stores.redis import (
    RedisClient,
    RedisOperationError,
    create_redis_pool,
)

__all__ = [
    # Memgraph
    "MemgraphClient",
    "MemgraphOperationError",
    "create_memgraph_driver",
    # Qdrant
    "QdrantClient",
    "QdrantOperationError",
    "SearchResult",
    # Redis
    "RedisClient",
    "RedisOperationError",
    "create_redis_pool",
]

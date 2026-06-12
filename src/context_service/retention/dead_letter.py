"""Dead-letter queue for failed Qdrant deletes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis

from context_service.stores.redis import create_redis_pool

logger = structlog.get_logger(__name__)

DEAD_LETTER_KEY = "dead_letter:qdrant_delete"

_redis_pool: Redis | None = None
_init_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


async def _get_redis() -> Redis:
    """Return a cached Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        async with _get_init_lock():
            if _redis_pool is None:
                _redis_pool = await create_redis_pool()
    return _redis_pool


async def enqueue_failed_delete(silo_id: str, node_id: str, error: str) -> None:
    """Add failed delete to dead-letter queue for reconciliation."""
    redis = await _get_redis()
    entry = {
        "silo_id": silo_id,
        "node_id": node_id,
        "error": error,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await redis.lpush(DEAD_LETTER_KEY, json.dumps(entry))
    logger.warning("enqueued_dead_letter", silo_id=silo_id, node_id=node_id)


async def dequeue_failed_deletes(batch_size: int = 100) -> list[dict[str, str]]:
    """Pop entries from dead-letter queue for retry."""
    redis = await _get_redis()
    entries: list[dict[str, str]] = []
    for _ in range(batch_size):
        raw = await redis.rpop(DEAD_LETTER_KEY)
        if raw is None:
            break
        entries.append(json.loads(raw))
    return entries

"""Dead-letter queue for failed Qdrant deletes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog

from context_service.stores.redis import create_redis_pool

logger = structlog.get_logger(__name__)

DEAD_LETTER_KEY = "dead_letter:qdrant_delete"


async def enqueue_failed_delete(silo_id: str, node_id: str, error: str) -> None:
    """Add failed delete to dead-letter queue for reconciliation."""
    redis = await create_redis_pool()
    entry = {
        "silo_id": silo_id,
        "node_id": node_id,
        "error": error,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await redis.lpush(DEAD_LETTER_KEY, json.dumps(entry))  # type: ignore[misc]
    logger.warning("enqueued_dead_letter", silo_id=silo_id, node_id=node_id)


async def dequeue_failed_deletes(batch_size: int = 100) -> list[dict]:  # type: ignore[type-arg]
    """Pop entries from dead-letter queue for retry."""
    redis = await create_redis_pool()
    entries = []
    for _ in range(batch_size):
        raw = await redis.rpop(DEAD_LETTER_KEY)  # type: ignore[misc]
        if raw is None:
            break
        entries.append(json.loads(raw))
    return entries

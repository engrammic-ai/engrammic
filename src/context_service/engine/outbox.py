"""Outbox writer for deferred Qdrant embedding operations.

Writes go to a Redis list (LPUSH). A Dagster sensor drains the queue by
yielding RunRequests that trigger outbox_embed_job.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

OUTBOX_KEY = "outbox:embed"
DLQ_KEY = "outbox:embed:dlq"
MAX_RETRIES = 3


class OutboxWriter:
    """Push embed entries onto a Redis list for async processing.

    Entry format:
        {
            "type": "embed",
            "node_id": str,
            "content": str,
            "metadata": dict,
        }
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def push(self, entry: dict[str, Any]) -> None:
        """Push an entry to the outbox list.

        Retries up to MAX_RETRIES times on transient Redis failure.

        Args:
            entry: Outbox entry dict with keys type, node_id, content, metadata.

        Raises:
            Exception: If all retry attempts fail.
        """
        from context_service.utils.json import dumps

        payload = dumps(entry).encode()
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await self._redis.lpush(OUTBOX_KEY, payload)  # type: ignore[misc]
                logger.debug(
                    "outbox_push_ok",
                    node_id=entry.get("node_id"),
                    attempt=attempt,
                )
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "outbox_push_failed",
                    node_id=entry.get("node_id"),
                    attempt=attempt,
                    max_retries=MAX_RETRIES,
                    error=str(exc),
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * attempt)

        logger.error(
            "outbox_push_exhausted",
            node_id=entry.get("node_id"),
            error=str(last_exc),
        )
        raise last_exc  # type: ignore[misc]


__all__ = ["DLQ_KEY", "MAX_RETRIES", "OUTBOX_KEY", "OutboxWriter"]

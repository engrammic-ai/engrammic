"""Poison queue for failed Dagster runs that have exhausted their retry budget."""

import contextlib
from typing import Any

from context_service.config.logging import get_logger
from context_service.utils.json import JSONDecodeError, dumps, loads

logger = get_logger(__name__)

_KEY_PREFIX = "dagster:poison"
_SCAN_BATCH = 100


class PoisonQueue:
    """Write and read failed-run snapshots in Redis.

    Keys have the form ``dagster:poison:{asset_key}:{run_id}``.
    All Redis errors are swallowed so callers (sensors) never fail because of
    a broken Redis connection — matches the fire-and-forget pattern in
    cache/node_cache.py.
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def _key(self, asset_key: str, run_id: str) -> str:
        return f"{_KEY_PREFIX}:{asset_key}:{run_id}"

    async def push(
        self,
        run_id: str,
        asset_key: str,
        error: str,
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> None:
        """Record a failed run in the poison queue with a TTL."""
        payload = dumps(
            {
                "run_id": run_id,
                "asset_key": asset_key,
                "error": error,
            }
        ).encode()
        try:
            await self._redis.set(self._key(asset_key, run_id), payload, ex=ttl_seconds)
        except Exception as exc:
            logger.debug("poison_queue_push_error", run_id=run_id, error=str(exc))

    async def peek(
        self,
        asset_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return up to *limit* failed-run snapshots, optionally filtered by asset_key."""
        pattern = f"{_KEY_PREFIX}:{asset_key}:*" if asset_key else f"{_KEY_PREFIX}:*"
        results: list[dict[str, Any]] = []
        try:
            cursor: int = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=_SCAN_BATCH)
                for key in keys:
                    raw: bytes | None = await self._redis.get(key)
                    if raw is not None:
                        with contextlib.suppress(JSONDecodeError, TypeError):
                            results.append(loads(raw))
                    if len(results) >= limit:
                        return results
                if cursor == 0:
                    break
        except Exception as exc:
            logger.debug("poison_queue_peek_error", error=str(exc))
        return results


__all__ = ["PoisonQueue"]

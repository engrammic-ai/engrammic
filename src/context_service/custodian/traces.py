"""Redis visit-trace writer and reader at custodian:visit:{pass_id}:{cluster_id}."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - runtime use by pydantic
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)

PREFIX = "custodian:visit"


class UsageBreakdown(BaseModel):
    """Per-phase LLM usage accounting recorded in a visit trace."""

    model: str
    input_tokens: int
    output_tokens: int
    duration_seconds: float


class VisitTrace(BaseModel):
    """Ephemeral record of everything that happened during a single cluster visit.

    ``fast_pass_observation``, ``plan``, and ``stitch_output`` are typed as
    ``dict | None`` instead of the concrete models from
    :mod:`context_service.custodian.models` to avoid a merge race during parallel
    Custodian foundation tasks.
    """

    pass_id: str
    cluster_id: str
    org_id: str
    silo_id: str
    fast_pass_observation: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    commit_log: list[dict[str, Any]] = Field(default_factory=list)
    usage_breakdown: dict[str, UsageBreakdown] = Field(default_factory=dict)
    stitch_output: dict[str, Any] | None = None
    created_at: datetime


class VisitTraceCache:
    """Redis-backed ephemeral visit trace store with configurable TTL.

    Key schema: ``custodian:visit:{pass_id}:{cluster_id}``.
    """

    def __init__(self, redis: RedisClient, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, pass_id: str, cluster_id: str) -> str:
        return f"{PREFIX}:{pass_id}:{cluster_id}"

    async def write(self, pass_id: str, cluster_id: str, trace: VisitTrace) -> None:
        """Serialize the trace to JSON and SET with the configured TTL."""
        key = self._key(pass_id, cluster_id)
        try:
            payload = trace.model_dump_json().encode("utf-8")
            await self._redis.set(key, payload, ttl_seconds=self._ttl)
        except Exception as e:
            logger.warning(f"VisitTraceCache write error for {key}: {e}")
            raise

    async def read(self, pass_id: str, cluster_id: str) -> VisitTrace | None:
        """GET and deserialize the trace; return ``None`` if missing or expired."""
        key = self._key(pass_id, cluster_id)
        try:
            data = await self._redis.get(key)
            if data is None:
                return None
            return VisitTrace.model_validate_json(data)
        except Exception as e:
            logger.warning(f"VisitTraceCache read error for {key}: {e}")
            return None

    async def delete(self, pass_id: str, cluster_id: str) -> None:
        """Manual eviction. Used by tests and rollback paths."""
        key = self._key(pass_id, cluster_id)
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.warning(f"VisitTraceCache delete error for {key}: {e}")

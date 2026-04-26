"""Redis-backed job store for extraction job tracking."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from context_service.config.logging import get_logger
from context_service.extraction.models import ExtractionJob

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)


class ExtractionJobStore:
    """Store and retrieve extraction job status in Redis.

    Key pattern: extraction:job:{silo_id}:{job_id}
    """

    KEY_PREFIX = "extraction:job:"
    JOB_TTL = 86400  # 24 hours

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    def _make_key(self, silo_id: str, job_id: str) -> str:
        """Create Redis key for a job."""
        return f"{self.KEY_PREFIX}{silo_id}:{job_id}"

    async def save(self, job: ExtractionJob) -> None:
        """Save or update an extraction job."""
        key = self._make_key(job.silo_id, job.id)
        data = json.dumps(job.to_dict())
        await self._redis.set(key, data, ttl_seconds=self.JOB_TTL)
        logger.debug(f"Saved extraction job: {job.id} (status={job.status.value})")

    async def get(self, silo_id: str, job_id: str) -> ExtractionJob | None:
        """Retrieve an extraction job by ID."""
        key = self._make_key(silo_id, job_id)
        data = await self._redis.get(key)
        if data is None:
            return None
        try:
            parsed = json.loads(data.decode())
            # Verify silo_id matches (defense in depth)
            if parsed.get("silo_id") != silo_id:
                logger.warning(f"Silo mismatch for job {job_id}")
                return None
            return ExtractionJob.from_dict(parsed)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse extraction job {job_id}: {e}")
            return None

    async def list_jobs(self, silo_id: str, limit: int = 50) -> list[ExtractionJob]:
        """List recent extraction jobs for a silo.

        Note: This performs a scan which is O(N). Acceptable for admin
        usage with small job counts. For production scale, consider a
        sorted set index.
        """
        jobs: list[ExtractionJob] = []
        pattern = f"{self.KEY_PREFIX}{silo_id}:*"
        try:
            cursor: int = 0
            while True:
                cursor, keys = await self._redis._redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    data = await self._redis._redis.get(key)
                    if data is not None:
                        try:
                            parsed = json.loads(data.decode())
                            # Verify silo_id matches
                            if parsed.get("silo_id") == silo_id:
                                jobs.append(ExtractionJob.from_dict(parsed))
                        except (json.JSONDecodeError, KeyError):
                            continue
                    if len(jobs) >= limit:
                        break
                if cursor == 0 or len(jobs) >= limit:
                    break
        except Exception as e:
            logger.error(f"Failed to list extraction jobs: {e}")

        # Sort by created_at descending
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

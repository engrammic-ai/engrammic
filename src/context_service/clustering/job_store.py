"""Redis-backed job store for clustering job tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.clustering.models import ClusteringJob
from context_service.config.logging import get_logger
from context_service.utils.json import JSONDecodeError, dumps, loads

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)


class ClusteringJobStore:
    """Store and retrieve clustering job status in Redis.

    Key pattern: clustering:job:{silo_id}:{job_id}
    """

    KEY_PREFIX = "clustering:job:"
    JOB_TTL = 86400  # 24 hours

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    def _make_key(self, silo_id: str, job_id: str) -> str:
        """Create Redis key for a job."""
        return f"{self.KEY_PREFIX}{silo_id}:{job_id}"

    async def save(self, job: ClusteringJob) -> None:
        """Save or update a clustering job."""
        key = self._make_key(job.silo_id, job.id)
        data = dumps(job.to_dict())
        await self._redis.set(key, data, ttl_seconds=self.JOB_TTL)
        logger.debug("saved clustering job", job_id=job.id, status=job.status.value)

    async def get(self, silo_id: str, job_id: str) -> ClusteringJob | None:
        """Retrieve a clustering job by ID.

        Args:
            silo_id: Silo identifier for isolation.
            job_id: Job identifier.

        Returns:
            ClusteringJob or None if not found.
        """
        key = self._make_key(silo_id, job_id)
        data = await self._redis.get(key)
        if data is None:
            return None
        try:
            parsed = loads(data.decode())
            if parsed.get("silo_id") != silo_id:
                logger.warning("silo mismatch for clustering job", job_id=job_id)
                return None
            return ClusteringJob.from_dict(parsed)
        except (JSONDecodeError, KeyError) as e:
            logger.error("failed to parse clustering job", job_id=job_id, error=str(e))
            return None

    async def list_jobs(self, silo_id: str, limit: int = 50) -> list[ClusteringJob]:
        """List recent clustering jobs for a silo.

        Args:
            silo_id: Silo identifier for isolation.
            limit: Maximum number of jobs to return.

        Note: This performs a scan which is O(N). Acceptable for admin
        usage with small job counts.
        """
        jobs: list[ClusteringJob] = []
        pattern = f"{self.KEY_PREFIX}{silo_id}:*"
        try:
            cursor: int = 0
            while True:
                cursor, keys = await self._redis._redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    data = await self._redis._redis.get(key)
                    if data is not None:
                        try:
                            parsed = loads(data.decode())
                            if parsed.get("silo_id") == silo_id:
                                jobs.append(ClusteringJob.from_dict(parsed))
                        except (JSONDecodeError, KeyError):
                            continue
                    if len(jobs) >= limit:
                        break
                if cursor == 0 or len(jobs) >= limit:
                    break
        except Exception as e:
            logger.error("failed to list clustering jobs", error=str(e))

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

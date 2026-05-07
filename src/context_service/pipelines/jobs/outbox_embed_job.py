"""Dagster job: drain the Redis outbox and upsert embeddings to Qdrant.

Processing loop:
1. RPOP entries from outbox:embed (right-pop = FIFO since writer uses LPUSH).
2. Embed content via the embedding service.
3. Upsert vector to Qdrant.
4. On success: entry is consumed (already popped).
5. On per-entry failure: increment retry_count in metadata and re-push to the
   tail of the queue; after MAX_RETRIES failures push to DLQ instead.

The job is a @dg.op-based job (not an asset job) so it can be triggered
directly by the outbox_embed_sensor with RunRequest rather than needing a
partitions_def.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg

from context_service.engine.outbox import DLQ_KEY, MAX_RETRIES, OUTBOX_KEY
from context_service.pipelines.resources import EmbeddingResource, QdrantResource, RedisResource

_DRAIN_BATCH = 50


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.op(
    name="outbox_embed_op",
    description=(
        "Drain the Redis outbox list, embed content, and upsert vectors to Qdrant. "
        "Failed entries are retried up to MAX_RETRIES times before moving to the DLQ."
    ),
    required_resource_keys={"redis", "qdrant", "embedding"},
)
def outbox_embed_op(context: dg.OpExecutionContext) -> dict[str, int]:
    """Process pending outbox entries."""
    redis_res: RedisResource = context.resources.redis
    qdrant_res: QdrantResource = context.resources.qdrant
    embed_res: EmbeddingResource = context.resources.embedding

    t0 = time.monotonic()

    async def _process() -> tuple[int, int, int]:
        from context_service.utils.json import JSONDecodeError, dumps, loads

        redis = await redis_res.client()
        embed_svc = embed_res.get_client()
        engine_qdrant = qdrant_res.qdrant_store()

        processed = 0
        failed = 0
        dlq_count = 0

        try:
            for _ in range(_DRAIN_BATCH):
                raw: bytes | None = await redis.rpop(OUTBOX_KEY)  # type: ignore[misc]
                if raw is None:
                    break

                try:
                    entry: dict[str, Any] = loads(raw.decode())
                except (JSONDecodeError, UnicodeDecodeError) as exc:
                    context.log.warning(f"outbox entry corrupt, discarding: {exc}")
                    failed += 1
                    continue

                node_id: str = entry.get("node_id", "")
                content: str = entry.get("content", "")
                metadata: dict[str, Any] = entry.get("metadata", {})
                silo_id: str = metadata.get("silo_id", "")
                retry_count: int = int(metadata.get("retry_count", 0))

                if not node_id or not content or not silo_id:
                    context.log.warning(
                        f"outbox entry missing required fields, discarding: {entry!r}"
                    )
                    failed += 1
                    continue

                try:
                    vectors = await embed_svc.embed([content])
                    vector = vectors[0]

                    node_type: str | None = metadata.get("node_type")
                    sparse_indices: list[int] | None = metadata.get("sparse_indices")
                    sparse_values: list[float] | None = metadata.get("sparse_values")
                    expansion: str | None = metadata.get("expansion")

                    await engine_qdrant.upsert(
                        node_id=node_id,  # type: ignore[arg-type]
                        vector=vector,
                        silo_id=silo_id,
                        node_type=node_type,
                        sparse_indices=sparse_indices,
                        sparse_values=sparse_values,
                        expansion=expansion,
                    )
                    processed += 1

                except Exception as exc:
                    context.log.warning(
                        f"outbox embed/upsert failed for node={node_id} "
                        f"retry={retry_count}: {exc}"
                    )
                    if retry_count >= MAX_RETRIES - 1:
                        # Move to DLQ
                        dlq_entry = dict(entry)
                        dlq_entry["metadata"] = dict(metadata)
                        dlq_entry["metadata"]["final_error"] = str(exc)
                        await redis.lpush(DLQ_KEY, dumps(dlq_entry).encode())  # type: ignore[misc]
                        dlq_count += 1
                        context.log.error(
                            f"outbox entry moved to DLQ after {retry_count + 1} attempts "
                            f"node={node_id}"
                        )
                    else:
                        # Re-queue with incremented retry count
                        retry_entry = dict(entry)
                        retry_entry["metadata"] = dict(metadata)
                        retry_entry["metadata"]["retry_count"] = retry_count + 1
                        await redis.rpush(OUTBOX_KEY, dumps(retry_entry).encode())  # type: ignore[misc]
                    failed += 1

        finally:
            await engine_qdrant.close()

        return processed, failed, dlq_count

    processed, failed, dlq_count = _run_async(_process())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"outbox_embed_op: processed={processed} failed={failed} dlq={dlq_count} "
        f"duration={duration_s:.2f}s"
    )

    return {"processed": processed, "failed": failed, "dlq_count": dlq_count}


@dg.job(
    name="outbox_embed_job",
    description="Process pending Qdrant embed outbox entries from Redis.",
    resource_defs={"redis": RedisResource, "qdrant": QdrantResource, "embedding": EmbeddingResource},
)
def outbox_embed_job() -> None:
    outbox_embed_op()


__all__ = ["outbox_embed_job", "outbox_embed_op"]

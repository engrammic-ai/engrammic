"""Dagster asset: marker_cleanup — delete expired Contradiction and StaleCommitment markers."""

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource

# Redis sorted-set key per (silo, node) that indexes which markers reference a node.
# Pattern: markers:{silo_id}:about:{node_id}
_MARKER_INDEX_KEY = "markers:{silo_id}:about:{node_id}"


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="marker_cleanup",
    partitions_def=silo_partitions,
    description="Delete expired Contradiction and StaleCommitment markers.",
    retry_policy=dg.RetryPolicy(max_retries=1, delay=5.0),
    tags={"dagster/concurrency_key": "marker_cleanup"},
)
def marker_cleanup_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Delete Contradiction and StaleCommitment nodes past their expires_at timestamp.

    Uses Option A for correctness: query expired markers first to collect about_ids,
    then delete from graph, then remove stale entries from the Redis marker index.
    """
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int]:
        from context_service.db.queries import DELETE_EXPIRED_MARKERS_ATOMIC

        graph_store = await memgraph.store()
        redis_client = await redis.client()
        now = datetime.now(UTC).isoformat()

        # Atomic delete: query and delete in a single transaction to avoid race conditions.
        # Returns marker IDs and about_ids for Redis cleanup.
        deleted_rows = await graph_store.execute_query(
            DELETE_EXPIRED_MARKERS_ATOMIC,
            {"silo_id": silo_id, "now": now},
        )

        # Build counts and collect about_ids for Redis cleanup.
        deleted_contradictions = 0
        deleted_stale_commitments = 0
        markers_to_clean: list[tuple[str, list[str]]] = []
        for row in deleted_rows:
            marker_id = str(row["id"])
            about_ids: list[str] = list(row.get("about_ids") or [])
            marker_type = str(row.get("marker_type", ""))
            markers_to_clean.append((marker_id, about_ids))
            if marker_type == "Contradiction":
                deleted_contradictions += 1
            else:
                deleted_stale_commitments += 1

        # Remove deleted marker IDs from the Redis sorted-set index.
        # Each about_id has its own key; ZREM the marker_id from every relevant key.
        if markers_to_clean:
            pipe = redis_client.pipeline(transaction=False)
            for marker_id, about_ids in markers_to_clean:
                for node_id in about_ids:
                    key = _MARKER_INDEX_KEY.format(silo_id=silo_id, node_id=node_id)
                    pipe.zrem(key, marker_id)
            await pipe.execute()

        return deleted_contradictions, deleted_stale_commitments

    deleted_contradictions, deleted_stale_commitments = _run_async(_run())
    duration_s = time.monotonic() - t0
    total_deleted = deleted_contradictions + deleted_stale_commitments
    skipped_no_work = total_deleted == 0

    if skipped_no_work:
        context.log.info(f"silo={silo_id} skipped_no_work duration={duration_s:.2f}s")
    else:
        context.log.info(
            f"silo={silo_id} "
            f"contradictions={deleted_contradictions} "
            f"stale_commitments={deleted_stale_commitments} "
            f"duration={duration_s:.2f}s"
        )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "deleted_contradictions": deleted_contradictions,
            "deleted_stale_commitments": deleted_stale_commitments,
            "total_deleted": total_deleted,
            "duration_s": duration_s,
            "skipped_no_work": skipped_no_work,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "deleted_contradictions": dg.MetadataValue.int(deleted_contradictions),
            "deleted_stale_commitments": dg.MetadataValue.int(deleted_stale_commitments),
            "total_deleted": dg.MetadataValue.int(total_deleted),
            "duration_s": dg.MetadataValue.float(duration_s),
            "skipped_no_work": dg.MetadataValue.bool(skipped_no_work),
        },
    )

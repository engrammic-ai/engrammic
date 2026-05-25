"""Dagster asset: marker_cleanup — delete expired Contradiction and StaleCommitment markers."""

import asyncio
import concurrent.futures
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

    async def _run() -> tuple[int, int]:
        from context_service.db.queries import DELETE_EXPIRED_MARKERS, GET_EXPIRED_MARKERS

        graph_store = await memgraph.store()
        redis_client = await redis.client()
        now = datetime.now(UTC).isoformat()

        # Phase 1: collect expired marker IDs and their about_ids before deletion.
        expired_rows = await graph_store.execute_query(
            GET_EXPIRED_MARKERS,
            {"silo_id": silo_id, "now": now},
        )

        # Build a map from marker_id -> list[about_id] per marker type.
        contradictions_to_clean: list[tuple[str, list[str]]] = []
        stale_commitments_to_clean: list[tuple[str, list[str]]] = []
        for row in expired_rows:
            marker_id = str(row["id"])
            about_ids: list[str] = list(row.get("about_ids") or [])
            marker_type = str(row.get("marker_type", ""))
            if marker_type == "Contradiction":
                contradictions_to_clean.append((marker_id, about_ids))
            else:
                stale_commitments_to_clean.append((marker_id, about_ids))

        # Phase 2: delete from graph.
        result = await graph_store.execute_query(
            DELETE_EXPIRED_MARKERS,
            {"silo_id": silo_id, "now": now},
        )
        deleted_contradictions = int(result[0]["deleted_contradictions"]) if result else 0
        deleted_stale_commitments = int(result[0]["deleted_stale_commitments"]) if result else 0

        # Phase 3: remove deleted marker IDs from the Redis sorted-set index.
        # Each about_id has its own key; ZREM the marker_id from every relevant key.
        all_markers_to_clean = contradictions_to_clean + stale_commitments_to_clean
        if all_markers_to_clean:
            pipe = redis_client.pipeline(transaction=False)
            for marker_id, about_ids in all_markers_to_clean:
                for node_id in about_ids:
                    key = _MARKER_INDEX_KEY.format(silo_id=silo_id, node_id=node_id)
                    pipe.zrem(key, marker_id)
            await pipe.execute()

        return deleted_contradictions, deleted_stale_commitments

    deleted_contradictions, deleted_stale_commitments = _run_async(_run())
    total_deleted = deleted_contradictions + deleted_stale_commitments

    context.log.info(
        f"marker_cleanup: silo={silo_id} "
        f"contradictions={deleted_contradictions} "
        f"stale_commitments={deleted_stale_commitments}"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "deleted_contradictions": deleted_contradictions,
            "deleted_stale_commitments": deleted_stale_commitments,
            "total_deleted": total_deleted,
        },
        metadata={
            "deleted_contradictions": deleted_contradictions,
            "deleted_stale_commitments": deleted_stale_commitments,
            "total_deleted": total_deleted,
            "markers_expired_contradictions": deleted_contradictions,
            "markers_expired_stale_commitments": deleted_stale_commitments,
        },
    )

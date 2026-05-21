"""Dagster job to retry failed Qdrant deletes from dead-letter queue."""

import asyncio
import concurrent.futures
import uuid
from typing import Any

import dagster as dg
import structlog
from dagster import AssetExecutionContext

from context_service.pipelines.resources import QdrantResource
from context_service.retention.dead_letter import dequeue_failed_deletes, enqueue_failed_delete

logger = structlog.get_logger(__name__)


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


async def _process_dead_letters(qdrant: QdrantResource) -> dict[str, int]:
    """Dequeue and retry failed Qdrant deletes."""
    qdrant_store = qdrant.qdrant_store()
    entries = await dequeue_failed_deletes(batch_size=100)
    succeeded = 0
    failed = 0

    try:
        for entry in entries:
            try:
                node_uuid = uuid.UUID(entry["node_id"])
            except (ValueError, KeyError) as e:
                logger.warning(
                    "dead_letter_invalid_entry",
                    entry=entry,
                    error=str(e),
                )
                failed += 1
                continue

            try:
                await qdrant_store.delete(
                    node_id=node_uuid,
                    silo_id=entry["silo_id"],
                )
                succeeded += 1
            except Exception as e:
                logger.error(
                    "dead_letter_retry_failed",
                    node_id=entry["node_id"],
                    error=str(e),
                )
                await enqueue_failed_delete(
                    entry["silo_id"],
                    entry["node_id"],
                    str(e),
                )
                failed += 1
    finally:
        if hasattr(qdrant_store, "close"):
            await qdrant_store.close()

    return {"succeeded": succeeded, "failed": failed}


@dg.asset(
    group_name="retention",
    description="Retry failed Qdrant deletes from dead-letter queue",
)
def dead_letter_reconciliation(
    context: AssetExecutionContext,
    qdrant: QdrantResource,
) -> dg.Output[dict[str, int]]:
    """Process dead-letter queue entries."""
    result = _run_async(_process_dead_letters(qdrant))

    context.log.info(
        f"Dead-letter reconciliation: {result['succeeded']} succeeded, {result['failed']} failed"
    )

    return dg.Output(
        value=result,
        metadata={
            "succeeded": dg.MetadataValue.int(result["succeeded"]),
            "failed": dg.MetadataValue.int(result["failed"]),
        },
    )


__all__ = ["dead_letter_reconciliation"]

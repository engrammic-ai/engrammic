"""Dagster asset to prune long supersession chains by stubbing interior nodes."""

import asyncio
import concurrent.futures
import uuid
from typing import Any

import dagster as dg
import structlog
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.resources import MemgraphResource, QdrantResource

logger = structlog.get_logger(__name__)


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling event loop detection."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=600)


async def _prune_chains(
    memgraph: MemgraphResource,
    qdrant: QdrantResource,
    silo_id: str,
    max_length: int,
) -> dict[str, int]:
    """Find and stub interior chain nodes beyond max_length."""
    store = await memgraph.store()
    qdrant_store = qdrant.qdrant_store()

    stubbed = 0
    failed = 0

    try:
        node_ids = await store.find_stale_chain_interior(
            silo_id=silo_id,
            max_length=max_length,
            batch_size=100,
        )

        for node_id in node_ids:
            try:
                success = await store.convert_to_stub(node_id, silo_id)
                if success:
                    try:
                        await qdrant_store.delete(
                            node_id=uuid.UUID(node_id),
                            silo_id=silo_id,
                        )
                    except Exception as e:
                        logger.warning("qdrant_delete_failed", node_id=node_id, error=str(e))
                    stubbed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error("stub_conversion_failed", node_id=node_id, error=str(e))
                failed += 1
    finally:
        if hasattr(qdrant_store, "close"):
            await qdrant_store.close()

    return {"stubbed": stubbed, "failed": failed}


@dg.asset(
    group_name="retention",
    description="Prune long supersession chains by stubbing interior nodes.",
    compute_kind="memgraph",
)
def chain_pruning(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    qdrant: QdrantResource,
) -> dg.Output[dict[str, int]]:
    """Stub interior nodes in chains exceeding max length.

    Reads silo_id from the partition key when running partitioned; falls back
    to ``"default"`` for unpartitioned runs.
    """
    settings = get_settings()
    max_length = settings.retention_supersession_chain_max_length

    try:
        silo_id: str = context.partition_key
    except Exception:
        silo_id = "default"

    result = _run_async(_prune_chains(memgraph, qdrant, silo_id, max_length))

    context.log.info(
        f"chain_pruning silo={silo_id} stubbed={result['stubbed']} failed={result['failed']}"
    )

    return dg.Output(
        value=result,
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "stubbed": dg.MetadataValue.int(result["stubbed"]),
            "failed": dg.MetadataValue.int(result["failed"]),
        },
    )


__all__ = ["chain_pruning"]

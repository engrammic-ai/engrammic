"""Dagster asset: hourly reasoning-chain compaction per silo.

Scans for completed :ReasoningChain nodes (status in "published" or
"retracted", not yet compacted) and converts each into a Memory-layer
:Event node. This keeps the graph lean by tombstoning finished chains
while preserving provenance via :DERIVED_FROM edges.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)

_BATCH_LIMIT = 100


@dg.asset(
    name="reasoning_compaction",
    partitions_def=silo_partitions,
    description=(
        "Compact completed :ReasoningChain nodes into Memory-layer :Event traces. "
        "Runs hourly per silo; tombstones chains while preserving :DERIVED_FROM provenance."
    ),
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "reasoning_compaction"},
)
def reasoning_compaction(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Compact eligible reasoning chains in the partition's silo."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, list[str]]:
        from context_service.engine.compaction import batch_compact_chains

        store = await memgraph.store()

        event_ids = await batch_compact_chains(
            store,
            silo_id,
            limit=_BATCH_LIMIT,
        )
        return len(event_ids), event_ids

    chains_compacted, event_ids = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} chains_compacted={chains_compacted} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "chains_compacted": chains_compacted,
            "event_ids": event_ids,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "chains_compacted": dg.MetadataValue.int(chains_compacted),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["reasoning_compaction"]

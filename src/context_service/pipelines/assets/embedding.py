"""Dagster asset: batch embed committed content nodes and upsert to Qdrant per silo."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import (
    EmbeddingResource,
    MemgraphResource,
    QdrantResource,
)


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


_BATCH_SIZE = 100

# Minimum content length to be worth embedding — matches the MCP service path constant.
_MIN_CONTENT_LEN = 10

_SCAN_UNEMBEDDED_NODES = """
MATCH (n)
WHERE n.silo_id = $silo_id
  AND n.committed = true
  AND coalesce(n.stale, false) = false
  AND (n:Document OR n:Passage OR n:Claim)
  AND n.content IS NOT NULL
  AND n.embedded_at IS NULL
RETURN n.id AS id, n.content AS content, labels(n)[0] AS node_type
LIMIT $batch_size
"""

_MARK_EMBEDDED = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
SET n.embedded_at = $embedded_at
RETURN count(n) AS updated
"""


@dg.asset(
    name="embedding",
    partitions_def=silo_partitions,
    description=(
        "Batch-embed committed content nodes and upsert vectors to Qdrant per silo. "
        "Runs in parallel with the extraction asset — no inter-asset dependency."
    ),
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "embedding"},
)
def embedding_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    qdrant: QdrantResource,
    embedding: EmbeddingResource,
) -> dg.Output[dict[str, Any]]:
    """Read unembedded nodes for the partition's silo, embed in batches, upsert to Qdrant."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, float]:
        from datetime import UTC, datetime

        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        embed_svc = embedding.get_client()

        # qdrant_store() creates a dedicated StoreQdrantClient/EngineQdrantStore
        # pair for this asset run. Close it in `finally` to avoid handle leaks.
        engine_qdrant = qdrant.qdrant_store(vector_size=embed_svc.dimensions)

        try:
            nodes_processed = 0
            vectors_upserted = 0

            max_iterations = 10
            for iteration in range(max_iterations):
                rows = await mg_client.execute_query(
                    _SCAN_UNEMBEDDED_NODES,
                    {"silo_id": silo_id, "batch_size": _BATCH_SIZE},
                )
                if not rows:
                    break

                eligible = [
                    r
                    for r in rows
                    if r.get("content") and len(str(r["content"])) >= _MIN_CONTENT_LEN
                ]

                for batch_start in range(0, len(eligible), _BATCH_SIZE):
                    batch = eligible[batch_start : batch_start + _BATCH_SIZE]
                    texts = [str(r["content"]) for r in batch]

                    try:
                        vectors = await embed_svc.embed(texts)
                    except Exception as exc:
                        context.log.warning(
                            f"embed batch failed at iteration={iteration} offset={batch_start}: {exc}"
                        )
                        continue

                    items = [
                        {
                            "node_id": str(r["id"]),
                            "vector": v,
                            "silo_id": silo_id,
                            "node_type": str(r.get("node_type") or "").lower(),
                        }
                        for r, v in zip(batch, vectors, strict=True)
                    ]

                    try:
                        await engine_qdrant.batch_upsert(items, silo_id)
                        vectors_upserted += len(items)
                    except Exception as exc:
                        context.log.warning(f"qdrant batch upsert failed: {exc}")
                        continue

                    embedded_ids = [str(r["id"]) for r in batch]
                    now_iso = datetime.now(UTC).isoformat()
                    try:
                        await mg_client.execute_write(
                            _MARK_EMBEDDED,
                            {
                                "node_ids": embedded_ids,
                                "silo_id": silo_id,
                                "embedded_at": now_iso,
                            },
                        )
                    except Exception as exc:
                        context.log.warning(f"mark_embedded write failed: {exc}")

                    nodes_processed += len(batch)

                if len(rows) < _BATCH_SIZE:
                    # Fetched fewer than a full page — queue is drained.
                    break

                if iteration == max_iterations - 1:
                    context.log.warning(
                        f"silo={silo_id} hit max_iterations={max_iterations}; "
                        "unembedded nodes may remain"
                    )

            return nodes_processed, vectors_upserted, 0.0
        finally:
            await engine_qdrant.close()

    nodes_processed, vectors_upserted, cost_usd = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} nodes_processed={nodes_processed} "
        f"vectors_upserted={vectors_upserted} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "nodes_processed": nodes_processed,
            "vectors_upserted": vectors_upserted,
            "tokens_used": 0,
            "cost_usd": cost_usd,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "nodes_processed": dg.MetadataValue.int(nodes_processed),
            "vectors_upserted": dg.MetadataValue.int(vectors_upserted),
            "tokens_used": dg.MetadataValue.int(0),
            "cost_usd": dg.MetadataValue.float(cost_usd),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )

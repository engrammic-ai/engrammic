"""One-time migration job to embed legacy nodes that predate write-gate embedding.

Before write-gate embedding was introduced, nodes were created without embeddings
and relied on the custodian batch path. This job backfills those nodes by querying
Memgraph for all nodes with embedded_at IS NULL across all active silos and
embedding them directly via the embedding service and Qdrant.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import dagster as dg

from context_service.pipelines.resources import EmbeddingResource, MemgraphResource, QdrantResource

_LIST_ACTIVE_SILOS = """
MATCH (n) WHERE n.silo_id IS NOT NULL RETURN DISTINCT n.silo_id AS silo_id LIMIT 1000
"""

_SCAN_UNEMBEDDED_NODES = """
MATCH (n)
WHERE n.silo_id = $silo_id
  AND n.content IS NOT NULL
  AND n.content <> ''
  AND n.embedded_at IS NULL
  AND NOT n.state = 'DELETED'
RETURN n.id AS id, n.content AS content, labels(n)[0] AS node_type
SKIP $offset
LIMIT $batch_size
"""

_COUNT_UNEMBEDDED_NODES = """
MATCH (n)
WHERE n.silo_id = $silo_id
  AND n.content IS NOT NULL
  AND n.content <> ''
  AND n.embedded_at IS NULL
  AND NOT n.state = 'DELETED'
RETURN count(n) AS total
"""

_MARK_EMBEDDED = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
SET n.embedded_at = $embedded_at
RETURN count(n) AS updated
"""

BATCH_SIZE = 50
MAX_EMBED_CHARS = 8000
MIN_CONTENT_LEN = 10


@dg.op(required_resource_keys={"memgraph", "qdrant", "embedding"})
def legacy_embed_migration_op(context) -> dict[str, Any]:
    """Embed all nodes with embedded_at IS NULL across all silos."""
    memgraph: MemgraphResource = context.resources.memgraph
    qdrant: QdrantResource = context.resources.qdrant
    embedding: EmbeddingResource = context.resources.embedding

    async def _run() -> dict[str, Any]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        embed_svc = embedding.get_client()
        engine_qdrant = qdrant.qdrant_store()

        try:
            silo_rows = await mg_client.execute_query(_LIST_ACTIVE_SILOS, {})
            silos = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]
            context.log.info(f"legacy_embed_migration: found {len(silos)} active silos")

            total_processed = 0
            total_upserted = 0
            total_errors = 0

            for silo_id in silos:
                count_rows = await mg_client.execute_query(
                    _COUNT_UNEMBEDDED_NODES, {"silo_id": silo_id}
                )
                silo_total = count_rows[0]["total"] if count_rows else 0
                if silo_total == 0:
                    context.log.info(f"legacy_embed_migration: silo={silo_id} no unembedded nodes")
                    continue

                context.log.info(f"legacy_embed_migration: silo={silo_id} unembedded={silo_total}")

                offset = 0
                while True:
                    rows = await mg_client.execute_query(
                        _SCAN_UNEMBEDDED_NODES,
                        {"silo_id": silo_id, "offset": offset, "batch_size": BATCH_SIZE},
                    )
                    if not rows:
                        break

                    eligible = [
                        r
                        for r in rows
                        if r.get("content") and len(str(r["content"])) >= MIN_CONTENT_LEN
                    ]

                    if not eligible:
                        offset += len(rows)
                        continue

                    texts = [str(r["content"])[:MAX_EMBED_CHARS] for r in eligible]

                    try:
                        vectors = await embed_svc.embed(texts)
                    except Exception as exc:
                        context.log.warning(
                            f"legacy_embed_migration: embed batch failed silo={silo_id} offset={offset}: {exc}"
                        )
                        total_errors += len(eligible)
                        offset += len(rows)
                        continue

                    items = [
                        {
                            "node_id": str(r["id"]),
                            "vector": v,
                            "silo_id": silo_id,
                            "node_type": str(r.get("node_type") or "").lower(),
                        }
                        for r, v in zip(eligible, vectors, strict=True)
                    ]

                    try:
                        await engine_qdrant.batch_upsert(items, silo_id)
                        total_upserted += len(items)
                    except Exception as exc:
                        context.log.warning(
                            f"legacy_embed_migration: qdrant upsert failed silo={silo_id} offset={offset}: {exc}"
                        )
                        total_errors += len(items)
                        offset += len(rows)
                        continue

                    embedded_ids = [str(r["id"]) for r in eligible]
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
                        context.log.warning(
                            f"legacy_embed_migration: mark_embedded failed silo={silo_id}: {exc}"
                        )

                    total_processed += len(eligible)
                    offset += len(rows)

                    context.log.info(
                        f"legacy_embed_migration: silo={silo_id} progress={total_processed}"
                    )

                    if len(rows) < BATCH_SIZE:
                        break

            return {
                "silos_processed": len(silos),
                "nodes_processed": total_processed,
                "vectors_upserted": total_upserted,
                "errors": total_errors,
            }
        finally:
            await engine_qdrant.close()

    return asyncio.run(_run())


@dg.job(
    name="sage_legacy_embed_migration_job",
    description="One-time migration: embed all nodes that predate write-gate embedding.",
)
def sage_legacy_embed_migration_job() -> None:
    """Backfill embeddings for legacy nodes with embedded_at IS NULL across all silos."""
    legacy_embed_migration_op()

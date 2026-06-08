"""Re-embedding job for migrating to task-type-aware embeddings.

One-time migration job to re-embed all existing nodes with RETRIEVAL_DOCUMENT
task type for improved asymmetric retrieval with Vertex AI embeddings.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import dagster as dg

from context_service.config.settings import get_settings
from context_service.pipelines.resources import MemgraphResource, QdrantResource

_LIST_NODES_FOR_REEMBED = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
  AND n.content IS NOT NULL
  AND n.content <> ''
  AND n.state <> 'DELETED'
RETURN n.id AS id, n.silo_id AS silo_id, n.content AS content, n.type AS node_type
ORDER BY n.created_at DESC
LIMIT $limit
OFFSET $offset
"""

_COUNT_NODES = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
  AND n.content IS NOT NULL
  AND n.content <> ''
  AND n.state <> 'DELETED'
RETURN count(n) AS total
"""

BATCH_SIZE = 50


@dg.op(required_resource_keys={"memgraph", "qdrant"})
def reembed_all_nodes_op(context) -> dict[str, Any]:
    """Re-embed all nodes with RETRIEVAL_DOCUMENT task type."""
    from context_service.config.models import load_models_config
    from context_service.embeddings.litellm_embeddings import LiteLLMEmbeddingService

    settings = get_settings()
    models_config = load_models_config()

    memgraph: MemgraphResource = context.resources.memgraph
    qdrant: QdrantResource = context.resources.qdrant

    async def _run() -> dict[str, Any]:
        mg_store = await memgraph.store()
        qd_store = qdrant.qdrant_store()

        # Get embedding service
        embed_model = models_config.litellm_embedding_model
        if embed_model is None:
            context.log.error("No embedding model configured")
            return {"error": "no_embedding_model", "processed": 0}

        embedding_svc = LiteLLMEmbeddingService(
            model=embed_model,
            dimensions=settings.embedding_dimensions,
        )

        # Count total nodes
        count_result = await mg_store.execute_query(_COUNT_NODES, {})
        total = count_result[0]["total"] if count_result else 0
        context.log.info(f"reembed: found {total} nodes to process")

        processed = 0
        errors = 0
        offset = 0

        while True:
            # Fetch batch
            rows = await mg_store.execute_query(
                _LIST_NODES_FOR_REEMBED,
                {"limit": BATCH_SIZE, "offset": offset},
            )

            if not rows:
                break

            # Extract content for embedding
            contents = [r["content"] for r in rows]

            try:
                # Re-embed with RETRIEVAL_DOCUMENT task type
                embeddings = await embedding_svc.embed(contents)

                # Upsert to Qdrant
                for row, vector in zip(rows, embeddings, strict=True):
                    node_id = uuid.UUID(row["id"])
                    silo_id = row["silo_id"]
                    node_type = row.get("node_type")

                    await qd_store.upsert(
                        node_id=node_id,
                        vector=vector,
                        silo_id=silo_id,
                        node_type=node_type,
                    )

                processed += len(rows)
                context.log.info(f"reembed: processed {processed}/{total}")

            except Exception as e:
                errors += len(rows)
                context.log.error(f"reembed: batch failed at offset {offset}: {e}")

            offset += BATCH_SIZE

        await embedding_svc.close()

        return {
            "total": total,
            "processed": processed,
            "errors": errors,
        }

    return asyncio.run(_run())


@dg.job(name="reembed_migration")
def reembed_migration() -> None:
    """One-time migration job to re-embed all nodes with task types."""
    reembed_all_nodes_op()

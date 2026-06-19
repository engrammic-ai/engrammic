"""SPO backfill job for existing claims without subject/predicate/object.

One-time migration job to extract SPO triples from claims that were created
before SPO extraction was added, enabling semantic corroboration.
"""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource

_LIST_CLAIMS_WITHOUT_SPO = """
MATCH (c:Claim)
WHERE c.silo_id IS NOT NULL
  AND c.content IS NOT NULL
  AND c.content <> ''
  AND (c.properties.state IS NULL OR c.properties.state = 'ACTIVE')
  AND (c.properties.subject IS NULL OR c.properties.predicate IS NULL OR c.properties.object IS NULL)
RETURN c.id AS id, c.silo_id AS silo_id, c.content AS content
ORDER BY c.created_at DESC
SKIP $offset
LIMIT $limit
"""

_COUNT_CLAIMS_WITHOUT_SPO = """
MATCH (c:Claim)
WHERE c.silo_id IS NOT NULL
  AND c.content IS NOT NULL
  AND c.content <> ''
  AND (c.properties.state IS NULL OR c.properties.state = 'ACTIVE')
  AND (c.properties.subject IS NULL OR c.properties.predicate IS NULL OR c.properties.object IS NULL)
RETURN count(c) AS total
"""

_UPDATE_CLAIM_SPO = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
SET c.properties.subject = $subject,
    c.properties.predicate = $predicate,
    c.properties.object = $object
RETURN c.id AS id
"""

BATCH_SIZE = 20


@dg.op(required_resource_keys={"memgraph"})
def backfill_spo_op(context) -> dict[str, Any]:
    """Extract and store SPO triples for claims missing them."""
    from context_service.config.models import load_models_config
    from context_service.llm.litellm_provider import LiteLLMProvider
    from context_service.llm.spo_extractor import extract_spo

    models_config = load_models_config()
    memgraph: MemgraphResource = context.resources.memgraph

    async def _run() -> dict[str, Any]:
        mg_store = await memgraph.store()

        extractor_model = models_config.litellm_expander_model
        if not extractor_model:
            context.log.error("No expander model configured for SPO extraction")
            return {"error": "no_model", "processed": 0, "updated": 0, "failed": 0}

        llm = LiteLLMProvider(
            model=extractor_model,
            vertex_project=models_config.vertex_project or None,
            vertex_location=models_config.vertex_location or None,
        )

        # Count total
        count_result = await mg_store.execute_query(_COUNT_CLAIMS_WITHOUT_SPO, {})
        total = count_result[0]["total"] if count_result else 0
        context.log.info(f"Found {total} claims without SPO")

        processed = 0
        updated = 0
        failed = 0
        offset = 0

        while True:
            batch = await mg_store.execute_query(
                _LIST_CLAIMS_WITHOUT_SPO,
                {"offset": offset, "limit": BATCH_SIZE},
            )

            if not batch:
                break

            for row in batch:
                claim_id = row["id"]
                silo_id = row["silo_id"]
                content = row["content"]

                try:
                    triple = await extract_spo(llm, content)
                    if triple and triple.is_valid():
                        await mg_store.execute_write(
                            _UPDATE_CLAIM_SPO,
                            {
                                "claim_id": claim_id,
                                "silo_id": silo_id,
                                "subject": triple.subject,
                                "predicate": triple.predicate,
                                "object": triple.object,
                            },
                        )
                        updated += 1
                        context.log.debug(
                            f"Updated claim {claim_id}: ({triple.subject}, {triple.predicate}, {triple.object})"
                        )
                    else:
                        failed += 1
                        context.log.warning(f"SPO extraction returned empty for claim {claim_id}")
                except Exception as e:
                    failed += 1
                    context.log.warning(f"SPO extraction failed for claim {claim_id}: {e}")

                processed += 1

            offset += len(batch)
            context.log.info(f"Progress: {processed}/{total} processed, {updated} updated, {failed} failed")

        return {
            "total": total,
            "processed": processed,
            "updated": updated,
            "failed": failed,
        }

    return asyncio.get_event_loop().run_until_complete(_run())


@dg.job(
    name="spo_backfill",
    description="Backfill SPO triples for claims missing subject/predicate/object",
)
def spo_backfill_job():
    """One-time job to extract SPO for existing claims."""
    backfill_spo_op()

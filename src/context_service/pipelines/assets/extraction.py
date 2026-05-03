"""Dagster asset: batch extraction of :Document nodes to :Claim/:Entity per silo."""

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource

_BATCH_SIZE = 50

_PENDING_DOCUMENTS = """
MATCH (d:Document {silo_id: $silo_id})
WHERE NOT EXISTS((d)<-[:EXTRACTED_FROM]-(:Claim))
RETURN d.id AS id, d.content AS content
LIMIT $batch
"""


@dg.asset(
    name="extraction",
    partitions_def=silo_partitions,
    description="Batch-extract :Claim/:Entity nodes from pending :Document nodes per silo.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "extraction"},
)
def extraction(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Read pending :Document nodes for the partition's silo, run LLM extraction, write :Claim nodes."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, int, float]:
        from context_service.db import queries
        from context_service.extraction.identity import claim_id as make_claim_id
        from context_service.extraction.models import (
            ClaimTriple,
            EntityMention,
            ExtractionResult,
        )
        from context_service.extraction.service import ExtractionService
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        llm_provider = llm.get_client()

        docs_processed = 0
        claims_created = 0
        tokens_used = 0

        svc = ExtractionService.llm_only(llm_provider)

        max_iterations = 10
        for iteration in range(max_iterations):
            rows = await client.execute_query(
                _PENDING_DOCUMENTS,
                {"silo_id": silo_id, "batch": _BATCH_SIZE},
            )
            if not rows:
                break

            now = datetime.now(UTC).isoformat()

            # Accumulate writes across all docs in this batch, then issue
            # exactly 4 RTTs after the loop. R-003/F-016 from 2026-04-28 review.
            all_claim_rows: list[dict[str, Any]] = []
            all_attach_rows: list[dict[str, Any]] = []
            all_mention_rows: list[dict[str, Any]] = []
            all_ref_rows: list[dict[str, Any]] = []

            for row in rows:
                doc_id: str = str(row["id"])
                content: str = str(row.get("content") or "")
                if not content:
                    context.log.warning(f"doc {doc_id} has no content; skipping")
                    continue

                try:
                    result: ExtractionResult
                    result, usage = await svc.extract(content)
                    tokens_used += usage.total_tokens
                    docs_processed += 1
                except Exception as exc:
                    context.log.warning(f"extraction failed for doc {doc_id}: {exc}")
                    continue

                entity_type_by_name = {e.name: e.entity_type for e in result.entities}
                triples: list[ClaimTriple] = []
                for rel in result.relationships:
                    predicate = (rel.kind or rel.relationship_type.value).strip().lower()
                    if not predicate:
                        predicate = rel.relationship_type.value.lower()
                    mentions = [
                        EntityMention(
                            entity_id=_stable_entity_id(silo_id, rel.source),
                            name=rel.source,
                            entity_type=entity_type_by_name.get(rel.source, "unknown"),
                        ),
                        EntityMention(
                            entity_id=_stable_entity_id(silo_id, rel.target),
                            name=rel.target,
                            entity_type=entity_type_by_name.get(rel.target, "unknown"),
                        ),
                    ]
                    triples.append(
                        ClaimTriple(
                            subject=rel.source,
                            predicate=predicate,
                            object=rel.target,
                            source_passage_id=doc_id,
                            source_doc_id=doc_id,
                            valid_from=now,
                            valid_to=None,
                            confidence=rel.confidence,
                            entity_mentions=mentions,
                        )
                    )

                if not triples:
                    continue

                for t in triples:
                    cid = make_claim_id(
                        t.subject,
                        t.predicate,
                        t.object,
                        t.valid_from,
                        t.valid_to,
                        t.source_doc_id,
                    )
                    all_claim_rows.append(
                        {
                            "claim_id": cid,
                            "fingerprint": cid,
                            "subject": t.subject,
                            "predicate": t.predicate,
                            "object": t.object,
                            "valid_from": t.valid_from,
                            "valid_to": t.valid_to,
                            "source_doc_id": t.source_doc_id,
                            "source_passage_id": t.source_passage_id,
                            "confidence": t.confidence,
                            "created_at": now,
                        }
                    )
                    all_attach_rows.append({"doc_id": doc_id, "claim_id": cid})
                    for m in t.entity_mentions:
                        all_mention_rows.append(
                            {
                                "entity_id": m.entity_id,
                                "silo_id": silo_id,
                                "name": m.name,
                                "entity_type": m.entity_type,
                                "created_at": now,
                                "claim_id": cid,
                            }
                        )
                    if t.ref_doc_id:
                        all_ref_rows.append({"claim_id": cid, "ref_doc_id": t.ref_doc_id})

                claims_created += len(triples)

            # Exactly 4 RTTs per iteration batch (or fewer if some lists empty).
            if all_claim_rows:
                await client.execute_write(
                    queries.BATCH_UPSERT_CLAIMS,
                    {"claims": all_claim_rows, "silo_id": silo_id},
                )
                await client.execute_write(
                    queries.BATCH_ATTACH_CLAIMS_TO_DOCUMENT,
                    {"rows": all_attach_rows, "silo_id": silo_id},
                )
            if all_mention_rows:
                await client.execute_write(
                    queries.BATCH_UPSERT_ENTITY_MENTIONS,
                    {"rows": all_mention_rows, "silo_id": silo_id},
                )
            if all_ref_rows:
                await client.execute_write(
                    queries.BATCH_ATTACH_CLAIM_REFERENCES,
                    {"rows": all_ref_rows, "silo_id": silo_id},
                )

            if len(rows) < _BATCH_SIZE:
                # Fetched fewer than a full page — queue is drained.
                break

            if iteration == max_iterations - 1:
                context.log.warning(
                    f"silo={silo_id} hit max_iterations={max_iterations}; "
                    "pending documents may remain"
                )

        return docs_processed, claims_created, tokens_used, 0.0

    docs_processed, claims_created, tokens_used, cost_usd = asyncio.run(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} docs={docs_processed} claims={claims_created} "
        f"tokens={tokens_used} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "docs_processed": docs_processed,
            "claims_created": claims_created,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "docs_processed": dg.MetadataValue.int(docs_processed),
            "claims_created": dg.MetadataValue.int(claims_created),
            "tokens_used": dg.MetadataValue.int(tokens_used),
            "cost_usd": dg.MetadataValue.float(cost_usd),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


def _stable_entity_id(silo_id: str, name: str) -> str:
    """Deterministic entity id from silo + lowercased name."""
    key = f"{silo_id}:{name.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

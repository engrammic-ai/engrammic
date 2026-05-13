"""Dagster asset: batch extraction of :Document nodes to :Claim/:Entity per silo."""

import asyncio
import concurrent.futures
import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource, RedisResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


_BATCH_SIZE = 50

_PENDING_DOCUMENTS = """
MATCH (d:Document {silo_id: $silo_id})
WHERE size([(d)<-[:EXTRACTED_FROM]-(c:Claim) | c]) = 0
RETURN d.id AS id, d.content AS content, d.source_uri AS source_uri
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
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Read pending :Document nodes for the partition's silo, run LLM extraction, write :Claim nodes."""
    from context_service.config.logging import set_dagster_context

    set_dagster_context(context)
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, int, float, int]:
        from pathlib import Path

        from context_service.cache.alias_cache import AliasCache
        from context_service.db import queries
        from context_service.extraction.alias_lookup import resolve_alias
        from context_service.extraction.filter.audit import FilterAuditor
        from context_service.extraction.filter.config import load_filter_rule_set
        from context_service.extraction.filter.llm_classifier import LLMClassifierRule
        from context_service.extraction.filter.orchestrator import FilterOrchestrator
        from context_service.extraction.filter.wikidata import WikidataRule
        from context_service.extraction.identity import claim_id as make_claim_id
        from context_service.extraction.models import (
            ClaimTriple,
            EntityMention,
            ExtractionResult,
        )
        from context_service.extraction.service import ExtractionService
        from context_service.stores import MemgraphClient
        from context_service.stores.redis import RedisClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        llm_provider = llm.get_client()
        redis_client = RedisClient(await redis.client())
        alias_cache = AliasCache(redis_client)

        config_path = Path(__file__).parents[4] / "config" / "extraction_filter.yaml"
        rule_set = load_filter_rule_set(config_path, silo_override=None)

        class _NoOpWriter:
            def insert_many(self, rows: list[dict[str, object]]) -> None:
                pass

        auditor = FilterAuditor(_NoOpWriter())
        wikidata_rule = WikidataRule(rule_set, redis_client, silo_id=silo_id)
        llm_rule = LLMClassifierRule(rule_set, llm_provider, silo_id=silo_id)
        filter_orchestrator = FilterOrchestrator(rule_set, wikidata_rule, llm_rule, auditor)

        docs_processed = 0
        claims_created = 0
        claims_filtered = 0
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
                source_uri: str | None = row.get("source_uri")
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
                    source_alias = await resolve_alias(
                        cache=alias_cache, silo_id=silo_id, surface_form=rel.source
                    )
                    target_alias = await resolve_alias(
                        cache=alias_cache, silo_id=silo_id, surface_form=rel.target
                    )
                    mentions = [
                        EntityMention(
                            entity_id=(
                                source_alias["entity_id"]
                                if source_alias
                                else _stable_entity_id(silo_id, rel.source)
                            ),
                            name=(source_alias["canonical_name"] if source_alias else rel.source),
                            entity_type=entity_type_by_name.get(rel.source, "unknown"),
                        ),
                        EntityMention(
                            entity_id=(
                                target_alias["entity_id"]
                                if target_alias
                                else _stable_entity_id(silo_id, rel.target)
                            ),
                            name=(target_alias["canonical_name"] if target_alias else rel.target),
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

                decisions = await filter_orchestrator.evaluate(triples, silo_id)
                kept_triples = [
                    t for t, d in zip(triples, decisions, strict=True) if d.action == "keep"
                ]
                claims_filtered += len(triples) - len(kept_triples)

                if not kept_triples:
                    continue

                for t in kept_triples:
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
                    elif source_uri:
                        all_ref_rows.append({"claim_id": cid, "ref_doc_id": doc_id})

                claims_created += len(kept_triples)

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

        return docs_processed, claims_created, tokens_used, 0.0, claims_filtered

    docs_processed, claims_created, tokens_used, cost_usd, claims_filtered = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} docs={docs_processed} claims={claims_created} filtered={claims_filtered} "
        f"tokens={tokens_used} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "docs_processed": docs_processed,
            "claims_created": claims_created,
            "claims_filtered": claims_filtered,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "docs_processed": dg.MetadataValue.int(docs_processed),
            "claims_created": dg.MetadataValue.int(claims_created),
            "claims_filtered": dg.MetadataValue.int(claims_filtered),
            "tokens_used": dg.MetadataValue.int(tokens_used),
            "cost_usd": dg.MetadataValue.float(cost_usd),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


def _stable_entity_id(silo_id: str, name: str) -> str:
    """Deterministic entity id from silo + lowercased name."""
    key = f"{silo_id}:{name.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

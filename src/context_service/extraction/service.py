"""Extraction service for entity/relationship extraction from context."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger
from context_service.db import queries
from context_service.db.queries import build_batch_entity_rel_query
from context_service.extraction.identity import (
    claim_id as make_claim_id,
)
from context_service.extraction.identity import (
    contradicts_edge_id,
)
from context_service.extraction.models import (
    SYMMETRIC_RELATIONSHIP_TYPES,
    ClaimTriple,
    ContradictsPair,
    EntityMention,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    ExtractionStatus,
    RelationshipType,
    RelationshipValidationError,
)
from context_service.extraction.prompts import (
    EXTRACTION_SCHEMA,
    get_extraction_system_prompt,
    get_extraction_user_template,
)

if TYPE_CHECKING:
    from context_service.extraction.filter.orchestrator import FilterOrchestrator
    from context_service.extraction.job_store import ExtractionJobStore
    from context_service.extraction.models import ExtractionJob
    from context_service.llm.base import LLMProvider, Usage
    from context_service.stores.memgraph import MemgraphClient

logger = get_logger(__name__)


class ExtractionError(Exception):
    """Raised when extraction operations fail."""


class ExtractionService:
    """Service for extracting entities and relationships from context nodes."""

    def __init__(
        self,
        llm: LLMProvider,
        memgraph: MemgraphClient,
        job_store: ExtractionJobStore,
        *,
        filter_orchestrator: FilterOrchestrator | None = None,
    ) -> None:
        self._llm = llm
        self._memgraph = memgraph
        self._job_store = job_store
        self._filter = filter_orchestrator

    @classmethod
    def llm_only(cls, llm: LLMProvider) -> ExtractionService:
        """Construct a service capable of running extract() with only an LLM.

        The resulting instance must not call any method that touches memgraph or
        job_store. Used by the Dagster extraction asset which manages graph writes
        directly via batched Cypher.
        """
        from typing import Any, cast

        inst: ExtractionService = object.__new__(cls)
        inst._llm = llm
        inst._memgraph = cast(Any, None)
        inst._job_store = cast(Any, None)
        inst._filter = None
        return inst

    async def extract(self, content: str) -> tuple[ExtractionResult, Usage]:
        """Extract entities and relationships from content using LLM.

        Returns:
            Tuple of ``(ExtractionResult, Usage)`` where ``Usage`` captures
            the single extraction LLM call's token/cost envelope.
        """
        messages = [
            {"role": "system", "content": get_extraction_system_prompt()},
            {"role": "user", "content": get_extraction_user_template().format(content=content)},
        ]

        try:
            raw, usage = await self._llm.extract_structured(
                messages, EXTRACTION_SCHEMA, timeout=90.0
            )
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}", exc_info=True)
            raise ExtractionError(f"LLM extraction failed: {e}") from e

        entities = [
            ExtractedEntity(
                name=e["name"],
                entity_type=e.get("entity_type", e.get("type", "unknown")),
                description=e.get("description", ""),
                qualified_name=e.get("qualified_name"),
                file_path=e.get("file_path"),
            )
            for e in raw.get("entities", [])
        ]

        relationships: list[ExtractedRelationship] = []
        for r in raw.get("relationships", []):
            source = r.get("source") or r.get("from") or r.get("src") or r.get("source_entity")
            target = r.get("target") or r.get("to") or r.get("tgt") or r.get("target_entity")
            if not source or not target:
                continue
            raw_rel_type = (
                r.get("relationship_type")
                or r.get("type")
                or r.get("relation")
                or r.get("rel_type")
            )
            if not raw_rel_type:
                logger.warning(
                    f"Skipping relationship {source} -> {target}: missing relationship_type"
                )
                continue
            # Normalize to the closed vocabulary; drop anything outside it.
            try:
                rel_type = RelationshipType(str(raw_rel_type).upper())
            except ValueError:
                logger.warning(
                    f"Skipping relationship {source} -> {target}: "
                    f"unknown relationship_type {raw_rel_type!r}"
                )
                continue

            kind = str(r.get("kind") or "").strip().lower().replace(" ", "_")
            # LLM may omit directed; fall back to type-driven default.
            if "directed" in r and r["directed"] is not None:
                directed = bool(r["directed"])
            else:
                directed = rel_type not in SYMMETRIC_RELATIONSHIP_TYPES
            try:
                confidence = float(r.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            confidence = max(0.0, min(1.0, confidence))
            temporal = r.get("temporal")
            if temporal not in (None, "past", "future"):
                temporal = None
            source_node_ids = r.get("source_node_ids") or []
            if not isinstance(source_node_ids, list):
                source_node_ids = []

            try:
                relationships.append(
                    ExtractedRelationship(
                        source=source,
                        target=target,
                        relationship_type=rel_type,
                        kind=kind,
                        directed=directed,
                        confidence=confidence,
                        temporal=temporal,
                        source_node_ids=[str(s) for s in source_node_ids],
                    )
                )
            except RelationshipValidationError as e:
                logger.warning(f"Skipping invalid relationship {source} -> {target}: {e}")

        return ExtractionResult(entities=entities, relationships=relationships), usage

    async def apply_to_graph(
        self,
        silo_id: str,
        node_id: str,
        result: ExtractionResult,
    ) -> tuple[int, int]:
        """Apply extraction results to the graph (Entity+Rel side only).

        Returns (entities_created, relationships_created). Callers that also
        need the name->entity_id map should call :meth:`_apply_entities_and_rels`.
        """
        ent, rel, _ = await self._apply_entities_and_rels(silo_id, node_id, result)
        return ent, rel

    async def _apply_entities_and_rels(
        self,
        silo_id: str,
        node_id: str,
        result: ExtractionResult,
    ) -> tuple[int, int, dict[str, str]]:
        """Entity+Rel writer shared by apply_to_graph and run_extraction_job."""
        now = datetime.now(UTC)
        entity_id_map: dict[str, str] = {}

        if result.entities:
            entity_id_map = await self._batch_find_or_create_entities(silo_id, result.entities, now)

        entities_created = len(entity_id_map)

        # Batch create entity relationships
        relationships_created = 0
        rels_data: list[dict[str, Any]] = []
        for rel in result.relationships:
            source_id = entity_id_map.get(rel.source)
            target_id = entity_id_map.get(rel.target)
            if source_id is None or target_id is None:
                logger.warning(
                    f"Skipping relationship {rel.source} -> {rel.target}: "
                    f"entity not found in extraction"
                )
                continue
            # Defensive: re-validate that the type is in the closed enum.
            try:
                rel_type_enum = RelationshipType(rel.relationship_type)
            except ValueError:
                logger.warning(
                    f"Skipping relationship {rel.source} -> {rel.target}: "
                    f"invalid relationship_type {rel.relationship_type!r}"
                )
                continue
            rels_data.append(
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "rel_type": rel_type_enum.value,
                    "kind": rel.kind,
                    "directed": rel.directed,
                    "confidence": rel.confidence,
                    "temporal": rel.temporal,
                    "source_node_ids": rel.source_node_ids,
                    "created_at": now.isoformat(),
                }
            )

        if rels_data:
            # Group relationships by rel_type so the edge label can be baked into
            # the Cypher (Memgraph does not support parameterized edge labels).
            grouped: dict[str, list[dict[str, Any]]] = {}
            for rd in rels_data:
                grouped.setdefault(rd["rel_type"], []).append(rd)

            for rel_type, group_rels in grouped.items():
                try:
                    result_rows = await self._memgraph.execute_write(
                        build_batch_entity_rel_query(rel_type),
                        {"rels": group_rels, "silo_id": silo_id},
                    )
                    relationships_created += result_rows[0].get("created", 0) if result_rows else 0
                except Exception as e:
                    logger.warning(
                        f"Failed to batch create {rel_type} entity relationships: {e}",
                        exc_info=True,
                    )

        logger.info(
            f"Applied extraction to node {node_id}: "
            f"{entities_created} entities, {relationships_created} relationships"
        )
        return entities_created, relationships_created, entity_id_map

    async def _batch_find_or_create_entities(
        self,
        silo_id: str,
        entities: list[ExtractedEntity],
        now: datetime,
    ) -> dict[str, str]:
        """Find or create all entities in a single Memgraph round trip.

        Dedup semantics match the legacy per-entity path: case-insensitive
        match on name, or on qualified_name when provided. Returns a
        ``{entity.name -> entity_id}`` map preserving the original casing
        used by downstream relationship wiring.
        """
        # Deduplicate inputs by (name_lower, qualified_name_lower) so the
        # same entity repeated in one extraction only consumes one row.
        seen: dict[tuple[str, str | None], ExtractedEntity] = {}
        order: list[ExtractedEntity] = []
        for ent in entities:
            key = (
                ent.name.lower(),
                ent.qualified_name.lower() if ent.qualified_name else None,
            )
            if key not in seen:
                seen[key] = ent
                order.append(ent)

        rows = [
            {
                "name": ent.name,
                "name_lower": ent.name.lower(),
                "qualified_name": ent.qualified_name,
                "qualified_name_lower": (
                    ent.qualified_name.lower() if ent.qualified_name else None
                ),
                "entity_type": ent.entity_type,
                "description": ent.description,
                "file_path": ent.file_path,
                "new_id": str(uuid.uuid4()),
            }
            for ent in order
        ]

        results = await self._memgraph.execute_write(
            queries.BATCH_FIND_OR_CREATE_ENTITIES,
            {
                "entities": rows,
                "silo_id": silo_id,
                "created_at": now.isoformat(),
            },
        )

        id_by_name_lower: dict[str, str] = {}
        for row in results or []:
            name = row.get("name")
            eid = row.get("id")
            if name is None or eid is None:
                continue
            id_by_name_lower[str(name).lower()] = str(eid)

        # Map back to original entity.name (preserving casing) for every input,
        # including duplicates that collapsed during dedup above.
        entity_id_map: dict[str, str] = {}
        for ent in entities:
            eid = id_by_name_lower.get(ent.name.lower())
            if eid is not None:
                entity_id_map[ent.name] = eid
            else:
                logger.warning(f"Batch entity upsert returned no id for {ent.name!r}; skipping")
        return entity_id_map

    async def apply_claims_to_graph(
        self,
        silo_id: str,
        triples: list[ClaimTriple],
    ) -> int:
        """Write Stage-5 Claim/Entity nodes and typed edges.

        For each triple:
        1. MERGE :Claim (deterministic ID, committed=true)
        2. MERGE Passage<-[:EXTRACTED_FROM]-Claim
        3. MERGE :Entity + Claim-[:MENTIONS]->Entity for each mention
        4. MERGE Claim-[:REFERENCES]->Document when ref_doc_id is set

        Returns the number of claims written.
        """
        now = datetime.now(UTC).isoformat()
        claims_written = 0
        for triple in triples:
            fingerprint = make_claim_id(
                triple.subject,
                triple.predicate,
                triple.object,
                triple.valid_from,
                triple.valid_to,
                triple.source_doc_id,
            )
            cid = fingerprint  # fingerprint == id per spec O-12

            try:
                await self._memgraph.execute_write(
                    queries.UPSERT_CLAIM,
                    {
                        "claim_id": cid,
                        "silo_id": silo_id,
                        "fingerprint": fingerprint,
                        "subject": triple.subject,
                        "predicate": triple.predicate,
                        "object": triple.object,
                        "valid_from": triple.valid_from,
                        "valid_to": triple.valid_to,
                        "source_doc_id": triple.source_doc_id,
                        "source_passage_id": triple.source_passage_id,
                        "confidence": triple.confidence,
                        "created_at": now,
                    },
                )
                await self._memgraph.execute_write(
                    queries.ATTACH_CLAIM_TO_PASSAGE,
                    {
                        "passage_id": triple.source_passage_id,
                        "claim_id": cid,
                        "silo_id": silo_id,
                    },
                )
                for mention in triple.entity_mentions:
                    await self._memgraph.execute_write(
                        queries.UPSERT_ENTITY_MENTION,
                        {
                            "entity_id": mention.entity_id,
                            "silo_id": silo_id,
                            "name": mention.name,
                            "entity_type": mention.entity_type,
                            "created_at": now,
                            "claim_id": cid,
                        },
                    )
                if triple.ref_doc_id:
                    await self._memgraph.execute_write(
                        queries.ATTACH_CLAIM_REFERENCES_DOC,
                        {
                            "claim_id": cid,
                            "silo_id": silo_id,
                            "ref_doc_id": triple.ref_doc_id,
                        },
                    )
                claims_written += 1
            except Exception as e:
                logger.warning(f"Failed to write claim {cid!r}: {e}", exc_info=True)

        return claims_written

    def _synthesize_claim_triples(
        self,
        result: ExtractionResult,
        entity_id_map: dict[str, str],
        doc_id: str,
        now: datetime,
    ) -> list[ClaimTriple]:
        """Option-alpha synthesis: one ClaimTriple per ExtractedRelationship.

        Each rel becomes a Claim whose subject/object are the rel endpoints and
        whose predicate is the free-form ``kind`` (falling back to the closed
        relationship_type label). Entity mentions are built from the shared
        entity_id_map. Rels referencing entities that failed to upsert are
        skipped (logged).
        """
        now_iso = now.isoformat()
        triples: list[ClaimTriple] = []
        entity_type_by_name: dict[str, str] = {e.name: e.entity_type for e in result.entities}
        for rel in result.relationships:
            src_id = entity_id_map.get(rel.source)
            tgt_id = entity_id_map.get(rel.target)
            if not src_id or not tgt_id:
                logger.warning(
                    f"Claim synthesis skip {rel.source}->{rel.target}: missing entity id in map"
                )
                continue
            predicate = (rel.kind or rel.relationship_type.value).strip().lower()
            if not predicate:
                predicate = rel.relationship_type.value.lower()
            mentions = [
                EntityMention(
                    entity_id=src_id,
                    name=rel.source,
                    entity_type=entity_type_by_name.get(rel.source, "unknown"),
                ),
                EntityMention(
                    entity_id=tgt_id,
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
                    valid_from=now_iso,
                    valid_to=None,
                    confidence=rel.confidence,
                    entity_mentions=mentions,
                )
            )
        return triples

    async def apply_document_claims(
        self,
        silo_id: str,
        doc_id: str,
        triples: list[ClaimTriple],
    ) -> list[str]:
        """Write Claim/Entity nodes + edges, attaching each Claim to a Document.

        Mirrors :meth:`apply_claims_to_graph` but uses ATTACH_CLAIM_TO_DOCUMENT
        (EXTRACTED_FROM -> Document) instead of ATTACH_CLAIM_TO_PASSAGE.
        Per A3 decision (plan 2026-04-20), extraction runs per-Document and
        the walker treats Document/Passage uniformly via the content-union.
        """
        now = datetime.now(UTC).isoformat()
        written_ids: list[str] = []
        for triple in triples:
            fingerprint = make_claim_id(
                triple.subject,
                triple.predicate,
                triple.object,
                triple.valid_from,
                triple.valid_to,
                triple.source_doc_id,
            )
            cid = fingerprint
            try:
                await self._memgraph.execute_write(
                    queries.UPSERT_CLAIM,
                    {
                        "claim_id": cid,
                        "silo_id": silo_id,
                        "fingerprint": fingerprint,
                        "subject": triple.subject,
                        "predicate": triple.predicate,
                        "object": triple.object,
                        "valid_from": triple.valid_from,
                        "valid_to": triple.valid_to,
                        "source_doc_id": triple.source_doc_id,
                        "source_passage_id": triple.source_passage_id,
                        "confidence": triple.confidence,
                        "created_at": now,
                    },
                )
                await self._memgraph.execute_write(
                    queries.ATTACH_CLAIM_TO_DOCUMENT,
                    {
                        "doc_id": doc_id,
                        "claim_id": cid,
                        "silo_id": silo_id,
                    },
                )
                for mention in triple.entity_mentions:
                    await self._memgraph.execute_write(
                        queries.UPSERT_ENTITY_MENTION,
                        {
                            "entity_id": mention.entity_id,
                            "silo_id": silo_id,
                            "name": mention.name,
                            "entity_type": mention.entity_type,
                            "created_at": now,
                            "claim_id": cid,
                        },
                    )
                if triple.ref_doc_id:
                    await self._memgraph.execute_write(
                        queries.ATTACH_CLAIM_REFERENCES_DOC,
                        {
                            "claim_id": cid,
                            "silo_id": silo_id,
                            "ref_doc_id": triple.ref_doc_id,
                        },
                    )
                written_ids.append(cid)
            except Exception as e:
                logger.warning(f"Failed to write claim {cid!r}: {e}", exc_info=True)
        return written_ids

    async def apply_contradicts_to_graph(
        self,
        silo_id: str,
        pairs: list[ContradictsPair],
    ) -> int:
        """Write CONTRADICTS edges between Claim pairs.

        Edge ID is deterministic (sorted fingerprints) so re-running detection
        on the same pair always MERGEs to the same edge — no duplicates.

        Returns the number of CONTRADICTS edges written.
        """
        edges_written = 0
        for pair in pairs:
            edge_id = contradicts_edge_id(pair.fingerprint_a, pair.fingerprint_b)
            try:
                await self._memgraph.execute_write(
                    queries.CREATE_CONTRADICTS_EDGE,
                    {
                        "claim_id_a": pair.claim_id_a,
                        "claim_id_b": pair.claim_id_b,
                        "silo_id": silo_id,
                        "edge_id": edge_id,
                    },
                )
                edges_written += 1
            except Exception as e:
                logger.warning(f"Failed to write CONTRADICTS edge {edge_id!r}: {e}", exc_info=True)
        return edges_written

    async def run_extraction_job(
        self, silo_id: str, job: ExtractionJob, content: str, category: str | None = None
    ) -> None:
        """Run a full extraction job: extract + apply to graph.

        Args:
            silo_id: Silo identifier (storage scope).
            job: ExtractionJob to track progress.
            content: Content text to extract from.
            category: Optional category of the source node (currently unused;
                retained for signature compatibility).
        """
        del category  # unused after tier removal

        job.status = ExtractionStatus.RUNNING
        await self._job_store.save(job)

        try:
            result, usage = await self.extract(content)
            (
                entities_created,
                relationships_created,
                entity_id_map,
            ) = await self._apply_entities_and_rels(silo_id, job.node_id, result)
            now = datetime.now(UTC)
            triples = self._synthesize_claim_triples(result, entity_id_map, job.node_id, now)

            if self._filter is not None:
                decisions = await self._filter.evaluate(
                    triples,
                    silo_id=silo_id,
                    extractor_model=getattr(self._llm, "model_name", None),
                )
                kept_triples = [
                    t for t, d in zip(triples, decisions, strict=False) if d.action == "keep"
                ]
                logger.info(
                    "extraction.filter: kept={} dropped={} silo={}",
                    len(kept_triples),
                    len(triples) - len(kept_triples),
                    silo_id,
                )
            else:
                kept_triples = triples

            claim_node_ids = await self.apply_document_claims(silo_id, job.node_id, kept_triples)
            claims_written = len(claim_node_ids)
            logger.info(
                f"Extraction job {job.id} wrote "
                f"{entities_created} entities, {relationships_created} rels, "
                f"{claims_written} claims (from {len(triples)} synthesized)"
            )
            if kept_triples and claims_written == 0:
                job.status = ExtractionStatus.FAILED
                job.error = f"All {len(kept_triples)} claim writes failed; see prior warnings"
                job.completed_at = datetime.now(UTC)
                await self._update_node_extraction_status(silo_id, job.node_id, "failed")
                logger.error(
                    "extraction_all_writes_failed",
                    job_id=job.id,
                    triples=len(kept_triples),
                )
            else:
                job.status = ExtractionStatus.COMPLETED
                job.entity_count = entities_created
                job.relationship_count = relationships_created
                job.claim_node_ids = claim_node_ids
                job.cost_usd = 0.0
                job.completed_at = now
                await self._update_node_extraction_status(silo_id, job.node_id, "done")
        except Exception as e:
            job.status = ExtractionStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.now(UTC)
            await self._update_node_extraction_status(silo_id, job.node_id, "failed")
            logger.error(f"Extraction job {job.id} failed: {e}")

        await self._job_store.save(job)

    async def _update_node_extraction_status(self, silo_id: str, node_id: str, status: str) -> None:
        """Update the extraction_status field on the source ContextNode."""
        from context_service.engine import queries as engine_queries

        logger.info(
            f"_update_node_extraction_status: silo={silo_id} node={node_id} status={status}"
        )
        try:
            rows = await self._memgraph.execute_write(
                engine_queries.UPDATE_EXTRACTION_STATUS,
                {"id": node_id, "silo_id": silo_id, "extraction_status": status},
            )
            if not rows:
                logger.warning(
                    f"UPDATE_EXTRACTION_STATUS matched 0 rows "
                    f"for silo={silo_id} node={node_id} — id/label mismatch?"
                )
        except Exception as e:
            logger.warning(
                f"Failed to update extraction_status for node {node_id}: {e}", exc_info=True
            )

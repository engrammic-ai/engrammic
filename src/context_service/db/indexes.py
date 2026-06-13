"""Memgraph index DDL for the EAG schema.

Run these on startup (idempotent — Memgraph silently skips existing indexes).
Grouped by persistence layer so the runner can apply subsets during migration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from primitives.schema import (  # noqa: E402
    AuditLabel,
    IntelligenceLabel,
    KnowledgeLabel,
    MemoryLabel,
    RegistryLabel,
    WisdomLabel,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# --- Cluster layer (not a schema enum label — bare string) ---

CLUSTER_INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX ON :Cluster(id);",
    "CREATE INDEX ON :Cluster(level);",
    "CREATE INDEX ON :Cluster(silo_id);",
    "CREATE INDEX ON :Cluster(tier);",
)

# --- Heat cursor (signals phase 2) ---

HEAT_CURSOR_INDEX_QUERIES: tuple[str, ...] = ("CREATE INDEX ON :HeatCursor(silo_id);",)

# --- Weak links (speculative signal accumulation) ---

WEAK_LINK_INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX ON :WeakLink(id);",
    "CREATE INDEX ON :WeakLink(silo_id);",
    "CREATE INDEX ON :WeakLink(speculative);",
)

# --- Memory layer ---

MEMORY_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(id);",
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(silo_id, committed);",
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(source_uri);",
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(embedded_at);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(id);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(silo_id, committed);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(source_uri);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(embedded_at);",
    f"CREATE INDEX ON :{MemoryLabel.UTTERANCE}(id);",
    f"CREATE INDEX ON :{MemoryLabel.UTTERANCE}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.EVENT}(id);",
    f"CREATE INDEX ON :{MemoryLabel.EVENT}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.EVENT}(event_type);",
    f"CREATE INDEX ON :{MemoryLabel.EVENT}(source_chain_id);",
)


# --- Knowledge layer ---

KNOWLEDGE_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(id);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(fingerprint);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id, committed);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id, content_hash);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(embedded_at);",
    # :Commitment is multi-label (:Claim:Commitment); Claim indexes already apply.
    f"CREATE INDEX ON :{KnowledgeLabel.COMMITMENT}(predicate);",
    f"CREATE INDEX ON :{KnowledgeLabel.COMMITMENT}(scope_type);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(id);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id, committed);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(valid_from);",
)


# --- Wisdom layer ---

WISDOM_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(id);",
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(silo_id);",
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(tombstoned_at);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(id);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(silo_id);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(pattern_type);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(silo_id, pattern_type);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(tombstoned_at);",
)


# --- Intelligence layer ---

INTELLIGENCE_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(silo_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(status);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(tier);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(heat_score);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(produced_by_agent_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(compacted);",
    f"CREATE INDEX ON :{IntelligenceLabel.QUERY_CONTEXT}(id);",
    f"CREATE INDEX ON :{IntelligenceLabel.QUERY_CONTEXT}(silo_id);",
)


# --- Working hypothesis (intelligence layer, session-scoped) ---

WORKING_HYPOTHESIS_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{IntelligenceLabel.WORKING_HYPOTHESIS}(id);",
    f"CREATE INDEX ON :{IntelligenceLabel.WORKING_HYPOTHESIS}(silo_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.WORKING_HYPOTHESIS}(session_id);",
)


# --- ProposedBelief (wisdom layer, awaiting validation) ---

PROPOSED_BELIEF_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{WisdomLabel.PROPOSED_BELIEF}(id);",
    f"CREATE INDEX ON :{WisdomLabel.PROPOSED_BELIEF}(silo_id);",
    f"CREATE INDEX ON :{WisdomLabel.PROPOSED_BELIEF}(status);",
)


# --- Registry layer ---

REGISTRY_INDEX_QUERIES: tuple[str, ...] = (
    # Entity is a pivot node; silo_id index mirrors the RAG-era :Entity index.
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(id);",
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(silo_id);",
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(name);",
    f"CREATE INDEX ON :{RegistryLabel.AGENT}(agent_id);",
    f"CREATE INDEX ON :{RegistryLabel.AGENT}(agent_id, silo_id);",
    f"CREATE INDEX ON :{RegistryLabel.PREDICATE}(id);",
)


# --- Audit layer ---

AUDIT_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{AuditLabel.ERASURE_EVENT}(silo_id);",
    f"CREATE INDEX ON :{AuditLabel.ERASURE_EVENT}(created_at);",
    f"CREATE INDEX ON :{AuditLabel.CALIBRATION_EVENT}(silo_id);",
    f"CREATE INDEX ON :{AuditLabel.CALIBRATION_EVENT}(created_at);",
    f"CREATE INDEX ON :{AuditLabel.BOOTSTRAP_STATE}(silo_id);",
)


# --- Meta-memory layer ---

META_MEMORY_INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX ON :MetaObservation(id);",
    "CREATE INDEX ON :MetaObservation(silo_id);",
    "CREATE INDEX ON :MetaObservation(created_at);",
    "CREATE INDEX ON :MetaObservation(agent_id);",
)


# --- Marker nodes (SAGE-internal, bare string labels) ---
#
# Contradiction and StaleCommitment are validator marker types used by the
# SAGE groundskeeper/validator to flag issues for agent engagement. They are
# not primitives enum labels — bare strings are intentional.

MARKER_INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX ON :Contradiction(id);",
    "CREATE INDEX ON :Contradiction(silo_id);",
    "CREATE INDEX ON :Contradiction(status);",
    "CREATE INDEX ON :Contradiction(detected_at);",
    "CREATE INDEX ON :Contradiction(expires_at);",
    "CREATE INDEX ON :StaleCommitment(id);",
    "CREATE INDEX ON :StaleCommitment(silo_id);",
    "CREATE INDEX ON :StaleCommitment(status);",
    "CREATE INDEX ON :StaleCommitment(detected_at);",
    "CREATE INDEX ON :StaleCommitment(expires_at);",
)


# --- Aggregate ---

ALL_INDEX_QUERIES: tuple[str, ...] = (
    *CLUSTER_INDEX_QUERIES,
    *HEAT_CURSOR_INDEX_QUERIES,
    *WEAK_LINK_INDEX_QUERIES,
    *MEMORY_INDEX_QUERIES,
    *KNOWLEDGE_INDEX_QUERIES,
    *WISDOM_INDEX_QUERIES,
    *INTELLIGENCE_INDEX_QUERIES,
    *WORKING_HYPOTHESIS_INDEX_QUERIES,
    *PROPOSED_BELIEF_INDEX_QUERIES,
    *REGISTRY_INDEX_QUERIES,
    *AUDIT_INDEX_QUERIES,
    *META_MEMORY_INDEX_QUERIES,
    *MARKER_INDEX_QUERIES,
)


async def apply_all_indexes(client: HyperGraphStore) -> None:
    """Apply every index in :data:`ALL_INDEX_QUERIES` to Memgraph.

    Each ``CREATE INDEX`` is idempotent — Memgraph silently skips indexes
    that already exist. Errors on individual statements are logged and the
    runner continues, mirroring :func:`bootstrap_custodian_schema`.
    """
    logger.info("applying_indexes", count=len(ALL_INDEX_QUERIES))
    applied = 0
    async with client.session() as session:
        for statement in ALL_INDEX_QUERIES:
            try:
                result = await session.run(statement)
                await result.consume()
                applied += 1
            except Exception as exc:
                logger.debug("index_apply_skipped", statement=statement, error=str(exc))
    logger.info("indexes_applied", applied=applied, total=len(ALL_INDEX_QUERIES))

    # Ensure text search index for grep channel (idempotent)
    await ensure_text_search_index(client)


async def ensure_text_search_index(client: HyperGraphStore) -> None:
    """Create text_search index on Node.content if not exists.

    Required by the grep channel in FusionRetriever.
    """
    async with client.session() as session:
        try:
            result = await session.run("CALL text_search.info() YIELD * RETURN *")
            records = [r async for r in result]
            existing = [r for r in records if r.get("index_name") == "node_content"]
            if existing:
                logger.debug("text_search_index_exists", index="node_content")
                return
        except Exception as exc:
            # text_search module might not be loaded
            logger.warning("text_search_info_failed", error=str(exc))
            return

        try:
            await session.run(
                'CALL text_search.create_index("node_content", "Node", "content")'
            )
            logger.info("text_search_index_created", index="node_content")
        except Exception as exc:
            logger.warning("text_search_index_create_failed", error=str(exc))

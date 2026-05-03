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


# --- Registry layer ---

REGISTRY_INDEX_QUERIES: tuple[str, ...] = (
    # Entity is a pivot node; silo_id index mirrors the RAG-era :Entity index.
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(id);",
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(silo_id);",
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(name);",
    f"CREATE INDEX ON :{RegistryLabel.AGENT}(id);",
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


# --- Aggregate ---

ALL_INDEX_QUERIES: tuple[str, ...] = (
    *CLUSTER_INDEX_QUERIES,
    *HEAT_CURSOR_INDEX_QUERIES,
    *MEMORY_INDEX_QUERIES,
    *KNOWLEDGE_INDEX_QUERIES,
    *WISDOM_INDEX_QUERIES,
    *INTELLIGENCE_INDEX_QUERIES,
    *REGISTRY_INDEX_QUERIES,
    *AUDIT_INDEX_QUERIES,
    *META_MEMORY_INDEX_QUERIES,
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

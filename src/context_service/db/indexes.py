"""Memgraph index DDL for CITE v2 schema.

Run these on startup (idempotent - Memgraph silently skips existing indexes).
Schema: 5 content nodes (Memory, Claim, Fact, Belief, Commitment), 6 edge types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from primitives.schema import (
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

# --- Memory layer (single node type) ---

MEMORY_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(id);",
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(silo_id, committed);",
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(memory_type);",
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(embedded_at);",
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(created_at);",
    # SPO indexes for supersession detection
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(silo_id, subject);",
    f"CREATE INDEX ON :{MemoryLabel.MEMORY}(silo_id, agent_id, subject);",
)


# --- Knowledge layer ---

KNOWLEDGE_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(id);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id, committed);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(evidence_uri);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(embedded_at);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(created_at);",
    # SPO indexes for supersession detection (Tier 1)
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id, subject);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id, agent_id, subject);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(id);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id, committed);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(valid_from);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(promoted_from);",
    # SPO indexes for Facts
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id, subject);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id, agent_id, subject);",
)


# --- Wisdom layer ---

WISDOM_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(id);",
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(silo_id);",
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(confidence);",
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(created_at);",
    f"CREATE INDEX ON :{WisdomLabel.COMMITMENT}(id);",
    f"CREATE INDEX ON :{WisdomLabel.COMMITMENT}(silo_id);",
    f"CREATE INDEX ON :{WisdomLabel.COMMITMENT}(source);",
    f"CREATE INDEX ON :{WisdomLabel.COMMITMENT}(stale);",
    f"CREATE INDEX ON :{WisdomLabel.COMMITMENT}(created_at);",
)


# --- Intelligence layer (passive observation - Phase 2) ---

INTELLIGENCE_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{IntelligenceLabel.EPISTEMIC_STATE}(id);",
    f"CREATE INDEX ON :{IntelligenceLabel.EPISTEMIC_STATE}(silo_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.EPISTEMIC_STATE}(session_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.EPISTEMIC_STATE}(state_type);",
    f"CREATE INDEX ON :{IntelligenceLabel.BREAKTHROUGH}(id);",
    f"CREATE INDEX ON :{IntelligenceLabel.BREAKTHROUGH}(silo_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.BREAKTHROUGH}(session_id);",
)


# --- Registry layer ---

REGISTRY_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{RegistryLabel.AGENT}(agent_id);",
    f"CREATE INDEX ON :{RegistryLabel.AGENT}(agent_id, silo_id);",
)


# --- Audit layer ---

AUDIT_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{AuditLabel.ERASURE_EVENT}(silo_id);",
    f"CREATE INDEX ON :{AuditLabel.ERASURE_EVENT}(created_at);",
    f"CREATE INDEX ON :{AuditLabel.CALIBRATION_EVENT}(silo_id);",
    f"CREATE INDEX ON :{AuditLabel.CALIBRATION_EVENT}(created_at);",
)


# --- Marker nodes (SAGE flags for agent engagement) ---

MARKER_INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX ON :ContradictionMarker(id);",
    "CREATE INDEX ON :ContradictionMarker(silo_id);",
    "CREATE INDEX ON :ContradictionMarker(status);",
    "CREATE INDEX ON :StaleCommitmentMarker(id);",
    "CREATE INDEX ON :StaleCommitmentMarker(silo_id);",
    "CREATE INDEX ON :StaleCommitmentMarker(status);",
)


# --- Aggregate ---

ALL_INDEX_QUERIES: tuple[str, ...] = (
    *MEMORY_INDEX_QUERIES,
    *KNOWLEDGE_INDEX_QUERIES,
    *WISDOM_INDEX_QUERIES,
    *INTELLIGENCE_INDEX_QUERIES,
    *REGISTRY_INDEX_QUERIES,
    *AUDIT_INDEX_QUERIES,
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
    Uses DDL syntax (CREATE TEXT INDEX) which is idempotent in Memgraph MAGE.
    """
    async with client.session() as session:
        try:
            result = await session.run("CREATE TEXT INDEX node_content ON :Node(content)")
            await result.consume()
            logger.info("text_search_index_created", index="node_content")
        except Exception as exc:
            if "already exists" in str(exc).lower():
                logger.debug("text_search_index_exists", index="node_content")
            else:
                logger.warning("text_search_index_create_failed", error=str(exc))

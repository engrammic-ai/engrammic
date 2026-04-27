"""Memgraph index DDL for the EAG schema.

Run these on startup (idempotent — Memgraph silently skips existing indexes).
Grouped by persistence layer so the runner can apply subsets during migration.
"""

from __future__ import annotations

from primitives.schema import (  # noqa: E402
    AuditLabel,
    IntelligenceLabel,
    KnowledgeLabel,
    MemoryLabel,
    RegistryLabel,
    WisdomLabel,
)

# --- Memory layer ---

MEMORY_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(id);",
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.DOCUMENT}(silo_id, committed);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(id);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.PASSAGE}(silo_id, committed);",
    f"CREATE INDEX ON :{MemoryLabel.UTTERANCE}(id);",
    f"CREATE INDEX ON :{MemoryLabel.UTTERANCE}(silo_id);",
    f"CREATE INDEX ON :{MemoryLabel.EVENT}(id);",
    f"CREATE INDEX ON :{MemoryLabel.EVENT}(silo_id);",
)


# --- Knowledge layer ---

KNOWLEDGE_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(id);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(fingerprint);",
    f"CREATE INDEX ON :{KnowledgeLabel.CLAIM}(silo_id, committed);",
    # :Commitment is multi-label (:Claim:Commitment); Claim indexes already apply.
    f"CREATE INDEX ON :{KnowledgeLabel.COMMITMENT}(predicate);",
    f"CREATE INDEX ON :{KnowledgeLabel.COMMITMENT}(scope_type);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(id);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id);",
    f"CREATE INDEX ON :{KnowledgeLabel.FACT}(silo_id, committed);",
)


# --- Wisdom layer ---

WISDOM_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(id);",
    f"CREATE INDEX ON :{WisdomLabel.BELIEF}(silo_id);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(id);",
    f"CREATE INDEX ON :{WisdomLabel.PATTERN}(silo_id);",
)


# --- Intelligence layer ---

INTELLIGENCE_INDEX_QUERIES: tuple[str, ...] = (
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(silo_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(status);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(tier);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(heat_score);",
    f"CREATE INDEX ON :{IntelligenceLabel.REASONING_CHAIN}(produced_by_agent_id);",
    f"CREATE INDEX ON :{IntelligenceLabel.QUERY_CONTEXT}(id);",
    f"CREATE INDEX ON :{IntelligenceLabel.QUERY_CONTEXT}(silo_id);",
)


# --- Registry layer ---

REGISTRY_INDEX_QUERIES: tuple[str, ...] = (
    # Entity is a pivot node; silo_id index mirrors the RAG-era :Entity index.
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(id);",
    f"CREATE INDEX ON :{RegistryLabel.ENTITY}(silo_id);",
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


# --- Aggregate ---

ALL_INDEX_QUERIES: tuple[str, ...] = (
    *MEMORY_INDEX_QUERIES,
    *KNOWLEDGE_INDEX_QUERIES,
    *WISDOM_INDEX_QUERIES,
    *INTELLIGENCE_INDEX_QUERIES,
    *REGISTRY_INDEX_QUERIES,
    *AUDIT_INDEX_QUERIES,
)

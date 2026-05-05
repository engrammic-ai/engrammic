# Hybrid Storage Strategy: Memgraph + Postgres

## Overview

Split storage between Memgraph (graph-native data) and Postgres (relational/config/audit) to reduce Memgraph heap, improve admin tooling ergonomics, and add chain projection to reduce agent context window bloat.

## Goals

- Reduce Memgraph heap by moving non-graph data to Postgres
- Add chain projection mode to reduce agent context window bloat
- Keep graph-native operations fast (traversal, provenance)
- Align with existing tag config spec (2026-05-05-auto-tagging-design.md)

## Data Placement

| Data | Storage | Rationale |
|------|---------|-----------|
| **Postgres** | | |
| User/org preferences | Postgres | LLM selection, feature flags - dashboard CRUD |
| Silo config | Postgres | Metadata, quotas, settings per silo |
| Tag config | Postgres | Per auto-tagging spec |
| ReasoningChain steps[] | Postgres | Large JSON payload, on-demand fetch |
| Events (compacted traces) | Postgres | Append-only audit logs, TTL cleanup |
| Audit events | Postgres | Erasure, calibration, bootstrap state |
| **Memgraph** | | |
| ReasoningChain node | Memgraph | Summary fields + edges (SPAWNED_BY, PART_OF_SESSION) |
| MetaObservation | Memgraph | ABOUT edges for traversal |
| Belief, Fact, Claim, Entity | Memgraph | Graph-native: provenance chains, synthesis edges |
| Cluster, Document, Passage | Memgraph | Traversal, MEMBER_OF, EXTRACTED_FROM |

## Postgres Schema

```sql
-- User/org preferences
CREATE TABLE org_preferences (
    org_id UUID PRIMARY KEY,
    default_llm VARCHAR(64) NOT NULL DEFAULT 'claude-haiku-4-5-20251001',
    embedding_model VARCHAR(64) NOT NULL DEFAULT 'jina-embeddings-v3',
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Silo config
CREATE TABLE silo_config (
    silo_id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES org_preferences(org_id),
    name VARCHAR(255) NOT NULL,
    quotas JSONB NOT NULL DEFAULT '{}',
    feature_flags JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ReasoningChain steps (hot payload)
CREATE TABLE reasoning_chain_steps (
    chain_id UUID PRIMARY KEY,
    silo_id UUID NOT NULL REFERENCES silo_config(silo_id),
    steps JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_chain_steps_silo ON reasoning_chain_steps(silo_id);

-- Upsert pattern for retries:
-- INSERT INTO reasoning_chain_steps (...) VALUES (...)
-- ON CONFLICT (chain_id) DO UPDATE SET steps = EXCLUDED.steps, updated_at = NOW();

-- Events (compacted traces)
CREATE TABLE events (
    id UUID PRIMARY KEY,
    silo_id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    source_chain_id UUID,
    content TEXT NOT NULL,
    agent_id VARCHAR(255),
    step_count INT,
    outcome VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ  -- NULL = no expiry; cleanup job deletes WHERE expires_at < NOW()
);
CREATE INDEX idx_events_silo_type ON events(silo_id, event_type, created_at DESC);
CREATE INDEX idx_events_expiry ON events(expires_at) WHERE expires_at IS NOT NULL;

-- Audit events
CREATE TABLE audit_events (
    id UUID PRIMARY KEY,
    silo_id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(255) NOT NULL,      -- who triggered (agent_id or user_id)
    actor_type VARCHAR(32) NOT NULL,     -- "agent" | "user" | "system"
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_silo_time ON audit_events(silo_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_events(actor_id, created_at DESC);
```

Tag config tables defined in auto-tagging spec - not duplicated here.

## ReasoningChain Split

### Memgraph Node (Summary Only)

```cypher
(:ReasoningChain {
  id: STRING,
  silo_id: STRING,
  tier: "hot" | "cold",
  status: "draft" | "published" | "superseded" | "retracted",
  source: "agent_explicit" | "session_trace_inferred",
  produced_by_model: STRING,
  produced_by_agent_id: STRING,
  query_context_hash: STRING | NULL,
  created_at: TIMESTAMP,
  valid_from: TIMESTAMP,
  valid_to: TIMESTAMP | NULL,
  
  // Summary fields (computed on write, stored)
  step_count: INT,
  first_step: STRING,    // JSON-serialized {premise_refs, operation, conclusion, confidence}
  final_step: STRING,    // JSON-serialized (Memgraph has no native JSON type)
  outcome: "success" | "failure" | "inconclusive" | NULL,
  all_premise_refs: LIST  // flattened from all steps
})
```

### Postgres (Full Payload)

```
reasoning_chain_steps.steps = [
  {step_index, premise_refs, operation, conclusion, confidence},
  ...
]
```

### Write Path (Saga Pattern)

1. Agent calls `context_store(layer="intelligence", steps=[...])`
2. Compute summary: `step_count`, `first_step`, `final_step`, `outcome`, flatten `all_premise_refs`
3. **Postgres first**: upsert steps JSON (ON CONFLICT UPDATE)
4. **Memgraph second**: upsert node with summary fields + create edges
5. **On Memgraph failure**: delete Postgres row (compensating transaction)

Postgres-first ordering ensures we never have a Memgraph summary pointing to missing steps. Retry-safe via ON CONFLICT.

### Read Path

- Default: return Memgraph node (summary only)
- `include_steps=true`: join from Postgres by chain_id

## API Changes

### context_recall

New parameter:

```python
context_recall(
    node_ids: list[str],
    include_steps: bool = False,  # default False to save context window
)
```

### Response Shapes

**Summary (default):**
```json
{
  "node_id": "chain_123",
  "layer": "intelligence",
  "step_count": 7,
  "first_step": {"operation": "retrieve", "conclusion": "Found 3 relevant facts"},
  "final_step": {"operation": "synthesize", "conclusion": "User prefers X because Y"},
  "outcome": "success",
  "all_premise_refs": ["fact_1", "fact_2", "claim_5"]
}
```

**Full (include_steps=true):**
```json
{
  "node_id": "chain_123",
  "layer": "intelligence",
  "step_count": 7,
  "first_step": {"operation": "retrieve", "conclusion": "Found 3 relevant facts"},
  "final_step": {"operation": "synthesize", "conclusion": "User prefers X because Y"},
  "outcome": "success",
  "all_premise_refs": ["fact_1", "fact_2", "claim_5"],
  "steps": [
    {"step_index": 0, "premise_refs": [...], "operation": "...", "conclusion": "...", "confidence": 0.9},
    ...
  ]
}
```

**Scope:** `include_steps` only applies to node_id fetch mode (depth=0). For semantic search and graph traversal modes, ReasoningChain nodes return summary only; agents must follow up with explicit node_id fetch if full steps needed.

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| `context_store` (intelligence) | < 200ms p95 | Postgres + Memgraph write (saga) |
| `context_recall` (summary) | < 20ms cached, < 100ms uncached | Memgraph only |
| `context_recall` (include_steps) | < 120ms | Memgraph + Postgres PK lookup |
| Event insert | < 50ms | Postgres append |
| Config CRUD | < 30ms | Postgres indexed |

## Implementation Notes

### Existing Infrastructure

- `src/context_service/db/postgres.py` - SQLAlchemy 2.0 async session management already wired
- `PostgresConfig` in settings with DSN
- `Base` declarative base ready for models

### New Files Required

- `src/context_service/models/postgres/` - SQLAlchemy models for tables above
- `src/context_service/engine/postgres_store.py` - repository layer
- Migration files via Alembic

### Dependencies

- References auto-tagging spec for tag config tables
- Compaction pipeline (`engine/compaction.py`) needs update to write Events to Postgres

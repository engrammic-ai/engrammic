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
| ReasoningChain node | Memgraph | Summary fields + edges (SPAWNED_BY, PART_OF_SESSION, CONCLUDES) |
| Conclusion node | Memgraph | Aggregates reasoning chains, consolidation target |
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
    silo_id UUID NOT NULL REFERENCES silo_config(silo_id),
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
    silo_id UUID NOT NULL REFERENCES silo_config(silo_id),
    event_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(255) NOT NULL,      -- who triggered (agent_id or user_id)
    actor_type VARCHAR(32) NOT NULL,     -- "agent" | "user" | "system"
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_silo_time ON audit_events(silo_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_events(actor_id, created_at DESC);

-- Dead-letter for failed saga compensations
CREATE TABLE orphaned_chains (
    chain_id UUID PRIMARY KEY,
    silo_id UUID NOT NULL,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_count INT NOT NULL DEFAULT 0,
    last_error TEXT
);
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
5. **On Memgraph failure**: 
   - Attempt compensating delete of Postgres row (3 retries, exponential backoff)
   - If delete fails after retries, log to `orphaned_chains` dead-letter table for async cleanup

Postgres-first ordering ensures we never have a Memgraph summary pointing to missing steps. Retry-safe via ON CONFLICT.

**Reconciliation GC (periodic):** Dagster job runs every 15 minutes:
- Scan `reasoning_chain_steps` for rows where `chain_id` has no matching Memgraph node
- Delete orphaned rows older than 5 minutes (grace period for in-flight writes)
- Also processes `orphaned_chains` dead-letter table

### Read Path

- Default: return Memgraph node (summary only)
- `include_steps=true`: join from Postgres by chain_id
- If Memgraph node missing, treat as not-found (don't fetch orphaned Postgres steps)

## Conclusion Node (Multi-Writer Pattern)

Multiple agents may reason about the same query in parallel, producing independent ReasoningChains that converge on similar conclusions. Rather than contending on a single chain, each agent writes their own chain and Conclusion, with async consolidation.

### Conclusion Schema (Memgraph)

```cypher
(:Conclusion {
  id: STRING,
  silo_id: STRING,
  query_context_hash: STRING,
  content: STRING,
  confidence: FLOAT,
  status: "active" | "consolidated",
  created_by_agent_id: STRING,
  created_at: TIMESTAMP,
  valid_from: TIMESTAMP,
  valid_to: TIMESTAMP | NULL  // for time-travel queries
})
```

### Edges

```
(:ReasoningChain)-[:CONCLUDES]->(:Conclusion)  // chain reaches this conclusion
(:Conclusion)-[:CONSOLIDATES]->(:Conclusion)   // canonical consolidates originals
```

### Write Path (No Contention)

1. Agent writes ReasoningChain (single-writer, no conflict)
2. Agent writes Conclusion with `query_context_hash`
3. Agent creates `CONCLUDES` edge from chain to conclusion
4. No locks required on hot path

### Consolidation (Custodian)

Runs as a separate pass in the custodian worker loop:

**Grouping key:** `(silo_id, query_context_hash)` - never consolidate across silos.

**Trigger (threshold):** When 2+ Conclusions share the same grouping key
- Acquire Redis lock: `consolidation:{silo_id}:{query_context_hash}` (10s TTL)
- Skip if any originals already have `status: consolidated` (idempotency guard)
- Create canonical Conclusion with merged confidence (agreement boost)
- Create `CONSOLIDATES` edges from canonical to originals
- Mark originals `status: consolidated`
- Release lock

**Fallback (periodic):** Every 5-10 minutes, sweep for unconsolidated Conclusions
- Cluster by embedding similarity within silo (cosine threshold > 0.85)
- Same consolidation logic with lock per cluster

**Failure handling:** If crash occurs between canonical creation and marking originals:
- Periodic sweep detects originals with `status: active` that have incoming `CONSOLIDATES` edge
- Marks them `status: consolidated` (idempotent repair)

**Provenance:** Original Conclusions are preserved, not deleted. Full reasoning paths remain traversable.

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

**Scope:** `include_steps` only applies to node_id fetch mode (depth=0). For semantic search and graph traversal modes, the parameter is silently ignored and ReasoningChain nodes return summary only. Agents must follow up with explicit node_id fetch if full steps needed. This is intentional: bulk search/traversal results should stay lightweight.

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| `context_store` (intelligence) | < 200ms p95 | Postgres + Memgraph write (saga) |
| `context_recall` (summary) | < 20ms cached, < 100ms uncached | Memgraph only |
| `context_recall` (include_steps) | < 120ms | Memgraph + Postgres PK lookup |
| Event insert | < 50ms | Postgres append |
| Config CRUD | < 30ms | Postgres indexed |

## Race Condition Mitigations

| Issue | Mitigation |
|-------|------------|
| Saga TOCTOU (reader sees Postgres steps for missing Memgraph node) | Read path checks Memgraph first; if node missing, don't fetch Postgres steps |
| Compensating delete fails | Retry 3x with backoff, then dead-letter to `orphaned_chains`; reconciliation GC cleans up |
| Lost update on steps (concurrent upserts) | Chains are single-writer; multi-writer scenarios use separate chains + Conclusion consolidation |
| Summary/payload split (Postgres updated, Memgraph stale) | Saga always writes both or neither; no partial retry path |
| Event expiry phantom read | Event reads use explicit transaction via `get_session()` context manager |
| Consolidation race (two workers create canonicals) | Redis lock per `(silo_id, query_context_hash)` with idempotency guard |
| Consolidation crash (canonical created, originals not marked) | Periodic sweep repairs: detects active originals with incoming CONSOLIDATES edge |
| Cross-silo hash collision | Grouping key includes `silo_id`; never consolidate across silos |

### System-Level Fixes (Separate from This Spec)

These pre-existing issues should be addressed independently:

- `db/postgres.py:67-68`: Add `asyncio.Lock` around lazy init of `_session_factory`
- `embeddings/splade.py:56-57`: Fix lock creation race with class-level lock
- `engine/memgraph_store.py:333-341`: Document non-atomic version check limitation
- `db/postgres.py:44`: Increase pool size or add `pool_timeout` configuration

## Implementation Notes

### Existing Infrastructure

- `src/context_service/db/postgres.py` - SQLAlchemy 2.0 async session management already wired
- `PostgresConfig` in settings with DSN
- `Base` declarative base ready for models

### New Files Required

- `src/context_service/models/postgres/` - SQLAlchemy models for tables above
- `src/context_service/engine/postgres_store.py` - repository layer
- `src/context_service/models/inference.py` - add Conclusion model
- `src/context_service/db/queries.py` - add Conclusion Cypher queries
- `src/context_service/custodian/consolidation.py` - Conclusion consolidation logic
- Migration files via Alembic

### Dependencies

- References auto-tagging spec for tag config tables
- Compaction pipeline (`engine/compaction.py`) needs update to write Events to Postgres
- Custodian worker loop needs consolidation pass after validation pass

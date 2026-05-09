# Architecture Review: Technical Debt and Optimization Opportunities

**Date:** 2026-05-09  
**Status:** Decisions complete

## Summary of Decisions

| Topic | Decision |
|-------|----------|
| Hypergraph | Wire up via Option B (structured `derivation` param, validated IDs), stay Memgraph, **HARD LOCK on TypeDB 3 migration** |
| Consistency | Full saga treatment (retry + dead-letter), scale incrementally |
| Performance | Staged - observability first, then quick wins |
| Custodian | Split into 4 identities (Custodian, Synthesizer, Groundskeeper, Validator) using pydantic-ai + Dagster. See `context/specs/glossary.md` for definitions. |
| Isolation | Not now, document `scope` field for future |
| Escape hatches | Auto-scope from auth context, add admin variants |
| Observability | Migrate from Jaeger to SigNoz on strata-finance box (19GB RAM sufficient) |
| Input validation | Validate all agent-provided IDs exist, add size limits on metadata/tags |
| Background tasks | Always explicit `silo_id` param, never ambient context |
| Embedding provider | Fail-fast if down, track model in Postgres `SiloEmbeddingConfig`, re-embed on model change |

---

## 1. Hypergraph Abstraction

### Current State

The `HyperEdge` model exists with proper bipartite encoding (HyperEdge node + PARTICIPANT edges), but the feature is incomplete:

- `upsert_hyperedge` in `engine/protocols.py` is never called by any service or MCP tool
- `SubGraph.hyper_edges` field is never populated by `get_neighborhood`
- `context_link` MCP tool only creates `BinaryEdge`s

The naming is technically accurate - bipartite encoding is the standard approach for N-ary relationships in property graphs (Memgraph cannot do native hyperedges).

### Options

| Option | Effort | Tradeoff |
|--------|--------|----------|
| **Wire it up** - Add `participants` param to `context_link` for 3+ nodes | Medium | Enables richer knowledge representation (HyperGraphRAG research shows 5x more expressive) |
| **Remove it** - Delete dead code | Low | Reduces confusion, loses future capability |
| **Defer** - Keep as-is | None | Dead code remains, no harm |

### Decision

**Wire it up via Option B** - implicit hyperedge creation from `context_store` when storing reasoning structures. Agents express intent ("I concluded X from Y and Z"), system captures structure. Agents shouldn't think in graph topology.

**Stay on Memgraph** with explicit `DerivationStep` reification pattern, but design abstractions to be storage-agnostic for future TypeDB 3 migration.

### TypeDB 3 Migration Path

> **HARD LOCK: DO NOT MIGRATE TO TYPEDB 3 YET.**
> TypeDB 3 is promising but ecosystem is immature (Python docs lag, small community, limited production case studies). 
> Revisit Q4 2026 at earliest. Any migration proposal requires explicit founder approval.

TypeDB 3 (Rust rewrite, 2025) is the only production DB with native N-ary relations. To enable future swap:

1. **Abstract at protocol level** - `HyperGraphStore` protocol already exists; ensure all hyperedge ops go through it
2. **Avoid Cypher in business logic** - use protocol methods, not raw queries
3. **Model DerivationStep as a first-class concept** - not just a graph pattern, but a domain model that could map to TypeDB's polymorphic relations
4. **Keep TypeQL in mind** - TypeDB's query language has type inference; structure data so it could leverage this

When to consider migration:
- Graph query complexity becomes untenable
- Need native type inference for reasoning
- TypeDB 3 ecosystem matures (better Python docs, more community adoption)

### Hyperedge Unbounded Growth Mitigation

| Strategy | When | Owner |
|----------|------|-------|
| Retention by layer | Continuous | Retention service (existing) |
| Hyperedge compaction | Periodic batch | Groundskeeper (new) |
| Deduplication (content-addressed) | Write time | context_store |
| Summarization | Threshold-based | Synthesizer (new) |

### Files

- `src/context_service/engine/models.py:111` - HyperEdge model
- `src/context_service/engine/protocols.py` - upsert_hyperedge protocol
- `src/context_service/stores/memgraph.py` - bipartite storage impl
- `src/context_service/mcp/tools/context_link.py` - only creates BinaryEdge (to be extended)

---

## 2. Multi-Store Consistency

### Current State

| Write Path | Stores | Pattern | Gap |
|------------|--------|---------|-----|
| `ContextService.store()` | Memgraph + Qdrant | Ad-hoc saga | Single compensation attempt, no dead-letter, no retry |
| `ChainSagaWriter` | Postgres + Memgraph | Named saga with 3x retry | Missing reconciliation job for `orphaned_chains` table |

### Recommended Pattern: Tiered Saga + Reconciliation

**Do not adopt:** 2PC (stores don't support XA), Outbox (overkill), Event sourcing (massive rewrite)

### Action Items

| Priority | Action | Effort |
|----------|--------|--------|
| 1 | Add 3x retry with exponential backoff to `ContextService.store()` Qdrant upsert before compensation | Low |
| 2 | Add `orphaned_vectors` dead-letter table (or add `resource_type` column to existing `orphaned_chains`) | Low |
| 3 | Add Dagster scheduled job to reconcile orphaned records by replaying failed writes | Medium |
| 4 | (Optional) Periodic consistency audit job: spot-check N random Memgraph nodes have Qdrant vectors | Low |

### Files

- `src/context_service/services/context.py:232-336` - ContextService.store() saga
- `src/context_service/engine/chain_saga.py` - ChainSagaWriter (good pattern to follow)
- `src/context_service/pipelines/` - location for reconciliation jobs

### Tolerable Inconsistency

For a knowledge/memory system, brief windows where a node exists in Memgraph but lacks a Qdrant vector (or vice versa) are acceptable. Semantic search returns no result for a node that exists in graph - degraded but not wrong. Reconciliation bounds the window.

### Saga Tradeoffs at Scale

**Latency impact (full saga):**

| Path | Current | Full Saga |
|------|---------|-----------|
| p50 | ~150ms | ~150ms (no change) |
| p95 | ~300ms | ~350ms (+retry on transient) |
| p99 (failure) | unbounded | ~2s (capped by retry budget) |

Saga overhead only shows up on failures - happy path is identical.

**Single tenant growth:** Saga overhead scales with *failure rate*, not *data size*. If stores are healthy, no extra cost.

**Multi-tenant (1000s):**

| Concern | Mitigation |
|---------|------------|
| Shared dead-letter contention | `silo_id` column, partition by tenant |
| Reconciliation job bottleneck | Shard by silo_id, parallel workers |
| Retry thundering herd | Per-tenant rate limiting, jittered backoff |
| Connection pool exhaustion | Separate pool for retries |

**Correlated failure risk:** If Qdrant goes down, all tenants hit retries simultaneously.

| Scale | Approach |
|-------|----------|
| Now (< 100 tenants) | Add retry + dead-letter. Simple, handles transient failures. |
| Growth (100-1000) | Add circuit breaker per tenant. Monitor dead-letter growth. |
| Scale (1000+) | Shard reconciliation, bulkheads, consider async-first writes |

**Decision:** Implement full saga treatment. Cost is minimal on happy path, prevents silent data loss. Scale concerns are solvable incrementally.

### Embedding Provider Handling

**Requirement:** Embedding provider must be up for writes. Fail-fast if unavailable.

**Model tracking:** Store in Postgres as source of truth:

```python
class SiloEmbeddingConfig(Base):
    __tablename__ = "silo_embedding_config"
    
    silo_id: Mapped[UUID] = mapped_column(primary_key=True)
    embedding_model: Mapped[str]  # e.g., "openai/text-embedding-3-small"
    embedding_dimensions: Mapped[int]
    updated_at: Mapped[datetime]
```

**On model change:** Dagster job re-embeds all nodes in silo, updates Qdrant collection.

---

## 3. Performance Optimizations

### Targets (from CLAUDE.md)

| Operation | Target | Current Risk |
|-----------|--------|--------------|
| `context_recall` (cached) | < 20ms | OK with warm cache |
| `context_recall` (search) | < 250ms | Embedding generation is bottleneck |
| `context_recall` (graph depth 2) | < 500ms | Variable-length Cypher is slow |
| `context_store` | < 300ms p95 | Inline embedding + cache write adds latency |
| `context_link` | < 100ms | OK |

### High-Impact Actions

| # | Change | Effort | Expected Gain |
|---|--------|--------|---------------|
| 1 | **Replace NEIGHBORHOOD variable-length Cypher with Memgraph BFS** | Low | Graph depth-2: ~500ms to ~100-150ms |
| 2 | **Parallel Redis lookups in `embed()`** via `asyncio.gather` | Low | Eliminates N sequential round-trips |
| 3 | **Fire-and-forget `EmbeddingCache.set`** | Trivial | Removes 1 Redis RTT from store path |
| 4 | **Add indexes on `(silo_id, committed)`** | Low | Reduces graph query planning cost |

### Medium-Effort Actions

| # | Change | Notes |
|---|--------|-------|
| 5 | Silo eager warming on creation | Background task to pre-populate node cache for new silos |
| 6 | Intermediate LIMIT in entity-graph query | Prevents join explosion in dense graphs |
| 7 | Background embedding on store write | Decouple write latency from embedding API call |

### Code Changes

**`embeddings/litellm_embeddings.py` - Parallel cache + fire-and-forget:**
```python
# Before: sequential cache lookup
for i, text in enumerate(texts):
    cached = await self._embedding_cache.get(text, task)
    ...

# After: parallel cache lookup
cached_results = await asyncio.gather(
    *(self._embedding_cache.get(text, task) for text in texts)
)

# Before: await cache set
await self._embedding_cache.set(text, task, embedding)

# After: fire-and-forget (failure already swallowed)
asyncio.create_task(self._embedding_cache.set(text, task, embedding))
```

**`engine/queries.py` - BFS rewrite for NEIGHBORHOOD:**
```cypher
-- Current (slow for depth > 2)
MATCH path = (start)-[:DERIVED_FROM|EXTRACTED_FROM|...*1..%d]-(other)

-- Recommended (Memgraph built-in BFS with inline filter)
MATCH (start)-[r *BFS..%d (r, n | n.silo_id = $silo_id AND n.committed = true)]-(other)
```

**Index creation (schema init):**
```cypher
CREATE INDEX ON :Passage(silo_id);
CREATE INDEX ON :Claim(silo_id);
CREATE INDEX ON :Entity(silo_id);
CREATE INDEX ON :Passage(silo_id, committed);
```

### Files

- `src/context_service/embeddings/litellm_embeddings.py` - parallel gather + fire-and-forget
- `src/context_service/engine/queries.py` - BFS rewrite, intermediate LIMIT
- `src/context_service/services/silo.py` - eager cache warming hook
- `src/context_service/db/indexes.py` or schema init - index creation

---

## 4. Tenant Isolation

### Current Model

| Level | Enforcement | Risk |
|-------|-------------|------|
| **Org to Silo** | Hard - `silo_id` required on every protocol method | Low |
| **Within Silo** | Soft - `session_id`, `agent_id`, `doc_id` are filters, not boundaries | Medium (any agent in silo sees all data) |

### Multi-Silo per Org

Already supported structurally via `ScopeContext(org_id, silo_id)`. The `derive_silo_id()` function is just MVP convenience for 1:1 mapping.

### Cross-Tenant Leak Vectors to Monitor

1. **Qdrant collections** - Named `ctx_{silo_id}`. Risk if collection creation fails silently and falls back to shared collection.
2. **Memgraph Cypher escape hatches** - `execute_query`/`execute_write` bypass protocol enforcement. Any query missing `WHERE silo_id = $silo_id` is a leak.
3. **Redis cache keys** - Verify all keys are prefixed with silo_id.
4. **Error messages** - Stack traces or error details could leak node IDs from other silos.

### Within-Silo Scoping

Current model doesn't enforce agent-to-agent isolation within a silo - soft filtering via `session_id`, `agent_id`, `doc_id` only.

**Decision:** Not needed now. Agents in same silo are cooperating. If hard isolation needed, create separate silos.

**Future option (if demand arises):** Add `scope` field to nodes:
- Values: `shared` (default), `private:{agent_id}`, `session:{session_id}`
- Filter at query time based on caller identity
- Don't build until there's concrete demand

---

## 5. Connection Pool Overhead

### Current State

4 backing stores (Memgraph, Qdrant, Redis, Postgres), each with its own async connection pool.

### Risk

At scale with many silos: memory pressure from socket buffers, driver state. Each pool has N connections x M silos potential.

### Mitigation

- Monitor pool sizes via metrics
- Consider shared pool managers if memory becomes an issue
- Current scale is fine; flag for future

---

## 6. Cypher Escape Hatches

### Current State

`HyperGraphStore` protocol includes `execute_query` and `execute_write` methods that bypass domain-level abstractions.

### Risk

- Queries that bypass silo_id enforcement
- Protocol abstraction leaks if these proliferate

### Decision: Auto-scope from Auth Context

Since silo_id is inferred from auth, escape hatches should auto-inject it:

```python
async def execute_query(self, cypher: str, params: dict) -> list[dict]:
    ctx = get_current_scope()  # from request/auth context
    params = {**params, "silo_id": str(ctx.silo_id)}
    # optionally: warn if cypher doesn't reference silo_id
    ...
```

**For admin/cross-silo operations:** Add separate `execute_query_admin` that:
- Requires explicit silo_id or allows bypass
- Only callable from admin paths
- Auditable

### Action Items

1. Modify `execute_query`/`execute_write` to auto-inject silo_id from auth context
2. Add `execute_query_admin`/`execute_write_admin` for privileged cross-silo ops
3. Add warning/log if query doesn't reference `$silo_id` param
4. Audit existing usages and migrate to scoped versions

---

---

## 7. Custodian Identity Split

### Current State

The Custodian handles:
- Contradiction detection
- Weak synthesis (ProposedBelief generation)
- Supersession tracking

With hyperedges and compaction, it would also need:
- Hyperedge compaction/merging
- Reasoning structure validation
- Summarization

This is too much for one identity with one cadence.

### Proposed Split: Four Identities

| Identity | Responsibility | EAG Transitions | Trigger | Latency |
|----------|----------------|-----------------|---------|---------|
| **Custodian** | Contradiction detection, supersession | T2 | Per-write (async) | Low (~100ms) |
| **Synthesizer** | Weak synthesis, ProposedBelief creation, revision | T3, T4, T10 | Periodic / threshold | Medium |
| **Groundskeeper** | Memory lifecycle, decay enforcement, dedup | T6, T9 | Scheduled batch (Dagster) | High (batch) |
| **Validator** | Reasoning structure validation, premise consistency | T13 | On crystallize | Low |

See `context/specs/glossary.md` for detailed definitions.

### Rationale

- **Cadence separation**: Real-time contradiction detection vs batch compaction have different SLAs
- **Prompt simplicity**: Each identity has focused instructions, no context-switching
- **Failure isolation**: Groundskeeper failure doesn't block writes
- **Resource allocation**: Batch jobs can use cheaper compute, different rate limits

### Implementation Notes

Use existing stack - no new frameworks needed.

| Layer | Tool | Notes |
|-------|------|-------|
| LLM calls | pydantic-ai | Each identity = typed `Agent` instance |
| Scheduling | Dagster | sensors, schedules, jobs per cadence |
| Observability | structlog + OTEL | `identity=` tag for filtering |

| Identity | Dagster Primitive | Trigger |
|----------|-------------------|---------|
| Custodian | `sensor` on write events | Per-write, reactive |
| Synthesizer | `ScheduleDefinition` + threshold `sensor` | Periodic |
| Groundskeeper | Partitioned `job` | Batch |
| Validator | `op` called from API/MCP | On-demand |

**Skip:** CrewAI, AutoGen, LangGraph - overkill for single-purpose scheduled calls.

**Future consideration:** Temporal for Groundskeeper if exactly-once durability becomes a hard requirement at scale.

### Files to Create/Modify

- `src/context_service/custodian/` - split into submodules per identity
- `src/context_service/custodian/identities/` - pydantic-ai Agent definitions
- `src/context_service/pipelines/compactor.py` - new Dagster job
- `src/context_service/pipelines/synthesizer.py` - new Dagster schedule
- `src/context_service/mcp/tools/context_crystallize.py` - add Validator hook

---

## 8. Input Validation (Hallucination Prevention)

### Problem

Agents can pass hallucinated IDs or unbounded data that we trust without validation.

### Critical Issues

| Issue | Location | Fix |
|-------|----------|-----|
| **`context_link` silent failure** | `context_link.py`, `services/context.py:1512` | Check node existence before write, return error if `from_node` or `to_node` missing |
| **`referenced_chain_ids` unvalidated** | `context_admin.py:125-137` | Batch existence check before writing chain reference edges |
| **Hyperedge `derivation.premises`** | (new, from Option B) | Validate all premise IDs exist in silo before creating hyperedge |

### Medium Issues

| Issue | Location | Fix |
|-------|----------|-----|
| **`metadata` dict unvalidated** | `context_store.py` | Add size cap (50 keys, 10KB serialized), denylist reserved keys (`source`, `author`, `created_by`) |
| **`tags` unbounded** | `context_store.py` | Per-tag limit (128 chars), list limit (50 tags) |
| **`source_tier` partial validation** | `context_store.py:146` | Extend `_VALID_SOURCE_TIERS` check to all layers, not just knowledge |

### What's Already Secure

- `silo_id` derived from auth, can't be spoofed
- `relationship` type enum-validated at MCP and service layers
- Evidence `node:<uuid>` refs existence-checked

### Action Items

1. Add existence check to `link()` service method - fail if nodes don't exist
2. Add batch existence check for `referenced_chain_ids`
3. Add validation for `derivation.premises` in context_store
4. Add metadata size cap and reserved key denylist
5. Add tags length limits
6. Extend source_tier validation to all layers

---

## 9. Observability Overhaul

### Current State

Jaeger all-in-one (v1.76.0) - traces only, dated UI, no metrics correlation.

### Decision: Migrate to SigNoz

**Why SigNoz:**
- Traces + metrics + logs in one UI with correlation
- Drop-in OTEL replacement (change endpoint only)
- pydantic-ai spans show up automatically
- Docker Compose deploy

**Deployment:** Host on strata-finance box (needs 4-8GB RAM for ClickHouse)

**Migration steps:**
1. Clone SigNoz repo, run install script on strata-finance
2. Update `OTEL_EXPORTER_OTLP_ENDPOINT` to point at SigNoz (port 4317)
3. Remove Jaeger from docker-compose
4. Configure retention in SigNoz UI

**Env vars:**
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://<signoz-host>:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_INSECURE=true
```

### Debug Trace Gating

Add config to control verbose spans:

```python
# config/settings.py
trace_debug_mode: bool = False
trace_cypher_queries: bool = False
trace_per_node: bool = False
```

Only emit verbose spans when explicitly enabled. Keeps prod traces lean.

### What to Trace

| Category | Trace | Why |
|----------|-------|-----|
| Latency | `context_store`, `context_recall` e2e | SLA targets |
| Breakdown | Memgraph vs Qdrant vs Embedding time | Find bottleneck |
| LLM | Custodian/Synthesizer calls, tokens | Cost attribution |
| Saga | Retry counts, compensation, dead-letter | Health signal |
| Cache | Hit/miss rates by silo | Tuning |

**Don't trace:** Every Cypher query, per-node spans, tight loop internals (unless debug mode).

---

## Discussion Topics

1. ~~**Hypergraph:** Wire up now, or wait for concrete use case?~~ **Decided: Wire up via Option B (structured schema, validated IDs), stay Memgraph, prep for TypeDB 3 (HARD LOCK on migration)**
2. ~~**Consistency:** Implement retry + dead-letter, or accept current risk level?~~ **Decided: Full saga treatment, scale incrementally**
3. ~~**Performance:** Which optimizations to prioritize for next sprint?~~ **Decided: Staged - observability first (SigNoz), then quick wins (1-4)**
4. ~~**Isolation:** Is within-silo agent isolation needed?~~ **Decided: Not now, document `scope` field for future**
5. ~~**Escape hatches:** Audit and restrict, or leave as-is?~~ **Decided: Auto-scope from auth context, add admin variants**
6. ~~**Custodian split:** Agree on the 4-identity model?~~ **Decided: 4 identities, use existing stack (pydantic-ai + Dagster). Trigger mechanisms and cost optimization require separate design session.**

## Open Items from Adversarial Review

| Issue | Status | Resolution |
|-------|--------|------------|
| Hyperedge extraction mechanism | Resolved | Structured schema with validated IDs |
| Custodian reactivity vs cost | Deferred | Needs dedicated design session |
| Auth context propagation | Resolved | Background tasks always receive explicit `silo_id` param, never rely on ambient context |
| Fire-and-forget error logging | Resolved | Add `task.add_done_callback()` to log/meter failures |
| SigNoz production path | Resolved | strata-finance has 19GB RAM, sufficient for current scale |
| Qdrant collection fail-fast | Resolved | Fail-fast on collection creation, never fallback to shared collection |
| Groundskeeper idempotency | Resolved | Use upsert-based operations (Cypher MERGE), reprocessing same inputs = same result |
| Embedding API circuit-breaker | Resolved | Fail-fast (Option B), require embedding provider up. Track `embedding_model` in Postgres `SiloEmbeddingConfig`, re-embed via Dagster job on model change |
| TypeDB review trigger | Resolved | Review if: median graph query >300ms for 7 days, OR escape hatch usage >20/day, OR >3 custom Cypher patterns for hyperedges |
| Validator timeout | Resolved | 5s soft timeout, crystallize proceeds with `validation_skipped=True` flag |

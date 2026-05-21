# Data Lifecycle Management

**Date:** 2026-05-20
**Status:** Complete - all issues resolved, ready for implementation planning

---

## Summary

Engrammic is currently append-only with limited pruning. Four features needed:

1. **`forget` MCP tool** - Agent-driven soft-delete with cancel window
2. **GDPR hard-delete** - Right-to-erasure compliance with cascading
3. **Supersession chain pruning** - Bounded chain lengths
4. **Retention policy enhancements** - Per-silo overrides, chain length config

All share a common pre-requisite: **three-store consistency** (Memgraph + Qdrant + Postgres).

---

## Critical Bug (Pre-Requisite)

**`HARD_DELETE_NODE` only deletes from Memgraph.** Qdrant vectors persist, causing:
- Deleted content surfaces in `recall` searches
- Storage leak in Qdrant
- GDPR non-compliance (vectors derived from PII are PII)

**Fix:** Coordinate deletion across all three stores with correct ordering:
1. **Memgraph first** (authoritative) - must succeed or abort entirely
2. **Qdrant second** - idempotent, retry 3x, failure → dead-letter queue for reconciliation
3. **Postgres third** - idempotent, retry 3x, failure acceptable

Key: Don't block GDPR response for vector cleanup. Orphaned vectors cleaned by nightly reconciliation.

Additionally: **tombstoned nodes still appear in recall** because Qdrant searches don't filter on `tombstoned_at`. Must add payload filter before `forget` ships.

---

## Feature 1: `forget` MCP Tool

### Behavior

```
forget(node_id, cancel=False, reason=None)
  -> { status, node_id, downstream_references, tombstoned_at | cancelled_at }
```

- **cancel=False:** Tombstone node, return count of downstream references (don't auto-cascade)
- **cancel=True:** Reverse tombstone if within grace period; return 410 Gone if already hard-deleted

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Profile | `standard` | All agents need retraction capability |
| Cascade | No | Agent decides; downstream_references count informs |
| Cancel window | Per-silo config (default 1h) | Shorter than grace period for quick mistakes |
| vs SUPERSEDES | Distinct | `forget` = deletion intent; SUPERSEDES = version history |

### Agent Heuristic

> Use `forget` when content is **wrong or shouldn't exist**.
> Use `link(SUPERSEDES)` when content was **valid but replaced**.

---

## Feature 2: GDPR Hard-Delete

### Endpoint

```
POST /v1/admin/erasure
{ "node_ids": [...], "reason": "gdpr_erasure", "request_id": "dsr-2026-001", "cascade_depth": 5 }
-> 202 Accepted { "job_id": "..." }
```

Operator-only (not MCP). Async Dagster job.

### Cascade

Traverse edges: `CITES`, `SYNTHESIZED_FROM`, `DERIVED_FROM`, `PROMOTED_FROM`, `MERGED_FROM`, `REFERENCES`

- Nodes with **only erased sources**: hard-delete
- Nodes with **mixed sources** (partial-source): log but don't auto-delete; flag for review

### Audit Trail

New table `erasure_audit_log` (Postgres):
- node_id, silo_id, node_type, deleted_at, deleted_by, reason, request_id, cascade_ids, stores_affected
- No `content` column (GDPR-safe)
- 7-year immutable retention

### Subject Identity

**Decision:** Ship both options in v1 for GDPR compliance on existing + new data.

| Option | Approach | Use Case |
|--------|----------|----------|
| A | Write-time `subject_id` field | New data (going forward) |
| B | Anchor node graph walk | Existing data (backfill not required) |

GDPR endpoint accepts either `subject_id` OR `anchor_node_ids`.

**Option B anchor-edge whitelist (required):**
- `EXTRACTED_FROM` - direct derivation from anchor
- `SUPERSEDES` - chain members
- `DERIVED_FROM_EVIDENCE` - reasoning chains
- `MENTIONS` - **exclude or limit to 1 hop** (prevents over-cascade via entity pivots)

---

## Feature 3: Supersession Chain Pruning

### Problem

Chains grow unbounded. A belief revised weekly = 52 stale nodes/year, each with embeddings.

### Approach: Stub-Retention (Preserves Provenance)

For chain `root -> v1 -> v2 -> ... -> vN (head)` exceeding `supersession_chain_max_length`:

1. Keep `root` (origin) and `head` (current) with full content
2. Convert interior nodes to **stubs**: clear `content`/`properties`, set `compacted_at`, `compact_reason = 'chain_pruning'`
3. **Keep node ID and all edges intact** - provenance graph remains correct
4. `trace` shows "[pruned: content removed for lifecycle compliance]" for stub nodes

This pattern matches `COMPACT_CHAIN` for ReasoningChains. Does NOT fabricate provenance by rewriting edges.

### Stub Handling in Recall and Trace

**Recall:** Filter stubs from search results (they have no content to match anyway). Add to Qdrant filter: `content IS NOT NULL` or check `compacted_at IS NULL`.

**Trace:** Include stubs in provenance graph but annotate:
```json
{
  "node_id": "...",
  "layer": "knowledge",
  "is_stub": true,
  "stub_reason": "chain_pruning",
  "compacted_at": "2026-05-20T...",
  "content": "[pruned: content removed for lifecycle compliance]"
}
```

### Why This Works with Pointer Optimization

The linked-list pointers (`tail_id`/`head_id`) require special handling:

| Pruned Node | Pointer Impact | Complexity |
|-------------|----------------|------------|
| Middle (v2) | None - head's tail_id and root's head_id unchanged | O(1) |
| Tail (root) | All nodes have stale tail_id; must rewrite | O(chain_length) |

By **preserving root**, we never need to rewrite pointers. Stub-retention preserves the full provenance graph - no shortcut edges needed.

### Config

```python
# retention/policy.py
supersession_chain_max_length: int = Field(default=20, ge=3)
chain_min_keep: int = Field(default=2, ge=2)  # head + one prior always kept
```

### Schedule

Dagster asset at 03:00 UTC daily (after retention sweep), partitioned by silo.

---

## Feature 4: Retention Policy Enhancements

### Per-Silo Overrides

**Use existing `SiloConfig.resolve()` pattern** (don't create new `for_silo()` method):

```python
# In Dagster retention asset (pipelines/assets/retention.py)
# BEFORE (broken - ignores per-silo overrides):
policy = RetentionPolicy.from_settings(settings)

# AFTER (correct - uses per-silo overrides):
silo = await silo_service.get(silo_id)
silo_config = SiloConfig.from_metadata(silo.metadata)
resolved = silo_config.resolve(settings)
policy = RetentionPolicy(
    ephemeral_max_age_hours=resolved.ephemeral_max_age_hours,
    standard_max_age_days=resolved.standard_max_age_days,
    # ... etc
)
```

### New Fields Required

Add to `models/silo.py` `RetentionOverrides`:
```python
supersession_chain_max_length: int | None = Field(default=None, ge=3)
```

Add to `models/silo.py` new `ForgetPolicyOverrides` class:
```python
class ForgetPolicyOverrides(BaseModel):
    model_config = {"extra": "ignore"}
    cancel_window_hours: int | None = Field(default=None, ge=1)
    rate_limit_per_hour: int | None = Field(default=None, ge=1)
```

Add to `config/settings.py`:
```python
retention_supersession_chain_max_length: int = 20
forget_cancel_window_hours: int = 1
forget_rate_limit_per_hour: int = 100
```

REST: `PATCH /v1/admin/silos/{id}` with `{"retention": {...}, "forget": {...}}`

---

## Risk Matrix (Top 5)

| Risk | Severity | Mitigation |
|------|----------|------------|
| Three-store inconsistency | HIGH | Saga pattern with compensation; idempotent ops |
| Cascade deletes wrong nodes | HIGH | Two-phase: soft delete first, partial-source detection |
| GDPR 30-day deadline breach | HIGH | Structured workflow, deadline tracking, day-25 alerts |
| Accidental mass deletion | HIGH | API-only, dry-run mode, 2-person approval for admin |
| Audit trail stores PII | HIGH | Hash-based proof (SHA256 of node_id + content_hash), no content column |

Full risk matrix: 13 risks across technical, compliance, implementation, operational categories.

---

## Implementation Order

| Step | Work | Dependency | Sprint |
|------|------|------------|--------|
| 0 | **Pointer indexes** (`tail_id`/`head_id`) + Redis lock for supersession | none | 1 |
| 1 | **Qdrant tombstone filter** (read-side filter + payload field + backfill script) | none | 1 |
| 2 | **Three-store hard-delete** (Memgraph-first ordering) + dead-letter queue | none | 1 |
| 2a | **Dead-letter reconciliation job** (Dagster, processes failed Qdrant deletes) | 2 | 1 |
| 3 | `forget` service methods + Qdrant payload sync on tombstone | 1, 2 | 1 |
| 4 | `forget` MCP tool + profile + abuse controls | 3 | 1 |
| 5 | Wire `SiloConfig.resolve()` into retention + new fields | none | 1 |
| 6 | Chain pruning asset (stub-retention) + schedule | 5 | 2 |
| 6a | **HyperEdge orphan cleanup** in groundskeeper job | 6 | 2 |
| 7 | `erasure_audit_log` migration + `ErasureService` + cold chain redaction | 2 | 2 |
| 8 | GDPR REST endpoint + Dagster job | 7 | 2 |
| 9 | Per-silo override REST support | 5 | 2 |

**Sprint 1:** Steps 0-5 (foundation + forget tool)
**Sprint 2:** Steps 6-9 (chain pruning + GDPR)

Note: Steps 1+3 are coupled - Qdrant filter alone doesn't fix tombstone bug, needs forget service to sync payload on tombstone.

---

## V1 Scope

### Ship

- `forget` MCP tool (soft delete + cancel)
- Three-store hard-delete coordination (bug fix)
- GDPR erasure endpoint (minimal, with `subject_id`)
- Chain pruning Dagster asset
- Per-silo retention overrides

### Defer to v1.1

- Cross-silo GDPR erasure
- GDPR dry-run mode
- `subject_id` backfill tool
- Agent-facing cascade (explicit `forget_cascade` tool)
- LLM-assisted chain collapse (for `permanent` decay class)

---

## Open Questions

1. **Subject identity model:** Option A (write-time) vs Option B (graph walk)?
   - Recommend Option A for v1

2. **Cancel window duration:** Per-silo config only, or per-tool-call?
   - Recommend per-silo only for simplicity

3. **Silo PII flag:** Should silos declare `contains_personal_data: bool`?
   - Useful to reject erasure calls on non-PII silos; defer decision

4. **Vector reidentifiability:** Legal review needed on whether embeddings are PII
   - Technical implementation (delete vectors) is conservative regardless

5. **Cross-border SLAs:** EU (1 day) vs US (5 day) backup deletion?
   - Defer to v1.1; single-region for v1

---

## Files Affected

| Area | Files | Changes |
|------|-------|---------|
| Models | `models/silo.py` | Add `supersession_chain_max_length` to `RetentionOverrides`, new `ForgetPolicyOverrides` class |
| Config | `config/settings.py` | Add `retention_supersession_chain_max_length`, `forget_cancel_window_hours`, `forget_rate_limit_per_hour` |
| Retention | `retention/policy.py`, `retention/service.py`, `retention/queries.py` | Three-store coordination, stub-retention queries, `forget_requested_at` handling |
| Engine | `engine/qdrant_store.py` | Tombstone payload filter, `set_payload()` for tombstone sync, backfill script |
| Engine | `engine/memgraph_store.py` | Redis lock for supersession |
| DB | `db/queries.py` | Stub-retention query, HyperEdge cleanup query, cold chain redaction |
| DB | `db/indexes.py` | Add `tail_id`/`head_id` indexes |
| MCP | `mcp/tools/forget.py` (new), `mcp/tools/registry.py`, `config/mcp_tools.yaml` | Forget tool + profile |
| Services | `services/erasure.py` (new) | ErasureService with cascade, partial-source handling |
| Pipelines | `pipelines/assets/retention.py` | Wire `SiloConfig.resolve()` |
| Pipelines | `pipelines/assets/chain_pruning.py` (new) | Stub-retention + HyperEdge cleanup |
| Pipelines | `pipelines/assets/dead_letter_reconciliation.py` (new) | Process failed Qdrant deletes |
| Postgres | Migration | `erasure_audit_log` + `ErasureReviewQueue` tables |

---

## Next Steps

1. ~~Review and decide open questions~~ Done
2. ~~Resolve critical review findings~~ Done (all issues resolved)
3. **Create implementation plan** via `superpowers:writing-plans`
4. Execute Sprint 1 (steps 0-5)
5. Execute Sprint 2 (steps 6-9)

---

## Review Findings (2026-05-20)

Independent reviews by Opus and Sonnet agents. Issues must be resolved before planning.

### Critical Issues

| # | Issue | Verdict | Resolution |
|---|-------|---------|------------|
| C1 | **Erasure cascade already exists** - `queries.py` P-G section has `RETRACT_CHAIN`, `REDACT_HOT_CHAIN_STEP`. | REVISE | Queries exist but have **zero callers** (dead code). `ErasureService` is new, not an extension. Reuse query constants but build orchestration from scratch. Note: `DELETE_NODE` doesn't clean chain pointer properties. |
| C2 | **`SiloConfig.resolve()` already exists** - `models/silo.py` has `RetentionOverrides`, `SiloConfig`. | APPROVE | Use existing pattern. **Bonus:** Fixes latent bug - Dagster asset bypasses `SiloConfig` entirely (`RetentionPolicy.from_settings()` ignores per-silo overrides). Add `supersession_chain_max_length` to `RetentionOverrides`. Put `forget_cancel_window_hours` in separate `ForgetPolicyOverrides` group. |
| C3 | **`subject_id` deferred = GDPR non-compliance** - Existing data un-erasable. | APPROVE | Ship both options in v1. Option A: `subject_id` on new writes. Option B: graph walk from anchor. **Required:** Define anchor-edge whitelist (suggest: `EXTRACTED_FROM`, `SUPERSEDES`, `DERIVED_FROM_EVIDENCE`; exclude `MENTIONS` or limit to 1 hop). |
| C4 | **Three-store saga has no compensation** - No concrete rollback defined. | CORRECTED | **Memgraph first** (authoritative store). Order: (1) Memgraph.delete - must succeed or abort, (2) Qdrant.delete - retry 3x, failure → dead-letter, (3) Postgres.cleanup - retry 3x, failure acceptable. Don't block GDPR response for vector cleanup. |
| C5 | **Concurrent supersession race** - Constraint not mandated. | CORRECTED | **Don't use DB constraint** - wrong property (`superseded_by` not `supersedes_id`), wrong label (`:Node` not in schema). Use **Redis lock** on predecessor node ID during supersession (same pattern as Custodian semaphore). MERGE provides edge-level idempotency. |
| C6 | **Chain pruning breaks `trace`** - D cites B, B pruned = broken reference. | CORRECTED | **Don't rewrite edges** (fabricates provenance). Use **stub-retention**: clear `content`/`properties`, set `compacted_at` + `compact_reason='chain_pruning'`, keep node ID + all edges. `trace` shows "[pruned: content removed]" for stub nodes. Same pattern as `COMPACT_CHAIN`. |

### High Issues

| # | Issue | Resolution |
|---|-------|------------|
| H1 | **Qdrant payload migration** | RESOLVED: Step 1 includes (a) read-side filter on `tombstoned_at IS NULL`, (b) write-path: `forget` service calls `qdrant.set_payload({tombstoned_at: now})`, (c) backfill script for existing tombstoned nodes, (d) payload index in `_ensure_collection`. |
| H2 | **Cold chain PII** | RESOLVED: Step 7 includes cold chain redaction. `ErasureService` checks `chain.tier = 'cold'` and nulls `compact_summary` in addition to `steps`. |
| H3 | **`forget` cancel needs separate timestamp** | RESOLVED: Add `forget_requested_at` timestamp alongside `tombstoned_at`. Cancel window = `now < forget_requested_at + cancel_window_hours`. Grace period = `now > tombstoned_at + grace_period_days`. |
| H4 | **GDPR partial-source "flag for review"** | RESOLVED: Add `partial_source_nodes` array to `erasure_audit_log`. Create `ErasureReviewQueue` Postgres table with `node_id`, `erasure_job_id`, `remaining_sources`, `created_at`. Dagster alert on queue size > 0. |
| H5 | **Cascade edge list incomplete** | RESOLVED: Full list for GDPR cascade: `CITES`, `SYNTHESIZED_FROM`, `DERIVED_FROM`, `PROMOTED_FROM`, `MERGED_FROM`, `REFERENCES`, `CAUSES`, `EXTRACTED_FROM`, `CRYSTALLIZED_INTO`, `DERIVED_FROM_EVIDENCE`, `PROMOTED_TO`. Exclude `MENTIONS` (entity pivot) and `ACCESSED_BY` (session trace, not content). |
| H6 | **HyperEdge orphan** | RESOLVED: Step 6a adds HyperEdge cleanup to `groundskeeper_nightly`. Query: `MATCH (h:HyperEdge) WHERE NOT (h)-[:PARTICIPANT]->() DETACH DELETE h`. |
| H7 | **Forked chains break pointers** | RESOLVED: Redis lock on predecessor node ID prevents concurrent supersession. If forking is intentional (two valid successors), document that only one gets `head_id` - the other is a branch, not a chain extension. |

### Medium Issues

| # | Issue | Resolution |
|---|-------|------------|
| M1 | **`tombstoned_at` format** | RESOLVED: Use epoch-microseconds (`timestamp()` in Cypher) to match codebase convention. Update `TOMBSTONE_NODE` query and all comparisons. |
| M2 | **`forget` cancel state changes** | RESOLVED: Cancel reverses: `tombstoned_at = NULL`, `forget_requested_at = NULL`, `retention_run_id = NULL`, Qdrant payload `tombstoned_at = NULL`, `heat_dirty = true`. |
| M3 | **`forget` abuse controls** | RESOLVED: Add to `ForgetPolicyOverrides`: `rate_limit_per_hour` (default 100), `max_batch_size` (default 10). Operator can set `forget_enabled: false` per silo. No 2-person approval for agent forget (that's GDPR only). |
| M4 | **Tests will break** | RESOLVED: Update `test_retention_service.py` to mock both Memgraph and Qdrant stores. Add integration test with testcontainers for three-store coordination. |
| M5 | **Step 1/2 dependency** | RESOLVED: Implementation order updated. Note added that Steps 1+3 are coupled - filter alone doesn't fix bug, needs service to sync payload. |
| M6 | **`supersession_chain_max_length` not in Settings** | RESOLVED: Added `retention_supersession_chain_max_length: int = 20` to Settings, `supersession_chain_max_length` to `RetentionOverrides`. |
| M7 | **Pointer indexes** | RESOLVED: Added as Step 0 in implementation order. Indexes: `CREATE INDEX ON :Node(tail_id)`, `CREATE INDEX ON :Node(head_id)`. |

### Contradictions Found

| # | Contradiction | Resolution |
|---|---------------|------------|
| X1 | Cancel window (1h) vs grace period (7d) semantics | RESOLVED: Cancel = reversal window (forget_requested_at + hours), grace = hard-delete timing (tombstoned_at + days). Two separate timestamps. |
| X2 | `SUPERSEDES_ORIGIN` edge type doesn't exist | RESOLVED: Remove references to `SUPERSEDES_ORIGIN`. Use standard `SUPERSEDES` edge with `source: 'chain_pruning'` property. Stub-retention approach means we don't need a shortcut edge - provenance graph stays intact. |
| X3 | `retention_overrides` key vs `SiloConfig` structure | RESOLVED: Use existing `SiloConfig` pattern. Add new fields to `RetentionOverrides` and new `ForgetPolicyOverrides` class. |
| X4 | Step 1 alone doesn't fix tombstone bug (needs Step 3) | RESOLVED: Implementation order updated with note that Steps 1+3 are coupled. |

### What Works Well (Keep)

- Three-store saga pattern (needs concrete compensation)
- Tombstone-middle with preserved root (with documented tradeoffs)
- `erasure_audit_log` design (no content, hash-based proof)
- Read-time resolution pattern (Datomic/CQRS)
- Deferring cross-silo erasure to v1.1

### Priority Actions Before Planning

All critical, high, and medium issues have been resolved in this spec. Key resolutions:

1. **SiloConfig.resolve()** - Wire into Dagster asset (fixes latent bug)
2. **Anchor-edge whitelist** - Defined: `EXTRACTED_FROM`, `SUPERSEDES`, `DERIVED_FROM_EVIDENCE`, etc.
3. **Redis lock** - For supersession race (same pattern as Custodian)
4. **Stub-retention** - For chain pruning (preserves provenance)
5. **Memgraph-first ordering** - For three-store saga
6. **Full cascade edge list** - 11 edge types defined
7. **Cold chain redaction** - In Step 7
8. **Pointer indexes** - In Step 0
9. **Dead-letter reconciliation** - In Step 2a
10. **HyperEdge cleanup** - In Step 6a

**Ready for implementation planning.**

---

## Appendix: Graph Resolution Research

Research conducted 2026-05-20 on temporal graph patterns for stale reference resolution.

### Problem Statement

When D cites B, and B is later superseded by C, how do we ensure queries resolve to the current head?

### Industry Patterns

| System | Approach | Our Mapping |
|--------|----------|-------------|
| PostgreSQL HOT | Pointer chains, vacuum compacts | `tail_id`/`head_id` pointers |
| Datomic | Stable entity ID, resolve at read | Node IDs stable, `resolve_current_head` at query |
| XTDB | Bitemporal indexes | `valid_from`/`valid_to` properties |
| Union-Find | Path compression | Our approach without destructive compression |

### Recommendation: Read-Time Resolution

**Don't rewrite edges on supersession.** This is the Datomic/CQRS pattern:
- Write side: `create_supersedes_edge` creates SUPERSEDES edge, updates pointers
- Read side: `recall`/`trace` resolve edge targets via `filter_superseded_at`

Benefits:
- O(1) writes (no in-degree fanout)
- Preserves provenance (original edges intact for time-travel)
- Consistent with existing architecture

### Implementation Gap: Wire Up Resolution

The pointer infrastructure exists but isn't called:
- `RESOLVE_CURRENT_HEAD` query defined but unused
- `filter_superseded_at` method defined but unused
- `recall` filters superseded nodes but doesn't resolve references TO them

**Fix:** In recall post-processing, resolve all `cites`/`derived_from` targets.

### Required Indexes

```cypher
CREATE INDEX ON :Node(tail_id);
CREATE INDEX ON :Node(head_id);
```

Without these, pointer lookups fall back to property scan.

### Concurrent Supersession Race

Two transactions superseding the same node:
1. Both read `old.tail_id`
2. Both compute `tail_id = COALESCE(old.tail_id, old.id)`
3. Both write `tail.head_id = new.id`
4. Last write wins, first superseder orphaned

**Resolution: Redis lock (not DB constraint)**

DB constraint rejected because:
- Wrong property (`superseded_by` is set on OLD node, not new)
- Wrong label (`:Node` not in phase-3 schema)
- Would prevent forking which may be intentional

Correct approach:
- **Redis lock on predecessor node ID** during supersession writes
- Same pattern as Custodian semaphore (`pipelines/poison_queue.py`)
- MERGE provides edge-level idempotency as additional guard

### Chain Compaction (Stub-Retention)

Add to `groundskeeper_nightly`:
1. Log chain depth distribution per silo
2. When depth > `supersession_chain_max_length` (default 20):
   - Convert interior nodes to stubs (clear content, set `compacted_at`)
   - Keep node IDs and edges intact (no pointer updates needed)
   - Preserves provenance graph for `trace`

---

## References

- `docs/superpowers/specs/2026-05-20-self-hosted-rest-api-design.md` - REST API spec with DELETE endpoints
- `context/plans/archive/2026-05-19-supersession-head-pointer.md` - Pointer optimization (tail_id/head_id)
- `src/context_service/retention/` - Existing retention infrastructure
- PostgreSQL HOT chains - postgrespro.com/blog/pgsql/5967910
- Datomic Identity Model - docs.datomic.com/schema/identity.html
- XTDB Bitemporality - v1-docs.xtdb.com/concepts/bitemporality/

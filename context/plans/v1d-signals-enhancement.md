# v1d Signals Enhancement Plan

**Status:** IN PROGRESS (Phase 1+2 complete, Phase 3+4 pending)
**Goal:** Extend the signals subsystem with query-time heat ranking, unified decay model, and write-side access events.
**Branch:** `phase-signals-enhancement`

---

## Adversarial Review Changes

This revision addresses findings from the adversarial review:

| Finding | Resolution |
|---------|------------|
| Phase ordering backward (P1 tests break when P2 changes scores) | Reorder: Phase 1 = feature flags + schema prep, Phase 2 = heat ranking, Phase 3 = unified decay, Phase 4 = write events |
| `event_type` breaking schema change | Add fallback: missing event_type defaults to "read" |
| Flooding contradiction in write events | Clarify: one event per write transaction, not per reference |
| N+1 in heat asset for layer lookup | Embed layer in Redis stream entry at emit time |
| Read spam inflates heat | Add per-node dedup with cooldown window |
| Layer exploit (tag as "wisdom") | Layer is immutable post-creation; validate via node label not property |
| Orphaned events (emit before commit) | Emit after successful commit |
| No migration path | Add recompute task with backfill flag |
| Phases not independently rollbackable | Each phase behind its own feature flag |
| No circuit breaker | Add asset error handling + observability |

---

## Phase 1: Foundation (feature flags + schema prep)

**Effort:** Low (1-2 hours)
**Rationale:** Establish kill-switches and schema changes before any behavioral changes.

### Tasks

- [x] **1.1** Add feature flags to `config/settings.py`:
  ```python
  heat_ranking_enabled: bool = False
  unified_decay_enabled: bool = False
  write_events_enabled: bool = False
  ```
- [x] **1.2** Add tuning knobs (inactive until flags enabled):
  ```python
  heat_weight: float = 0.1
  heat_half_life_days: int = 7
  heat_read_weight: float = 1.0
  heat_write_weight: float = 0.5
  heat_dedup_window_seconds: int = 300  # 5 min cooldown per node
  ```
- [ ] **1.3** Update `emit_access_event` signature to accept optional `event_type: str = "read"` and `layer: str | None = None`
- [ ] **1.4** Update heat asset to handle missing `event_type` field (default to "read" for backwards compat)
- [ ] **1.5** Add `heat_events_processed` and `heat_events_skipped` metrics to asset logging

### Acceptance
- All flags default OFF (no behavior change)
- Old events without `event_type` processed as reads
- Metrics logged per asset run

---

## Phase 2: Query-time heat ranking

**Effort:** Low (2-3 hours)
**Rationale:** Heat scores already exist on nodes. This phase adds them to query ranking behind feature flag.

### Tasks

- [x] **2.1** In `services/context.py::query`, add heat adjustment (gated by flag):
  ```python
  if settings.heat_ranking_enabled and heat_weight > 0:
      heat = float(props.get("heat_score", 0.5))
      relevance = relevance * ((1.0 - heat_weight) + heat_weight * heat)
  ```
- [x] **2.2** Add test `tests/test_context_query_heat.py`:
  - Hot node outranks cold node at equal semantic score (flag ON)
  - Ranking unchanged when flag OFF
  - Missing heat_score uses 0.5 fallback
- [ ] **2.3** Document in `context/api-examples.md`

### Acceptance
- `heat_ranking_enabled=True` + `heat_weight=0.1` boosts hot nodes
- `heat_ranking_enabled=False` = no change to existing behavior
- Independently rollbackable via flag

---

## Phase 3: Unified decay model

**Effort:** Medium (4-6 hours)
**Rationale:** Replace arbitrary per-layer multipliers with label-based decay. Layer is determined by node label (`:Claim`, `:Fact`, `:Commitment`, `:Insight`), not a mutable property.

### Design decisions

1. **Exponential decay** (simpler than Gaussian, industry standard)
2. **Layer from label, not property** - immutable, not gameable
3. **Multipliers derived from epistemology** - higher layers represent validated knowledge, should retain heat longer:
   - Memory (`:Claim`, `:Finding`): 1.0x (7 days base)
   - Knowledge (`:Fact`): 2.0x (14 days)
   - Wisdom (`:Commitment`): 3.0x (21 days)
   - Intelligence (`:Insight`, `:ReasoningChain`): 4.0x (28 days)

### Tasks

- [ ] **3.1** Add `LAYER_DECAY_MULTIPLIERS` constant to `signals/heat.py`:
  ```python
  LAYER_DECAY_MULTIPLIERS: dict[str, float] = {
      "Claim": 1.0, "Finding": 1.0,
      "Fact": 2.0,
      "Commitment": 3.0,
      "Insight": 4.0, "ReasoningChain": 4.0,
  }
  ```
- [ ] **3.2** Update `emit_access_event` calls in MCP tools to include `layer` param (read from node labels, not properties)
- [ ] **3.3** Update heat asset to:
  - Read `layer` from stream entry (not Memgraph lookup - avoids N+1)
  - Apply multiplier: `effective_half_life = base_half_life * multiplier`
  - Gate behind `unified_decay_enabled` flag
- [ ] **3.4** Add backfill task: `just heat-recompute` that triggers full asset run with `--backfill` flag
- [ ] **3.5** Add test: Fact-layer node retains heat longer than Claim-layer node
- [ ] **3.6** Deprecate unused Gaussian freshness config (`sigma_default_days`, `temporal_decay_enabled`) with removal in v1e

### Acceptance
- `unified_decay_enabled=True` applies label-based multipliers
- Layer read from stream entry (no N+1)
- Backfill task available for migration
- Independently rollbackable via flag

---

## Phase 4: Write-side access events

**Effort:** Medium (3-4 hours)
**Rationale:** Writes signal stronger intent than reads. Emit events after successful commit to avoid orphans.

### Design decisions

1. **One event per write transaction** - not per reference (avoids flooding)
2. **Emit after commit** - no orphaned events from failed writes
3. **Dedup window** - same node accessed within 5 min = one event
4. **Write weight 0.5x** - prevents write-heavy agents from dominating

### Tasks

- [ ] **4.1** Add dedup logic to `emit_access_event`:
  ```python
  dedup_key = f"heat:dedup:{silo_id}:{node_id}"
  if await redis.exists(dedup_key):
      return  # skip duplicate
  await redis.setex(dedup_key, settings.heat_dedup_window_seconds, "1")
  ```
- [ ] **4.2** Emit write event from `context_link` (target node only, after successful link)
- [ ] **4.3** Emit write event from `context_assert` (one event for the claim node itself, not per evidence_node)
- [ ] **4.4** Emit write event from `context_commit` (one event for the commitment node itself, not per about_node)
- [ ] **4.5** Update heat asset to weight by event_type:
  ```python
  weight = settings.heat_read_weight if event_type == "read" else settings.heat_write_weight
  ```
- [ ] **4.6** Gate all write emissions behind `write_events_enabled` flag
- [ ] **4.7** Add tests:
  - Write event has `event_type="write"`
  - Dedup prevents spam within window
  - Failed write does not emit event

### Acceptance
- Write tools emit one event per transaction (not per reference)
- Events only emitted after successful commit
- 5-min dedup window prevents spam
- `write_events_enabled=False` = no write events (rollback)

---

## Operational safeguards

### Feature flags (all default OFF)
```python
heat_ranking_enabled: bool = False      # Phase 2
unified_decay_enabled: bool = False     # Phase 3
write_events_enabled: bool = False      # Phase 4
```

### Rollback procedure
1. Set flag to False in env/config
2. Restart service (no redeploy needed)
3. Heat asset continues with old logic

### Migration
- Phase 3 requires `just heat-recompute` after enabling `unified_decay_enabled`
- Old scores remain valid but will shift on next asset run

### Circuit breaker
- Heat asset logs `heat_asset_error` on failure, does not raise
- Stale scores are better than no scores
- Alert on consecutive failures via existing Dagster sensors

---

## Out of scope

- Full PageRank/citation propagation (batch graph algorithm, high complexity)
- A/B testing infrastructure
- Per-silo decay configuration
- Heat ceiling/normalization (consider for v1e if runaway scores observed)
- Gaussian freshness removal (deprecated in Phase 3, removed in v1e)

---

## Risks (post-revision)

| Risk | Mitigation |
|------|------------|
| Compounding penalties (low heat + low freshness) | Keep weights small (0.1 each); monitor score distribution |
| Write-heavy agents | 0.5x weight + dedup window; monitor per-agent event counts |
| Layer detection in stream | Embed at emit time; fallback to 1.0x if missing |
| Migration ranking shift | Backfill task + gradual rollout via flag |

---

## Done criteria

- [ ] All four phases merged to main
- [ ] All three feature flags tested ON and OFF
- [ ] `just check && just test` green
- [ ] `just heat-recompute` backfill task works
- [ ] Manual verification with flags enabled

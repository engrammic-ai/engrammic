# Signals Port: Heat, Freshness, Priority

**Status:** Shipped (Phase 1+2 complete 2026-05-02); v1d enhancements in progress
**Brainstorm:** `context/brainstorm/2026-04-30-signals-port.md`
**Phasing:** Phase 1 ships this week (stubs + live emitters + real freshness/priority); Phase 2 ships after partner talks (real heat asset).

## Goal

Port the three signal subsystems from `prototype` (`pipelines/assets/heat.py`, `app/services/access_events.py`, retrieval-time freshness in `app/services/context.py`, `app/custodian/priority.py`) into `context-service/src/context_service/signals/`. The custodian must visit hot-and-uncertain content first (cost control); retrieval must penalise stale content; the demo must be able to show "the system gets sharper on what you actually use."

## Non-goals

- Memgraph disaster recovery / snapshots.
- Cost tracking (separate spec).
- Admin / dashboard UI for heat or tier inspection (deferred to v1.0+).
- Per-silo configurability of half-life, σ, or tier thresholds.

## Layout

```
src/context_service/signals/
├── __init__.py             # public API surface
├── heat.py                 # get_heat(node_id, silo_id) -> float
│                           # Phase 1: stub returning 0.5
│                           # Phase 2: read node.heat_score from Memgraph
├── freshness.py            # compute_freshness(created_at, now, sigma_days) -> float
├── priority.py             # compute_consensus_priority(...)  (moved from custodian/)
├── access_events.py        # emit_access_event(redis, silo_id, node_id) — live in P1
└── cursor.py               # Phase 2: HeatCursor read/advance (Memgraph singleton)
```

`custodian/priority.py` is reduced to a one-line re-export of `signals.priority` for back-compat.

`pipelines/assets/heat.py` is added in Phase 2.

## Phase 1 — this week

### 1.1 Public API stubs / real implementations

| Module | Phase 1 behaviour |
|---|---|
| `signals.heat.get_heat(memgraph, node_id, silo_id)` | async. Phase 1 ignores `memgraph` and returns `0.5` (neutral); logs `heat.stub_active` once per silo per process run so the stub is grep-able. Signature stays stable across phases so consumers don't refactor when stub flips to real. |
| `signals.freshness.compute_freshness(created_at, now, sigma_days=30)` | real. `max(0.25, exp(-0.5 * (t/σ)**2))` where `t` is days. Pure function, no I/O. |
| `signals.priority.compute_consensus_priority(avg_confidence, avg_heat, distinct_agents)` | real. File moved from `custodian/priority.py`; formula unchanged. |
| `signals.access_events.emit_access_event(redis, silo_id, node_id)` | real. `await redis.xadd(f"silo:{silo_id}:access_events", {"node_id": str(node_id)}, maxlen=100_000, approximate=True)`. Wrap in try/except — log and swallow on Redis failure (best-effort signal, never blocks reads). |

### 1.2 Wire-ups

**Access-event emission** — call `emit_access_event` from each MCP read tool wherever a node is resolved into user-visible output:

- `mcp/tools/context_get.py` — after the node is fetched and authorised, before return.
- `mcp/tools/context_query.py` — after candidate set is finalised, emit once per returned node.
- `mcp/tools/context_lookup.py` (or equivalent) — same pattern.

Use a Redis pipeline (`async with redis.pipeline()`) when emitting for multiple nodes from a single tool call.

**Freshness in retrieval** — in `services/context.py`, after candidate scoring and before final ranking:

```python
freshness_weight = settings.freshness_weight  # default 0.3
for cand in candidates:
    fresh = signals.freshness.compute_freshness(cand.created_at, now, sigma_days=settings.freshness_sigma_days)
    cand.score *= (1 - freshness_weight) + freshness_weight * fresh
```

Add `freshness_weight: float = 0.3` and `freshness_sigma_days: int = 30` to `config/settings.py`.

**Priority in consensus sensor** — extend `custodian/sensors/consensus.py::FIND_CONSENSUS_CANDIDATES` to also return `avg_chain_confidence` (from chain rows). After the Cypher returns, in Python: for each candidate, fetch heat via `await signals.heat.get_heat(memgraph, target_id, silo_id)` (stubbed → 0.5 in P1, real in P2), compute priority, sort `DESC` by priority, return top `limit`. Replace the current `ORDER BY distinct_agents DESC, chain_count DESC` with this Python-side ranking.

### 1.3 Tests

- `tests/test_signals_freshness.py` — table-driven cases: t=0 → 1.0; t=σ → ≈0.61; t=3σ → 0.25 floor; negative t (clock skew) clamped to 1.0.
- `tests/test_signals_priority.py` — confirm formula edge cases: zero heat → priority=0; agent_count=1 → low priority (self-promotion guard); agent_count clamps at 5; confidence=1.0 → priority=0.
- `tests/test_signals_access_events.py` — mock Redis, assert XADD shape (stream key, payload, maxlen). Confirm Redis failure does not raise to caller.
- `tests/test_consensus_priority_ordering.py` — given seeded fixtures with mixed heat / confidence / agent counts, assert the candidate order produced by the sensor matches expected priority ranking.
- No integration test for emitter wiring in P1; covered by β5 integration test pack when that lands.

### 1.4 Acceptance criteria — Phase 1

- `just check` and `just test` green.
- `signals/heat.py::get_heat` returns `0.5` and emits a single `heat.stub_active` log entry on first call per silo per process.
- Each MCP read tool emits one `silo:{silo_id}:access_events` entry per resolved node. Verified by spinning up Redis, calling the tool, and `XLEN`-ing the stream.
- `services/context.py` retrieval applies the freshness multiplier when `freshness_weight > 0`. A test fixture with two otherwise-identical candidates differing only in `created_at` returns the fresher one first.
- Consensus sensor ordering changes from `(distinct_agents, chain_count)` to priority-formula ranking. Pinned by a test.

## Phase 2 — after partner talks

### 2.1 Cursor

`signals/cursor.py`:

```python
async def fetch_or_init_heat_cursor(memgraph, silo_id) -> str: ...
async def advance_heat_cursor(memgraph, silo_id, last_id, *, tx=None) -> None: ...
```

Backing node:

```cypher
MERGE (c:HeatCursor {silo_id: $silo_id})
ON CREATE SET c.last_id = '0-0', c.created_at = $now
RETURN c.last_id AS last_id
```

`advance_heat_cursor` runs in the same session/transaction as the heat application so cursor advance and heat write commit together.

Index added in `db/indexes.py`: `CREATE INDEX ON :HeatCursor(silo_id)`.

### 2.2 Heat asset

`pipelines/assets/heat.py` — direct port of prototype's asset, with substitutions:

| Contextr | Replacement |
|---|---|
| `postgres.fetch_or_init_heat_cursor` | `signals.cursor.fetch_or_init_heat_cursor` |
| `postgres.advance_heat_cursor` | `signals.cursor.advance_heat_cursor` (run inside the same Memgraph session as `APPLY_HEAT_CYPHER`) |
| `silo_partitions = dg.DynamicPartitionsDefinition(name="silo")` | reuse the existing `silo` partitions definition from `pipelines/partitions.py` |
| `MemgraphResource`, `RedisResource` | already wired in `pipelines/resources.py` |

Cypher (`APPLY_HEAT_CYPHER`, `RECOMPUTE_TIERS_CYPHER`) imported verbatim — both are already silo-scoped via `$silo_id` and use the multi-label content predicate, which matches this repo's schema.

### 2.3 Schedule

Add to `pipelines/schedules.py`: hourly schedule per active silo, matching the existing β2 fact-promotion schedule pattern. Concurrency-keyed by silo so a slow run on one silo doesn't block others.

Index added in `db/indexes.py`: `CREATE INDEX ON :Cluster(tier)` so admin / dashboard queries by tier are cheap.

### 2.4 Flip stub → real

`signals/heat.py::get_heat`:

```python
async def get_heat(memgraph, node_id, silo_id) -> float:
    row = await memgraph.execute_query(
        "MATCH (n {id: $id, silo_id: $silo_id}) RETURN coalesce(n.heat_score, 0.5) AS h",
        {"id": str(node_id), "silo_id": silo_id},
    )
    return float(row[0]["h"]) if row else 0.5
```

Remove `heat.stub_active` log line. Update the consensus-sensor batch fetch to retrieve heat for all candidates in one query rather than N round-trips (`UNWIND $ids AS id MATCH (n {id: id, silo_id: $silo_id}) RETURN n.id, n.heat_score`).

### 2.5 Acceptance criteria — Phase 2

- `just dagster-web` shows `heat_scores` and `cluster_tiers` assets, partitioned by silo.
- Hourly schedule materialises both assets. Manual launch on a seeded silo populates `n.heat_score` and `:Cluster.tier` correctly.
- Cursor advances atomically with heat write — verified by a test that injects a Memgraph failure between `APPLY_HEAT_CYPHER` and cursor advance and confirms neither commits.
- `get_heat` returns real values; `heat.stub_active` log line no longer fires.
- Consensus sensor priority ordering shifts measurably once heat data is populated (regression test on a fixture with prior-week access events seeded).

## Defaults / constants

| Constant | Value | Source |
|---|---|---|
| `HEAT_HALF_LIFE` | 7 days | prototype |
| `TIER_THRESHOLDS` | HOT ≥ 0.66, WARM ≥ 0.33 | prototype |
| `XREAD_COUNT` | 10 000 per asset run | prototype |
| `ACCESS_STREAM_MAXLEN` | 100 000 (approximate) | new |
| `freshness_sigma_days` | 30 | port |
| `freshness_weight` | 0.3 | port |
| Stub heat value | 0.5 | new (avoids killing the priority formula during P1) |

All exposed via `config/settings.py` so they can be overridden per environment without code change. Per-silo override is out of scope.

## Risks

- **Stream backpressure.** If a silo's read traffic outpaces the heat asset's hourly cadence, the stream MAXLEN truncates oldest entries. Acceptable at 100 k entries / 1 hour cadence (would need ≈28 events/sec sustained to lose data); reconsider cadence if a partner exceeds this.
- **Cursor advance failure.** If the heat write commits but cursor advance fails (network blip between two Cypher calls in the same session), next run double-counts the same window. Mitigation: keep both inside a single transaction (`session.execute_write`).
- **Stub leakage.** Phase 1 ships with `get_heat` returning 0.5 for everything. Consequence: priority formula effectively reduces to `(1 - confidence) * log(distinct_agents + 1)` during the stub week. Documented; acceptable for partner trials since the relative ordering on the other two factors is still meaningful.

---

## v1d Enhancements (post Phase 2)

**Status:** Draft 2026-05-02
**Plan:** `context/plans/v1d-signals-enhancement.md`

Four additional phases extending the signals subsystem after Phase 1+2 shipped.

### v1d-1: Foundation (feature flags + schema prep)

Add kill-switches before any behavioral changes:

```python
heat_ranking_enabled: bool = False      # gates query-time heat
unified_decay_enabled: bool = False     # gates per-layer decay
write_events_enabled: bool = False      # gates write-side events
```

Update `emit_access_event` signature:
```python
async def emit_access_event(
    redis: RedisClient,
    silo_id: str,
    node_id: str,
    event_type: str = "read",      # "read" or "write"
    layer: str | None = None,       # for per-layer decay
) -> None
```

Heat asset handles missing `event_type` field (defaults to "read" for backwards compat).

### v1d-2: Query-time heat ranking

Heat scores already exist on nodes (from Phase 2 asset). Add to query ranking:

```python
if settings.heat_ranking_enabled and heat_weight > 0:
    heat = float(props.get("heat_score", 0.5))
    relevance = relevance * ((1.0 - heat_weight) + heat_weight * heat)
```

Default `heat_weight: float = 0.1`. No additional I/O (heat_score already in node properties).

Tradeoffs (from industry research):
- Filter bubbles: popular stays popular. Mitigate with small weight (0.1) and diversity re-ranking.
- Cold start: new nodes at 0.5 fallback. Acceptable.
- Compounding: low heat + low freshness = double penalty. Keep both weights small.

### v1d-3: Unified decay model

Replace arbitrary constants with label-based decay. Layer determined by node label (immutable, not gameable):

| Label | Multiplier | Effective half-life |
|-------|------------|---------------------|
| `:Claim`, `:Finding` | 1.0x | 7 days |
| `:Fact` | 2.0x | 14 days |
| `:Commitment` | 3.0x | 21 days |
| `:Insight`, `:ReasoningChain` | 4.0x | 28 days |

Embed `layer` in Redis stream entry at emit time (avoids N+1 in heat asset). Asset reads layer from stream, applies multiplier.

Deprecate unused Gaussian freshness config (`sigma_default_days`, `temporal_decay_enabled`).

Add backfill task: `just heat-recompute` for migration.

### v1d-4: Write-side access events

Writes signal stronger intent than reads. Design:

1. **One event per write transaction** (not per reference - avoids flooding)
2. **Emit after successful commit** (no orphaned events from failed writes)
3. **Dedup window** (5 min cooldown per node)
4. **Write weight 0.5x** (prevents write-heavy agents from dominating)

```python
heat_read_weight: float = 1.0
heat_write_weight: float = 0.5
heat_dedup_window_seconds: int = 300
```

Emit from:
- `context_link`: target node only
- `context_assert`: claim node itself (not per evidence_node)
- `context_commit`: commitment node itself (not per about_node)

### v1d constants

| Constant | Value | Notes |
|----------|-------|-------|
| `heat_weight` | 0.1 | query-time multiplier |
| `heat_read_weight` | 1.0 | event weight for reads |
| `heat_write_weight` | 0.5 | event weight for writes |
| `heat_dedup_window_seconds` | 300 | 5 min cooldown |
| Layer multipliers | 1.0/2.0/3.0/4.0 | by epistemological layer |

### v1d risks (addressed)

| Risk | Mitigation |
|------|------------|
| Compounding penalties | Keep weights small (0.1 each) |
| Write-heavy agents | 0.5x weight + dedup window |
| Layer gaming | Layer from label (immutable), not property |
| Orphaned events | Emit after commit |
| Migration ranking shift | Backfill task + gradual rollout via flag |
| Phase coupling | Each phase behind independent feature flag |

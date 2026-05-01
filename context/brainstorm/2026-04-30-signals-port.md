# Brainstorm: Signals Port (Heat / Freshness / Priority)

**Date:** 2026-04-30
**Driver:** partner-readiness for Antler residency, Knowzilla (Mon), Silt (Sat), angels+VCs (Wed next week).
**Outcome:** spec at `context/specs/signals-port.md`.

## Why

`src/context_service/signals/__init__.py` has been a one-line TODO since the 2026-04-26 port from `prototype`. The custodian visits nodes without priority weighting (LLM cost is uncontrolled), and the demo story for partners — "the system gets sharper on what you actually use" — has no implementation behind it. v1-β master plan never scoped signals; they fell through the gap. Time to close it.

## What was already in prototype

- **Heat** (`pipelines/assets/heat.py`): hourly Dagster asset per silo. `XREAD` `silo:{silo_id}:access_events` from a Postgres-backed cursor, aggregate per-node deltas, exp-decay each `n.heat_score` with `t_½ = 7 days`, and assign `:Cluster.tier` ∈ {HOT, WARM, COLD} by quantile (≥0.66 / ≥0.33).
- **Freshness** (`app/services/context.py:2136`): retrieval-time Gaussian. `fresh_score = max(0.25, exp(-0.5 * (t/σ)**2))` where `t` is age-in-days. Multiplicative on the retrieval score, gated by `freshness_weight`.
- **Priority** (`app/custodian/priority.py`): `(1 - avg_confidence) * avg_heat * log(min(distinct_agents, 5) + 1)`. Already mechanically ported into this repo at `custodian/priority.py` but never wired to a consumer.
- **Access-event emitters** (`app/services/access_events.py`, called from `app/mcp/tools/context_get.py` + `context_lookup.py`): fire-and-forget XADD on user-facing reads.

## Deltas vs the prototype environment

| Concern | prototype | context-service |
|---|---|---|
| Heat cursor | Postgres | (no Postgres) — needs substitute |
| Cluster tier index | implicit | needs `:Cluster(tier)` index added |
| Priority consumer | unknown wire-up site | identified: `custodian/sensors/consensus.py::find_consensus_candidates` orders by `distinct_agents DESC, chain_count DESC` — splice in the formula here |
| Freshness location | inline in `services/context.py` | port to `signals/freshness.py`, called from `services/context.py` |
| Multi-tenancy | silo_id | same — Cypher already silo-scoped |

## Decisions

### Q1 — Scope (heat alone vs heat+priority vs all three)
**Decision:** all three (heat + freshness + priority), **phased**: stubs this week, real heat next week.
**Why:** the partner-narrative arc is "the more you use it the cheaper and sharper it gets" — that's heat *and* priority. Freshness is a per-query micro-tweak but the port is trivial (Gaussian + a settings knob), so doing it now rather than later costs nothing.
**Phasing:** real heat is the heaviest piece (Dagster asset, schedule, cursor, tier recompute). Stubbing it this week lets the rest of the surface ship now without blocking on the asset.

### Q2 — Access-event emission timing
**Decision:** emit live this week (option A), even though the consumer asset doesn't land until next week.
**Why:** the marginal cost is ~30 lines of fire-and-forget XADD. Alternative B (stub emitters too) means real heat starts cold — first meaningful tier assignment happens a week after the asset ships. With A, heat decays a real week of partner-trial signal on its first run.

### Q3 — Heat cursor storage substitute
**Considered:** Redis key, Memgraph singleton node, Redis stream consumer groups, Memgraph + Postgres backup.
**Decision:** Memgraph singleton `:HeatCursor {silo_id, last_id}` alone.
**Why:**
- Cursor write lives in the same Memgraph session as the heat application → atomic ("cursor advances iff heat applied").
- Redis-key option (A) mixes durable state into a cache-tier Redis; bites later.
- Consumer-group option (C) is more idiomatic but the per-silo group bootstrap + claim/ack semantics are fiddlier than the problem warrants.
- Postgres-backup variant rejected: adds a whole datastore for one 64-bit integer per silo. If Memgraph loses the cursor it's lost the graph, so the cursor is the least valuable thing to back up. Disaster-recovery is a Memgraph-snapshots conversation, separate from this work.

### Defaults baked in
- Stub heat returns **0.5**, not 0.0 (zero would multiply through the priority formula and kill all consensus tasks during the stub week). Logged once per silo per asset run as `heat.stub_active` so the stub is grep-able post-hoc.
- Tier thresholds: 0.66 / 0.33 (prototype).
- Half-life: 7 days (prototype).
- Freshness σ = 30 days, `freshness_weight = 0.3` (gentle nudge, not a gate).
- Access-event stream MAXLEN ≈ 100k per silo (~3 days at 1 event/sec heavy usage; well past one heat-asset run).
- Access-event payload: `node_id` only. No access type / agent. Redis stream IDs already carry timestamps.
- Per-silo configurability of half-life / σ / thresholds: deferred (YAGNI until a partner asks).

## File-layout decision

`custodian/priority.py` moves to `signals/priority.py`. It's a signal computation, not a custodian-internal concern, and the priority-consumer site (`custodian/sensors/consensus.py`) imports it as a peer. One-line import shim left at `custodian/priority.py` for back-compat in case anything external references it.

## Punted (not in scope here)

- Memgraph DR / snapshots (separate concern; raise after fundraise).
- Cost tracking — separate brainstorm/spec, next-up. Note: `app/cost/emitter.py` + `app/telemetry/cost_drain.py` exist in prototype (XADD per-event with a single drain writing to `cost_ledger_hot`); cost-tracking is a known-shape port, not greenfield.
- Dashboard / admin UI to surface heat scores and cluster tiers. UI deferred to v1.0+.
- Per-silo configurability of any signal constant.
- Validator refactor Phase C/D (already deferred elsewhere).

## Acceptance for this brainstorm

The decisions above are stable enough to write the spec. Open questions remaining are operational, not architectural:
- exact Dagster schedule cadence for heat (probably hourly per active silo, matching β2 fact-promotion pattern — confirm at Phase 2 kickoff)
- exact `freshness_weight` default — 0.3 chosen as starting point, may need tuning once we have query-quality telemetry

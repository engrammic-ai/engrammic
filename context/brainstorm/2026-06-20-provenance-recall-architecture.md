# Brainstorm: Provenance and Recall Architecture

**Mode**: architecture
**Date**: 2026-06-20
**Agents**: Pattern Analyst, Component Designer, Integration Analyst, Tradeoff Evaluator

---

## Summary

The system is architecturally sound (CQRS: brain transactions for writes, FusionRetriever for reads). The gaps are: (1) a small bug breaking provenance for file:// and urn:// evidence, (2) three orphaned features in dead code that belong as post-retrieval hooks, and (3) missing write-time dedup. The fixes are additive, not restructuring.

---

## Key Insights

### Pattern Analysis
- **CQRS is already the architecture** — don't fight it. Writes via `sage/transactions.py`, reads via `FusionRetriever`. Lost features belong as read-side hooks, not merged into the retriever.
- **Event sourcing via supersession chains** — the provenance model is sound, just incomplete for local refs.
- **W3C PROV-DM alignment** — `DERIVED_FROM` edges are the derivation relation. Stub nodes with `stub=true` are equivalent to `prov:hadPrimarySource` on an opaque entity.
- **TMS-style dependency propagation is missing** — when a Claim is superseded, ProposedBeliefs derived from it should be re-evaluated. Backlog item.

### Component Design
- **as_of is already partially wired** — `context_query.py:179` accepts it, routes to `temporal_query()`. Gap is MCP tool doesn't expose it and FusionRetriever path doesn't filter by it.
- **Evidence stub fix is exactly `_upsert_stub_for_local_ref()`** — mirrors existing `_upsert_document_for_uri()` for HTTP.
- **Hook insertion points are clear**: post-`FusionRetriever.retrieve()` in `context_query.py`, post-`_context_recall()` in `recall.py`.
- **urn: is blocked at MCP layer** — `models/mcp.py:96-108` rejects it before reaching evidence validator. Must add to allow-list.

### Integration Analysis
- **Fire-and-forget is the pattern for non-critical async work** — already used for access events (2s timeout, never blocks). Lazy synthesis should follow the same pattern.
- **SAGE synthesis is stable** (commit 7b6982ac) — lazy synthesis can depend on it, but gate with feature flag.
- **sage/recall.py has one late-import caller** in `services/context.py:1002` — verify before deleting.
- **Stub creation failure should hard-fail** — a claim with failed evidence stub is unprovenanced masquerading as evidenced. Better to reject than store a lie.

### Tradeoff Evaluation
- **Evidence stubs: Option A unconditionally** — deterministic UUID5, MERGE idempotent, `stub: true` flag for transparency.
- **Lazy synthesis: fire-and-forget, not inline-blocking** — 2s timeout destroys 250ms recall target.
- **Write dedup: soft block (Option B) with two-tier thresholds** — 0.85 warn, 0.92 require acknowledgment.
- **sage/recall.py: delete and port** — no production callers, features belong as hooks.

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Evidence stubs | Create nodes for file:// and urn:// | Consistent with HTTP, preserves provenance chain |
| urn: validation | Add to MCP model allow-list | Currently rejected before reaching validator |
| Lazy synthesis | Fire-and-forget with `synthesis_pending` flag | Protects recall latency target |
| Write dedup | Soft block at 0.92, warn at 0.85 | Balances friction vs garbage prevention |
| Belief hints | On-demand (`include_hints=true`) | Avoid noise until accuracy validated |
| sage/recall.py | Delete after porting features to hooks | Zero production callers |
| Stub failure | Hard-fail the write | Unprovenanced claim is worse than rejected write |
| Dedup failure | Degrade gracefully | Custodian catches duplicates later |

---

## Implementation Priority

| # | Task | Effort | Impact | Dependencies |
|---|------|--------|--------|--------------|
| 1 | Evidence stub nodes + urn: allow-list | 45 min | Fixes broken provenance | None |
| 2 | as_of temporal filter | 2-3h | Unlocks time-travel queries | None |
| 3 | Write-time semantic dedup | 3-4h | Prevents garbage accumulation | None |
| 4 | Lazy synthesis (fire-and-forget) | 3-4h | Auto-belief formation | SAGE stable |
| 5 | Belief candidate hints | 4-5h | Agent steering | On-demand only |
| 6 | Delete sage/recall.py | 30 min | Removes dead code | After #4-5 |

**Total: ~14-18 hours**

---

## Component Flow (Post-Fix)

```
WRITE PATH
==========
learn(content, evidence=["file://...", "urn:isbn:..."])
  |
  v
models/mcp.py:EvidenceRef.validate_ref_format()  -- now allows urn:
  |
  v
services/evidence.py:EvidenceValidator.validate()
  |-- http(s):// -> _upsert_document_for_uri() -> node_id
  |-- file://   -> _upsert_stub_for_local_ref() -> node_id  [FIX]
  |-- urn:      -> _upsert_stub_for_local_ref() -> node_id  [FIX]
  |-- node:     -> _validate_node_ref() -> node_id
  |
  v
sage/transactions.py:store_claim()
  |-- CREATE (:Claim)
  |-- CREATE (:Claim)-[:DERIVED_FROM]->(:Document {stub: true})
  |
  v
Provenance chain intact


READ PATH
=========
recall(query, as_of="2026-06-15")
  |
  v
FusionRetriever.retrieve()  -- 4-channel search
  |
  v
apply_epistemic_fusion()    -- confidence/conflict scoring
  |
  v
apply_temporal_filter()     -- [NEW HOOK] filter by as_of
  |
  v
maybe_trigger_lazy_synthesis()  -- [NEW HOOK] fire-and-forget
  |
  v
detect_epistemic_hints()    -- [NEW HOOK] if include_hints=true
  |
  v
{results, synthesis_pending, hints}
```

---

## Open Questions

1. **Lazy synthesis default** — off until SAGE synthesis validated in beta?
2. **Dedup threshold tuning** — 0.85/0.92 are starting points, need empirical data
3. **as_of + chain walk** — post-retrieval filter sufficient, or need exact historical state via SUPERSEDES walk?
4. **Stale-belief invalidation** — when Claim superseded, should dependent ProposedBeliefs be re-queued? (backlog)

---

## Related Plans

- `context/plans/2026-06-20-evidence-stub-nodes.md` — ready to implement
- `context/plans/2026-06-20-retrieval-remaining-work.md` — consolidated retrieval gaps
- `context/plans/2026-06-20-recall-epistemic-hooks.md` — as_of, lazy synthesis, hints

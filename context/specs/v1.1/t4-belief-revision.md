# T4: Belief Revision (Wisdom → Wisdom)

**Status:** Draft
**Priority:** P1
**Roadmap:** [v1.1-roadmap.md](../../plans/v1.1-roadmap.md)
**Depends on:** T3 (Belief Synthesis), Pattern Nodes

## Summary

Transition T4 revises a Belief when the underlying fact distribution shifts past a threshold. Unlike supersession (which replaces), revision creates a new Belief version while preserving the audit chain.

From spec (`03-transitions.md`):
> Wisdom -> Wisdom (revise): distribution shift >= M% since last synthesis

## Trigger Predicate

A Belief is eligible for revision when:
1. New facts have been added to its source cluster since synthesis
2. The semantic shift between old and new fact distributions exceeds threshold M%
3. No revision has occurred within cooldown period (prevent thrashing)

Semantic shift calculation:
- Compute centroid embedding of facts at synthesis time (stored on Belief)
- Compute current centroid of cluster facts
- If cosine distance > M% (default 15%), trigger revision

## Execution

1. **Shift detection:** Dagster sensor compares stored vs current cluster centroids
2. **Revision synthesis:** LLM re-synthesizes Belief from updated fact set
3. **Supersession:** Create new Belief with `SUPERSEDES` edge to old, `reason: 'evidence_shift'`
4. **Centroid update:** Store new centroid embedding on revised Belief

```cypher
(:Belief {id: "new", ...})-[:SUPERSEDES {
  reason: "evidence_shift",
  shift_magnitude: 0.23,
  created_at: datetime
}]->(:Belief {id: "old", ...})
```

Old Belief remains queryable for audit and `as_of` temporal queries.

## Schema Additions

Belief node gains:
```
centroid_embedding: list[float]   // cluster centroid at synthesis time
last_revision_check: datetime     // for cooldown
revision_count: int               // how many times revised
```

## Scoring Impact

From spec:
> wisdom_status in {active, stale}; stale = 0.1x multiplier

After revision:
- New Belief: `wisdom_status: active`
- Old Belief: `wisdom_status: stale` (0.1x scoring multiplier)

Stale beliefs are still returned in `as_of` queries and provenance traces.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BELIEF_REVISION_THRESHOLD` | 0.15 | Cosine distance threshold (15%) |
| `BELIEF_REVISION_COOLDOWN` | 7d | Minimum time between revisions |
| `BELIEF_MIN_NEW_FACTS` | 2 | Minimum new facts before checking shift |

## MCP Surface

No new tools. Revision is automatic (Dagster-driven).

Debug/admin: `context_belief_history(subject)` already shows supersession chains.

## Open Questions

1. **Threshold tuning:** Is 15% the right default? Should it be per-silo configurable?
2. **Partial revision:** If only part of a belief is invalidated, split into two beliefs?
3. **Cascade:** If Belief A references Belief B and B is revised, should A be flagged for review?
4. **Pattern interaction:** Do patterns trigger revision, or only facts?

## Out of Scope

- T3 (initial synthesis) — separate spec
- Manual belief editing — beliefs are system-synthesized, not user-editable
- Belief deletion — beliefs are superseded, not deleted

## Done Criteria

- [ ] Centroid embedding stored on Belief at synthesis time
- [ ] Dagster sensor for shift detection
- [ ] Revision logic: re-synthesize + SUPERSEDES edge
- [ ] Old belief marked `wisdom_status: stale`
- [ ] Configuration for threshold/cooldown
- [ ] `context_belief_history` shows revision chain
- [ ] Integration test: synthesize belief → add facts → trigger revision → verify chain

## References

- Transitions spec: `../primitives/docs/03-transitions.md` (T4)
- Layers spec: `../primitives/docs/02-layers.md` (Wisdom scoring)
- Supersession in Knowledge layer: `src/context_service/custodian/supersession.py`

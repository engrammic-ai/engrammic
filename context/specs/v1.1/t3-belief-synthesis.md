# T3: Belief Synthesis (Fact Cluster → Belief)

**Status:** Draft
**Priority:** P0
**Roadmap:** [v1.1-roadmap.md](../../plans/v1.1-roadmap.md)

## Summary

Transition T3 promotes a cluster of related Facts into a synthesized Belief. This is the Knowledge → Wisdom transition that enables the system to form higher-order understanding from accumulated evidence.

## Trigger Predicate

From spec (`03-transitions.md`):
> cluster density >= N AND no current Belief covers it

Operationally:
- Custodian clustering job produces Leiden clusters of content nodes
- When a cluster reaches density threshold (N facts with high inter-similarity), check if an existing Belief already covers the cluster's subject
- If no covering Belief exists, trigger synthesis

## Execution

1. **Cluster detection:** Dagster sensor monitors cluster metadata for density threshold
2. **Coverage check:** Query existing Beliefs by subject overlap (embedding similarity to cluster centroid)
3. **Synthesis prompt:** LLM summarizes the fact cluster into a Belief statement
4. **Node creation:** Create `:Belief` node with `SYNTHESIZED_FROM` edges to source Facts
5. **Provenance:** Belief carries `created_at`, `evidence_count`, `confidence` (derived from fact confidences)

## Schema

```cypher
(:Belief {
  id: string,
  content: string,
  silo_id: string,
  confidence: float,
  evidence_count: int,
  created_at: datetime,
  valid_from: datetime,
  valid_to: datetime | null
})-[:SYNTHESIZED_FROM]->(:Fact)
```

Minimum `SYNTHESIZED_FROM` edges: N (the density threshold, default 3).

## Scoring

From spec (`02-layers.md`):
> similarity x evidence_strength x underlying_fact_recency x proximity x wisdom_status_multiplier

- `evidence_strength` = avg confidence of source facts
- `underlying_fact_recency` = freshest source fact timestamp
- `wisdom_status` in {active, stale}; stale = 0.1x multiplier

## MCP Surface

No new tool. Beliefs are returned by `context_query` when layer filter includes Wisdom.

Optional: `context_synthesize(cluster_id)` to force synthesis of a specific cluster (admin/debug).

## Open Questions

1. **Density threshold N:** What's the right default? 3 facts? 5? Configurable per silo?
2. **Subject extraction:** How do we determine what "subject" a cluster covers for coverage checking?
3. **Belief merging:** If two clusters produce overlapping Beliefs, do we merge or keep both?
4. **Incremental updates:** When new facts join a cluster, do we revise the Belief (T4) or re-synthesize?

## Out of Scope

- T4 (Belief revision) — separate spec
- Pattern detection — separate spec (patterns emerge from belief clusters)
- Auto-scheduling synthesis — initially manual trigger via Dagster

## Done Criteria

- [ ] Dagster asset for belief synthesis with cluster density sensor
- [ ] `:Belief` node creation with `SYNTHESIZED_FROM` edges
- [ ] Coverage check query (no duplicate beliefs for same subject)
- [ ] Beliefs returned in `context_query` results
- [ ] Integration test: ingest facts → cluster → synthesize → query belief

## References

- Transitions spec: `../primitives/docs/03-transitions.md` (T3)
- Layers spec: `../primitives/docs/02-layers.md` (Wisdom)
- Clustering service: `src/context_service/clustering/service.py`

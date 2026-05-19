# Pattern Nodes

**Status:** Draft
**Priority:** P1
**Roadmap:** [v1.1-roadmap.md](../../plans/v1.1-roadmap.md)
**Depends on:** T3 (Belief Synthesis)

## Summary

`:Pattern` is a Wisdom-layer node type representing recurring shapes detected across Facts or Beliefs. Patterns are structural observations ("X tends to follow Y") rather than synthesized judgments (Beliefs).

From spec (`02-layers.md`):
> `:Pattern` — a recurring shape detected across Facts

## Pattern vs Belief

| Aspect | Belief | Pattern |
|--------|--------|---------|
| Nature | Synthesized judgment | Structural observation |
| Example | "The auth system is reliable" | "Auth failures spike after deploys" |
| Confidence | Evidence-weighted | Frequency-weighted |
| Revision trigger | Evidence shift | Frequency change |

Beliefs answer "what is true?" Patterns answer "what tends to happen?"

## Detection Approaches

### Option A: Rule-based (v1.1)

Predefined pattern templates:
- **Temporal correlation:** Event A precedes Event B within window W
- **Co-occurrence:** Facts X and Y frequently appear in same cluster
- **Causal chain:** A CAUSES B CAUSES C (from CAUSES edges)

Pro: Predictable, explainable. Con: Limited vocabulary.

### Option B: LLM-detected (v1.2+)

Prompt LLM to identify patterns across fact summaries:
> "Given these 20 facts about deployment practices, identify recurring patterns."

Pro: Flexible, discovers novel patterns. Con: Harder to validate, more expensive.

**Recommendation:** Start with Option A (rule-based) for v1.1, add Option B later.

## Schema

```cypher
(:Pattern {
  id: string,
  pattern_type: string,       // "temporal_correlation" | "co_occurrence" | "causal_chain"
  description: string,        // human-readable pattern statement
  silo_id: string,
  frequency: int,             // how many times observed
  confidence: float,          // statistical confidence
  first_observed: datetime,
  last_observed: datetime,
  created_at: datetime
})-[:OBSERVED_IN]->(:Fact|:Belief|:Event)
```

`OBSERVED_IN` edges link to the nodes where the pattern was detected.

## Detection Pipeline

1. **Trigger:** Dagster sensor on new Facts/Beliefs (batch, not real-time)
2. **Template matching:** For each pattern type, run detection query
3. **Deduplication:** Check if pattern already exists (same type + same subjects)
4. **Creation/Update:** Create new Pattern or increment frequency on existing

Example detection query (temporal correlation):
```cypher
MATCH (a:Fact)-[:DERIVED_FROM]->(d:Document)
MATCH (b:Fact)-[:DERIVED_FROM]->(d)
WHERE a.created_at < b.created_at
  AND duration.between(a.created_at, b.created_at) < duration('PT1H')
  AND a.subject <> b.subject
WITH a.subject AS subject_a, b.subject AS subject_b, count(*) AS freq
WHERE freq >= 3
RETURN subject_a, subject_b, freq
```

## Scoring

Patterns are scored for retrieval:
> similarity x frequency x recency x confidence

- `frequency` = observation count (log-scaled)
- `recency` = time since last observation
- `confidence` = statistical significance of the pattern

## MCP Surface

Patterns returned by `context_query` when layer filter includes Wisdom.

Optional (v1.2): `context_patterns(subject)` — list patterns involving a subject.

## Open Questions

1. **Pattern types:** What's the initial vocabulary? Just the three listed?
2. **Minimum frequency:** How many observations before creating a Pattern? 3? 5?
3. **Pattern decay:** Do patterns decay if not re-observed? Or persist indefinitely?
4. **Cross-belief patterns:** Can patterns link Beliefs, or only Facts?

## Out of Scope

- LLM-detected patterns (v1.2+)
- Pattern-triggered actions (e.g., "when this pattern appears, alert")
- User-defined pattern templates

## Done Criteria

- [ ] `:Pattern` node schema with `pattern_type` enum
- [ ] Detection queries for 2-3 pattern types
- [ ] Dagster asset for pattern detection (daily schedule)
- [ ] `OBSERVED_IN` edges to source nodes
- [ ] Patterns returned in `context_query` Wisdom results
- [ ] Integration test: create correlated facts → detect pattern → query pattern

## References

- Layers spec: `../primitives/docs/02-layers.md` (Wisdom)
- Clustering for co-occurrence: `src/context_service/clustering/service.py`

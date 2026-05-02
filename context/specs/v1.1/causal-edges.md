# Causal Edges (CAUSES / CORROBORATES)

**Status:** Draft
**Priority:** P1
**Roadmap:** [v1.1-roadmap.md](../../plans/v1.1-roadmap.md)

## Summary

`CAUSES` and `CORROBORATES` are semantic edge types defined in `CITEEdgeType` but not yet wired into extraction or write paths. This spec covers adding them to the extraction vocabulary and creating appropriate write paths.

From `primitives.schema.CITEEdgeType`:
```python
CAUSES = "CAUSES"           # causal relationship
CORROBORATES = "CORROBORATES"  # supporting evidence relationship
```

## Current State

- Edges defined in `primitives.schema.CITEEdgeType`
- `extraction/models.py:RelationshipType` has `CAUSES` as a local enum (LLM extraction vocabulary)
- No write path in `engine/` or `db/queries.py` creates these edges
- No extraction prompt elicits causal or corroborating relationships

## CAUSES Edge

**Semantics:** Directional causal relationship. A causes B.

**Source → Target:**
- `:Fact` → `:Fact` (fact A implies/causes fact B)
- `:Event` → `:Event` (event A triggered event B)
- `:Claim` → `:Claim` (claim A leads to claim B)

**Properties:**
```cypher
[:CAUSES {
  confidence: float,      // how confident in the causal link
  mechanism: string?,     // optional: how A causes B
  created_at: datetime,
  extracted_from: string  // source passage/document id
}]
```

**Extraction prompt addition:**
```
Identify causal relationships: if statement A implies or causes statement B,
extract as (A)-[CAUSES]->(B). Include confidence and mechanism if stated.
```

## CORROBORATES Edge

**Semantics:** Supporting evidence relationship. A strengthens belief in B.

**Source → Target:**
- `:Fact` → `:Fact` (fact A supports fact B)
- `:Fact` → `:Belief` (fact A supports belief B)
- `:Claim` → `:Claim` (claim A aligns with claim B)

**Properties:**
```cypher
[:CORROBORATES {
  strength: float,        // how strongly A supports B (0-1)
  created_at: datetime,
  extracted_from: string
}]
```

**Extraction prompt addition:**
```
Identify supporting evidence: if statement A provides evidence for or supports
statement B, extract as (A)-[CORROBORATES]->(B). Include strength (weak/moderate/strong).
```

## Implementation

### 1. Extraction Vocabulary

Update `extraction/prompts.py` to include CAUSES and CORROBORATES in relationship extraction:

```python
RELATIONSHIP_TYPES = """
- CAUSES: A implies or leads to B (directional causation)
- CORROBORATES: A provides evidence for or supports B
- REFERENCES: A mentions or cites B
- SUPERSEDES: A replaces B (for contradictions)
"""
```

### 2. Extraction Models

`extraction/models.py:RelationshipType` already has CAUSES. Add CORROBORATES:

```python
class RelationshipType(str, Enum):
    CAUSES = "CAUSES"
    CORROBORATES = "CORROBORATES"
    REFERENCES = "REFERENCES"
    # ...
```

### 3. Write Path

Add to `db/queries.py`:

```python
CREATE_CAUSES_EDGE = f"""
MATCH (a {{id: $source_id, silo_id: $silo_id}})
MATCH (b {{id: $target_id, silo_id: $silo_id}})
CREATE (a)-[:{CITEEdgeType.CAUSES.value} {{
  confidence: $confidence,
  mechanism: $mechanism,
  created_at: datetime(),
  extracted_from: $extracted_from
}}]->(b)
"""

CREATE_CORROBORATES_EDGE = f"""
MATCH (a {{id: $source_id, silo_id: $silo_id}})
MATCH (b {{id: $target_id, silo_id: $silo_id}})
CREATE (a)-[:{CITEEdgeType.CORROBORATES.value} {{
  strength: $strength,
  created_at: datetime(),
  extracted_from: $extracted_from
}}]->(b)
"""
```

### 4. Link Tool Support

`context_link` already validates edge types against `CITEEdgeType`. Once CAUSES/CORROBORATES are in the enum, they'll be linkable.

## Retrieval Impact

When traversing with `context_graph`:
- CAUSES edges indicate causal chains (useful for "why did X happen?")
- CORROBORATES edges indicate evidence strength (useful for "how confident are we in X?")

Consider adding edge-type filtering to `context_graph`:
```python
context_graph(node_id, depth=2, edge_types=["CAUSES"])  # causal chain only
```

## Open Questions

1. **Extraction accuracy:** How well do LLMs extract causal relationships? Need eval.
2. **Transitivity:** If A CAUSES B and B CAUSES C, do we infer A CAUSES C?
3. **Confidence aggregation:** If multiple sources say A CORROBORATES B, how do we combine?
4. **Negative causation:** How to represent "A prevents B"? Separate edge type?

## Out of Scope

- Causal inference algorithms (Pearl-style do-calculus)
- Automatic causal chain summarization
- Contradiction detection via corroboration conflicts

## Done Criteria

- [ ] `CORROBORATES` added to `extraction/models.py:RelationshipType`
- [ ] Extraction prompts updated to elicit CAUSES/CORROBORATES
- [ ] Write queries in `db/queries.py`
- [ ] `context_link` supports both edge types
- [ ] Integration test: extract causal claim → verify CAUSES edge
- [ ] Integration test: extract supporting evidence → verify CORROBORATES edge

## References

- Edge types: `primitives/src/primitives/schema/edges.py`
- Extraction models: `src/context_service/extraction/models.py`
- Current extraction prompts: `src/context_service/extraction/prompts.py`

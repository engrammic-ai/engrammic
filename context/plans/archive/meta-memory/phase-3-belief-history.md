# Phase 3: Belief History

> "How has my understanding of X evolved?" — track belief changes over time.

## Goal

Enable agents to see the evolution of beliefs about a subject, showing how facts have been created, revised, and superseded.

## User Story

```
Agent: context_belief_history("OAuth token expiry")
→ Timeline:
  - 2026-03-01: "OAuth tokens expire in 7 days" (confidence: 0.85)
  - 2026-04-15: Superseded by "OAuth tokens expire in 30 days" (confidence: 0.92)
    Reason: security-policy-v2.md contradicted previous
  - Current: "OAuth tokens expire in 30 days"
```

## MCP Tool

### `context_belief_history`

**Input**:
```json
{
  "subject": "OAuth token expiry",  // semantic query or entity ID
  "limit": 20
}
```

**Output**:
```json
{
  "subject": "OAuth token expiry",
  "timeline": [
    {
      "node_id": "fact-old",
      "content": "OAuth tokens expire in 7 days",
      "confidence": 0.85,
      "valid_from": "2026-03-01T00:00:00Z",
      "valid_to": "2026-04-15T00:00:00Z",
      "status": "superseded",
      "superseded_by": "fact-new"
    },
    {
      "node_id": "fact-new",
      "content": "OAuth tokens expire in 30 days",
      "confidence": 0.92,
      "valid_from": "2026-04-15T00:00:00Z",
      "valid_to": null,
      "status": "current",
      "superseded_by": null
    }
  ],
  "summary": {
    "total_versions": 2,
    "first_belief": "2026-03-01T00:00:00Z",
    "last_change": "2026-04-15T00:00:00Z",
    "confidence_trend": "increasing"
  }
}
```

## Implementation

### Subject Identification

Challenge: How do we know two facts are "about the same thing"?

Options:
1. **Entity ID match**: Facts with same `subject_id` field
2. **Predicate match**: Facts with same `(subject, predicate)` tuple
3. **Embedding similarity**: Semantically similar facts (expensive)
4. **Supersession chain**: Follow SUPERSEDES edges (most reliable)

**Recommended**: Start with supersession chains (Phase 3a), add semantic grouping later (Phase 3b).

### Cypher Query

```cypher
// Find all facts in a supersession chain
MATCH path = (current:Fact)-[:SUPERSEDES*0..10]->(ancestor:Fact)
WHERE current.id = $start_id OR ancestor.id = $start_id
WITH collect(nodes(path)) AS all_nodes
UNWIND all_nodes AS node_list
UNWIND node_list AS n
RETURN DISTINCT n
ORDER BY n.valid_from ASC
```

### Code Location

- `src/context_service/mcp/tools/belief_history.py` — new tool
- `src/context_service/engine/history.py` — traversal and aggregation
- `src/context_service/db/queries.py` — add `GET_SUPERSESSION_CHAIN`

### Response Schema

```python
@dataclass
class BeliefState:
    node_id: str
    content: str
    confidence: float
    valid_from: datetime
    valid_to: datetime | None
    status: Literal["current", "superseded"]
    superseded_by: str | None

@dataclass
class BeliefHistorySummary:
    total_versions: int
    first_belief: datetime
    last_change: datetime
    confidence_trend: Literal["increasing", "decreasing", "stable", "volatile"]

@dataclass
class BeliefHistory:
    subject: str
    timeline: list[BeliefState]
    summary: BeliefHistorySummary
```

## Edge Cases

1. **No supersession chain**: Single fact with no history — return single-item timeline
2. **Branching supersession**: Fact A superseded by both B and C — return both branches
3. **Cyclic supersession**: Should not happen, but guard against infinite loops
4. **Subject not found**: Return empty timeline with explanation

## Testing

```python
def test_single_fact_no_history():
    """Fact with no supersession returns single-item timeline"""
    
def test_linear_supersession_chain():
    """A → B → C returns ordered timeline"""
    
def test_branching_supersession():
    """A superseded by both B and C"""
    
def test_confidence_trend_calculation():
    """Summary correctly identifies increasing/decreasing trend"""
```

## Effort Estimate

| Task | Estimate |
|------|----------|
| Supersession traversal query | 3 hours |
| History aggregation logic | 3 hours |
| MCP tool | 2 hours |
| Summary calculation | 2 hours |
| Tests | 3 hours |
| **Total** | **13 hours** |

## Dependencies

- Phase 1 (provenance) for understanding edge relationships
- SUPERSEDES edges must be created on supersession (already implemented)

## Success Criteria

- [ ] Agent can call `context_belief_history(subject)`
- [ ] Returns ordered timeline of belief evolution
- [ ] Shows supersession relationships
- [ ] Calculates summary statistics (trend, version count)

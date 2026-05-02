# Phase 4: Reflection

> Agent stores observations about its own cognition.

## Goal

Enable agents to create and retrieve meta-observations — thoughts about their own beliefs, confidence changes, and epistemic state.

## User Story

```
Agent notices its belief changed:
  context_reflect(
    observation="My belief about token expiry changed significantly after reading the new security policy",
    about=["fact-old", "fact-new", "doc-policy"]
  )

Later, agent or user queries:
  context_get_reflections("fact-new")
  → "My belief about token expiry changed significantly..."
```

## Why This Matters

Without reflection:
- Agent has beliefs but no awareness of having them
- No record of "I was surprised by X" or "I noticed Y"
- Debugging agent behavior requires external logging

With reflection:
- Agent can record metacognitive observations
- "I was wrong about X, here's why"
- "My confidence in Y decreased because Z"
- Enables learning from epistemic history

## New Node Type

### `:MetaObservation`

```cypher
CREATE (m:MetaObservation {
  id: "meta-123",
  content: "My belief about token expiry changed significantly",
  observation_type: "belief_change",  // enum
  confidence: 0.9,                     // how confident agent is in this observation
  created_at: datetime(),
  agent_id: "agent-456",
  silo_id: "silo-789"
})
```

### Observation Types

| Type | Meaning |
|------|---------|
| `belief_change` | Agent noticed a belief was superseded |
| `confidence_shift` | Agent noticed confidence changed |
| `contradiction` | Agent noticed conflicting information |
| `uncertainty` | Agent noticed high uncertainty |
| `correction` | Agent acknowledges previous error |
| `insight` | Agent formed a new understanding |

### Edge Type

```cypher
(m:MetaObservation)-[:ABOUT]->(n:Fact|Claim|Document)
```

A single MetaObservation can be ABOUT multiple nodes.

## MCP Tools

### `context_reflect`

**Input**:
```json
{
  "observation": "My belief about token expiry changed significantly after reading the new security policy",
  "observation_type": "belief_change",  // optional, defaults to "insight"
  "about": ["fact-old", "fact-new", "doc-policy"],
  "confidence": 0.9  // optional
}
```

**Output**:
```json
{
  "meta_observation_id": "meta-123",
  "created_at": "2026-04-27T10:00:00Z",
  "linked_to": ["fact-old", "fact-new", "doc-policy"]
}
```

### `context_get_reflections`

**Input**:
```json
{
  "node_id": "fact-new",  // optional — get reflections about this node
  "limit": 10,
  "observation_type": null  // optional filter
}
```

**Output**:
```json
{
  "reflections": [
    {
      "meta_observation_id": "meta-123",
      "content": "My belief about token expiry changed significantly",
      "observation_type": "belief_change",
      "confidence": 0.9,
      "created_at": "2026-04-27T10:00:00Z",
      "about": ["fact-old", "fact-new", "doc-policy"]
    }
  ]
}
```

## Implementation

### Code Location

- `src/context_service/mcp/tools/reflect.py` — new tools
- `src/context_service/engine/reflection.py` — storage and retrieval logic
- `src/context_service/db/queries.py` — add `CREATE_META_OBSERVATION`, `GET_REFLECTIONS`
- `src/context_service/db/schema.py` — add `MetaObservation` label and `ABOUT` edge
- `primitives/schema/labels.py` — add `MetaObservation` to label enum

### Cypher Queries

```cypher
// Create reflection
CREATE (m:MetaObservation {
  id: $id,
  content: $content,
  observation_type: $type,
  confidence: $confidence,
  created_at: datetime(),
  agent_id: $agent_id,
  silo_id: $silo_id
})
WITH m
UNWIND $about_ids AS about_id
MATCH (n {id: about_id})
CREATE (m)-[:ABOUT]->(n)
RETURN m

// Get reflections about a node
MATCH (m:MetaObservation)-[:ABOUT]->(n {id: $node_id})
RETURN m
ORDER BY m.created_at DESC
LIMIT $limit
```

### Schema

```python
class ObservationType(StrEnum):
    BELIEF_CHANGE = "belief_change"
    CONFIDENCE_SHIFT = "confidence_shift"
    CONTRADICTION = "contradiction"
    UNCERTAINTY = "uncertainty"
    CORRECTION = "correction"
    INSIGHT = "insight"

@dataclass
class MetaObservation:
    id: str
    content: str
    observation_type: ObservationType
    confidence: float
    created_at: datetime
    agent_id: str
    about: list[str]  # node IDs
```

## Open Questions

### 1. Auto-generation

Should the system auto-generate meta-observations?

| Trigger | Auto-observation |
|---------|------------------|
| Supersession | "Belief about X was updated" |
| Confidence drop | "Confidence in X decreased from 0.9 to 0.6" |
| Contradiction detected | "Conflicting information about X" |

**Recommendation**: Start with explicit reflection only. Auto-generation adds noise and complexity.

### 2. Retention

Do meta-observations decay?

Options:
- Never decay (persist indefinitely)
- Decay with Memory layer rules
- Agent-controlled deletion

**Recommendation**: No decay. Meta-observations are valuable for audit trails.

### 3. Visibility

Can other agents see reflections?

Options:
- Agent-private (only creating agent can read)
- Silo-shared (all agents in silo can read)
- Selective sharing (agent chooses)

**Recommendation**: Silo-shared by default. Reflections about shared facts should be visible.

## Testing

```python
def test_create_reflection():
    """Agent can create meta-observation linked to nodes"""
    
def test_get_reflections_by_node():
    """Retrieve reflections about a specific node"""
    
def test_reflection_types():
    """Different observation types are stored correctly"""
    
def test_multi_node_reflection():
    """Reflection can be ABOUT multiple nodes"""
```

## Effort Estimate

| Task | Estimate |
|------|----------|
| Schema additions | 2 hours |
| Cypher queries | 3 hours |
| Engine module | 4 hours |
| MCP tools | 3 hours |
| Tests | 4 hours |
| **Total** | **16 hours** |

## Dependencies

- Phases 1-3 not required, but recommended for understanding
- Schema changes require migration if data exists

## Success Criteria

- [ ] Agent can call `context_reflect(observation, about)`
- [ ] MetaObservation nodes are created with ABOUT edges
- [ ] Agent can retrieve reflections about any node
- [ ] Observation types are enforced
- [ ] Silo isolation is respected

# Phase 1: Provenance Queries

> "Why do I believe X?" — trace the citation chain from fact to source.

## Goal

Enable agents to query the provenance of any belief, returning the full chain of evidence from a Claim/Fact back to the source Document(s) it was extracted from.

## User Story

```
Agent: "OAuth tokens expire in 30 days"
User: "Where did you get that?"
Agent: context_provenance("fact-123")
→ Fact "OAuth tokens expire in 30 days" (confidence: 0.92)
  ← extracted from Claim "claim-456" (confidence: 0.88)
    ← cited in Document "security-policy.md" (source: internal wiki)
```

## MCP Tool

### `context_provenance`

**Input**:
```json
{
  "node_id": "fact-123"
}
```

**Output**:
```json
{
  "chain": [
    {
      "node_id": "fact-123",
      "type": "Fact",
      "content": "OAuth tokens expire in 30 days",
      "confidence": 0.92,
      "created_at": "2026-04-20T10:00:00Z"
    },
    {
      "node_id": "claim-456",
      "type": "Claim", 
      "content": "OAuth tokens expire in 30 days",
      "confidence": 0.88,
      "extracted_at": "2026-04-19T15:30:00Z",
      "extraction_method": "llm_extraction"
    },
    {
      "node_id": "doc-789",
      "type": "Document",
      "title": "security-policy.md",
      "source_uri": "https://wiki.example.com/security-policy",
      "ingested_at": "2026-04-19T14:00:00Z"
    }
  ],
  "edges": [
    {"from": "fact-123", "to": "claim-456", "type": "PROMOTED_FROM"},
    {"from": "claim-456", "to": "doc-789", "type": "REFERENCES"}
  ]
}
```

## Implementation

### Cypher Query

```cypher
MATCH path = (start)-[:PROMOTED_FROM|REFERENCES*1..5]->(end)
WHERE start.id = $node_id
RETURN path
```

### Code Location

- `src/context_service/mcp/tools/provenance.py` — new tool
- `src/context_service/engine/provenance.py` — traversal logic
- `src/context_service/db/queries.py` — add `GET_PROVENANCE_CHAIN`

### Schema

```python
@dataclass
class ProvenanceNode:
    node_id: str
    type: Literal["Fact", "Claim", "Document", "Passage"]
    content: str | None
    confidence: float | None
    created_at: datetime

@dataclass
class ProvenanceEdge:
    from_id: str
    to_id: str
    type: Literal["PROMOTED_FROM", "REFERENCES", "EXTRACTED_FROM"]

@dataclass
class ProvenanceChain:
    chain: list[ProvenanceNode]
    edges: list[ProvenanceEdge]
```

## Edge Cases

1. **No provenance found**: Return empty chain with explanation
2. **Circular references**: Limit traversal depth (max 5 hops)
3. **Multiple sources**: A claim can reference multiple documents — return all paths
4. **Deleted source**: Document was deleted but claim remains — note in response

## Testing

```python
def test_provenance_single_hop():
    """Claim → Document"""
    
def test_provenance_multi_hop():
    """Fact → Claim → Document"""
    
def test_provenance_multiple_sources():
    """Claim references 2 documents"""
    
def test_provenance_not_found():
    """Node exists but has no REFERENCES edges"""
```

## Effort Estimate

| Task | Estimate |
|------|----------|
| Cypher query | 1 hour |
| Engine module | 2 hours |
| MCP tool | 1 hour |
| Tests | 2 hours |
| **Total** | **6 hours** |

## Dependencies

- None — uses existing REFERENCES edges

## Success Criteria

- [ ] Agent can call `context_provenance(node_id)`
- [ ] Returns chain from Fact → Claim → Document
- [ ] Handles multi-hop and multi-source cases
- [ ] Returns empty chain gracefully when no provenance exists

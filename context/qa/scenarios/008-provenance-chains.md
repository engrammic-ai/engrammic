# Scenario: Provenance Chains

## Metadata

- **ID:** 008
- **Agents:** 2
- **Duration:** ~6 min
- **Silo:** (default)

## Setup

None

## Instructions

### Worker 1: Evidence Chain Builder

1. Store a source document (memory layer):
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="Research paper: 'Effects of sleep on learning consolidation' - Smith et al. 2024",
       tags=["source", "sleep-research"]
   )
   ```

2. Store a fact derived from the document (knowledge layer):
   ```
   mcp__engrammic__context_store(
       layer="knowledge",
       content="Sleep deprivation reduces memory consolidation efficiency by 40%",
       evidence=["node:<doc_id>"],
       source_type="document"
   )
   ```

3. Store another fact that builds on the first:
   ```
   mcp__engrammic__context_store(
       layer="knowledge",
       content="Students who sleep less than 6 hours show measurable learning deficits",
       evidence=["node:<fact1_id>"],
       source_type="agent"
   )
   ```

4. Create links to show derivation:
   ```
   mcp__engrammic__context_link(
       from_node="<fact2_id>",
       to_node="<fact1_id>",
       relationship="DERIVED_FROM"
   )
   ```

5. Report all node IDs and links created

### Worker 2: Provenance Tracer

1. Start from the leaf fact and trace provenance:
   ```
   mcp__engrammic__context_admin(
       action="provenance",
       ref="<fact2_id>"
   )
   ```

2. Verify the chain:
   - fact2 -> fact1 -> source document
   - All nodes in chain are returned

3. Query with graph depth to see the full chain:
   ```
   mcp__engrammic__context_recall(
       node_ids=["<fact2_id>"],
       depth=2
   )
   ```

4. Report the provenance chain structure

## Success Criteria

- [ ] Source document stored in memory layer
- [ ] Fact 1 references document via evidence field
- [ ] Fact 2 references Fact 1 via evidence field
- [ ] DERIVED_FROM link exists between facts
- [ ] Provenance admin action returns complete chain
- [ ] Graph traversal at depth=2 reaches source document

## Notes

Tests provenance tracking:
- evidence field on knowledge layer
- DERIVED_FROM relationship type
- provenance admin action
- Graph traversal following evidence chains

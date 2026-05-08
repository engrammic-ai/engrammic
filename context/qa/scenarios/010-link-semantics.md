# Scenario: Link Semantics

## Metadata

- **ID:** 010
- **Agents:** 2
- **Duration:** ~6 min
- **Silo:** (default)

## Setup

None

## Instructions

### Worker 1: Relationship Builder

Create a knowledge graph with diverse relationship types:

1. Store base observations:
   ```
   # Observation A
   mcp__engrammic__context_store(layer="memory", content="Exercise increases heart rate", tags=["health"])
   
   # Observation B  
   mcp__engrammic__context_store(layer="memory", content="Elevated heart rate burns more calories", tags=["health"])
   
   # Observation C
   mcp__engrammic__context_store(layer="memory", content="Sedentary lifestyle linked to weight gain", tags=["health"])
   
   # Observation D
   mcp__engrammic__context_store(layer="memory", content="Some studies show exercise has minimal weight impact", tags=["health"])
   ```

2. Create varied relationship types:
   ```
   # CAUSES: A causes B
   mcp__engrammic__context_link(from_node="<A>", to_node="<B>", relationship="CAUSES")
   
   # SUPPORTS: B supports conclusion about exercise
   mcp__engrammic__context_link(from_node="<B>", to_node="<conclusion>", relationship="SUPPORTS")
   
   # CONTRADICTS: D contradicts the conclusion
   mcp__engrammic__context_link(from_node="<D>", to_node="<conclusion>", relationship="CONTRADICTS")
   
   # CORROBORATES: C corroborates B
   mcp__engrammic__context_link(from_node="<C>", to_node="<B>", relationship="CORROBORATES")
   
   # RELATED_TO: general association
   mcp__engrammic__context_link(from_node="<A>", to_node="<C>", relationship="RELATED_TO")
   ```

3. Store a conclusion node:
   ```
   mcp__engrammic__context_store(
       layer="knowledge",
       content="Regular exercise contributes to weight management",
       evidence=["node:<A>", "node:<B>"],
       source_type="agent"
   )
   ```

4. Report all nodes and edges

### Worker 2: Graph Analyzer

1. Traverse from conclusion to find supporting evidence:
   ```
   mcp__engrammic__context_recall(
       node_ids=["<conclusion_id>"],
       depth=2
   )
   ```

2. Identify contradicting nodes in the response

3. Verify edge types are preserved in traversal results

4. Report:
   - Which nodes SUPPORT the conclusion
   - Which nodes CONTRADICT it
   - The causal chain (CAUSES edges)

## Success Criteria

- [ ] All 5 relationship types created successfully
- [ ] CAUSES edge connects A -> B
- [ ] SUPPORTS edge connects B -> conclusion
- [ ] CONTRADICTS edge connects D -> conclusion
- [ ] CORROBORATES edge connects C -> B
- [ ] Graph traversal returns edges with relationship types
- [ ] Contradicting evidence identifiable in results

## Notes

Tests relationship semantics:
- CAUSES, SUPPORTS, CONTRADICTS, CORROBORATES, RELATED_TO
- Edge preservation in graph traversal
- Building argument graphs with supporting/contradicting evidence

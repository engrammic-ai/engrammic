# Scenario: Metacognition and Reflections

## Metadata

- **ID:** 005
- **Agents:** 3
- **Duration:** ~8 min
- **Silo:** (default)

## Setup

None (fresh session)

## Instructions

Research topic: **"Differences between feline and canine genetics"**

### Worker 1: Knowledge Builder

1. Store 4 observations to memory layer about cat/dog genetic differences:
   - Chromosome count (cats: 38, dogs: 78)
   - Domestication timeline differences
   - Dietary gene adaptations (carnivore vs omnivore)
   - Behavioral genetics (pack vs solitary)

2. Store 2 knowledge-layer facts synthesizing the observations:
   ```
   mcp__engrammic__context_store(
       layer="knowledge",
       content="<synthesized fact>",
       evidence=["node:<obs_id_1>", "node:<obs_id_2>"],
       source_type="agent"
   )
   ```

3. Report all node IDs

### Worker 2: Meta-Observer

1. Query for Worker 1's observations and facts
2. Store 3 meta-observations reflecting on the knowledge:
   ```
   mcp__engrammic__context_store(
       layer="meta",
       content="The chromosome count observation may be misleading without context about gene density",
       observation_type="uncertainty",
       about=["<node_id>"]
   )
   ```
   
   Types to use:
   - `uncertainty` - flag uncertain or incomplete knowledge
   - `connection` - note unexpected relationship between nodes
   - `gap` - identify missing information

3. Report meta-observation IDs

### Worker 3: Reflection Reviewer

1. Query the meta layer for reflections:
   ```
   mcp__engrammic__context_recall(
       query="uncertainty gap connection genetics",
       layers=["meta"]
   )
   ```

2. Query original nodes with reflections attached:
   ```
   mcp__engrammic__context_recall(
       node_ids=["<original_node_id>"],
       include_reflections=true
   )
   ```

3. Verify reflections are linked to their target nodes
4. Report findings

## Success Criteria

- [ ] Worker 1 created 4 observations + 2 facts
- [ ] Worker 2 created 3 meta-observations with different types
- [ ] Meta-observations have ABOUT edges to target nodes
- [ ] Reflections retrievable via include_reflections=true
- [ ] Meta layer queryable separately from memory/knowledge

## Notes

Tests the meta-memory system:
- MetaObservation node type
- ABOUT edges from meta to other layers
- include_reflections flag on recall
- Meta layer as cross-cutting concern

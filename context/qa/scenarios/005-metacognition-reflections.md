# Scenario: Metacognition and Reflections

## Metadata

- **ID:** 005
- **Agents:** 3
- **Duration:** ~8 min
- **Silo:** (default)

## Setup

None (fresh session)

## Background

Metacognition is not a separate layer. Reflections are Memory nodes with `memory_type="reflection"` and ABOUT edges linking to the nodes being reflected upon. This scenario tests that pattern.

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
   learn(
       content="<synthesized fact>",
       evidence=["node:<obs_id_1>", "node:<obs_id_2>"]
   )
   ```

3. Report all node IDs

### Worker 2: Meta-Observer

1. Query for Worker 1's observations and facts
2. Store 3 reflections as Memory nodes with `memory_type="reflection"`:
   ```
   remember(
       content="The chromosome count observation may be misleading without context about gene density",
       memory_type="reflection",
       about=["<node_id>"]
   )
   ```
   
   Reflection content types to cover:
   - Uncertainty - flag uncertain or incomplete knowledge
   - Connection - note unexpected relationship between nodes
   - Gap - identify missing information

3. Report reflection node IDs

### Worker 3: Reflection Reviewer

1. Query for reflections:
   ```
   recall(
       query="uncertainty gap connection genetics"
   )
   ```

2. Query original nodes with reflections attached:
   ```
   recall(
       node_ids=["<original_node_id>"],
       include_reflections=true
   )
   ```

3. Trace provenance of a fact to see its sources:
   ```
   trace(node_id="<fact_id>", direction="up")
   ```

4. Verify reflections are linked to their target nodes via ABOUT edges
5. Report findings

## Success Criteria

- [ ] Worker 1 created 4 observations + 2 facts (Claims promoted to Fact by corroboration)
- [ ] Worker 2 created 3 reflection Memory nodes
- [ ] Reflection nodes have ABOUT edges to target nodes
- [ ] Reflections retrievable via include_reflections=true
- [ ] trace() shows provenance chain for facts

## Notes

Tests metacognition as a cross-cutting capability:
- Reflections are Memory nodes with memory_type="reflection"
- ABOUT edges connect reflections to target nodes
- include_reflections flag surfaces reflections on recall
- trace() walks provenance chains (DERIVED_FROM, SYNTHESIZED_FROM, SUPERSEDES)

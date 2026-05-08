# Scenario: Reasoning Chains

## Metadata

- **ID:** 012
- **Agents:** 2
- **Duration:** ~8 min
- **Silo:** (default)

## Setup

None

## Instructions

### Worker 1: Reasoning Builder

1. Store supporting observations:
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="Premise: All mammals are warm-blooded",
       tags=["logic", "premise"]
   )
   
   mcp__engrammic__context_store(
       layer="memory",
       content="Premise: Dolphins are mammals",
       tags=["logic", "premise"]
   )
   ```

2. Create a reasoning chain (intelligence layer):
   ```
   mcp__engrammic__context_store(
       layer="intelligence",
       content="Therefore, dolphins are warm-blooded",
       steps=[
           {"step": 1, "reasoning": "Accepted premise: All mammals are warm-blooded", "confidence": 0.99},
           {"step": 2, "reasoning": "Accepted premise: Dolphins are mammals", "confidence": 0.99},
           {"step": 3, "reasoning": "By syllogistic logic: If all A are B, and C is A, then C is B", "confidence": 0.95},
           {"step": 4, "reasoning": "Conclusion: Dolphins are warm-blooded", "confidence": 0.95}
       ],
       confidence=0.95
   )
   ```

3. Link the chain to its premises:
   ```
   mcp__engrammic__context_link(
       from_node="<chain_id>",
       to_node="<premise1_id>",
       relationship="REFERENCES"
   )
   ```

4. Report chain ID and premise IDs

### Worker 2: Chain Analyzer

1. Fetch the reasoning chain with steps:
   ```
   mcp__engrammic__context_recall(
       node_ids=["<chain_id>"],
       include_steps=true
   )
   ```

2. Verify steps are returned in order

3. Close the reasoning session:
   ```
   mcp__engrammic__context_admin(
       action="close_session",
       ref="<chain_id>"
   )
   ```

4. Query for the chain after closing:
   ```
   mcp__engrammic__context_recall(
       query="dolphins warm-blooded reasoning",
       layers=["intelligence"]
   )
   ```

5. Report:
   - Steps retrieved correctly
   - Step ordering preserved
   - Session closure successful
   - Chain still queryable after closure

## Success Criteria

- [ ] Premises stored in memory layer
- [ ] Reasoning chain stored with 4 steps
- [ ] Steps include step number, reasoning, and confidence
- [ ] include_steps=true returns step array
- [ ] Steps are ordered correctly (1, 2, 3, 4)
- [ ] REFERENCES edges link chain to premises
- [ ] close_session completes without error
- [ ] Chain remains queryable after session close

## Notes

Tests intelligence layer and reasoning:
- ReasoningChain node type
- Structured steps with confidence
- include_steps flag on recall
- Session management (close_session)
- REFERENCES relationship to premises

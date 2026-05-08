# Scenario: Contradiction Detection

## Metadata

- **ID:** 007
- **Agents:** 2
- **Duration:** ~5 min
- **Silo:** (default)

## Setup

None (fresh session)

## Instructions

### Worker 1: Belief Creator

1. Store 2 base observations:
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="Study A found caffeine improves cognitive performance",
       tags=["caffeine", "cognition"]
   )
   ```

2. Create 2 contradictory WorkingHypotheses about the same topic:
   ```
   mcp__engrammic__context_store(
       layer="belief",
       content="Caffeine significantly improves short-term memory retention",
       confidence=0.75,
       about=["<obs_id>"],
       session_id="qa-007-session"
   )
   
   mcp__engrammic__context_store(
       layer="belief",
       content="Caffeine has no measurable effect on memory retention",
       confidence=0.70,
       about=["<obs_id>"],
       session_id="qa-007-session"
   )
   ```

3. Report hypothesis IDs

### Worker 2: Contradiction Checker

1. Query belief state for the session:
   ```
   mcp__engrammic__context_belief_state(session_id="qa-007-session")
   ```

2. Verify response includes:
   - Both hypotheses in working_hypotheses
   - potential_contradictions array with the pair
   - reflection_suggested flag

3. If contradictions detected, store a meta-observation:
   ```
   mcp__engrammic__context_store(
       layer="meta",
       content="Detected contradiction between caffeine memory hypotheses - need additional evidence",
       observation_type="contradiction",
       about=["<hyp_id_1>", "<hyp_id_2>"]
   )
   ```

4. Report findings

## Success Criteria

- [ ] Worker 1 created 2 observations + 2 contradictory hypotheses
- [ ] Both hypotheses reference the same observation(s)
- [ ] belief_state returns both hypotheses
- [ ] potential_contradictions contains the hypothesis pair
- [ ] reflection_suggested is true
- [ ] Meta-observation records the contradiction

## Notes

Tests contradiction detection in the belief layer:
- Pairwise contradiction detection via shared ABOUT targets
- reflection_suggested flag triggers agent attention
- Meta layer for recording detected issues

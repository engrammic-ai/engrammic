---
name: engrammic:belief-state
description: Query working hypotheses in a session. Use for "what hypotheses", "current beliefs", "session state".
allowed-tools:
  - mcp__engrammic__recall
---

# Belief State

Query the current state of working hypotheses in a reasoning session. Use this to take stock of what the agent currently believes before committing, updating, or reasoning further.

## When to use

- "What hypotheses are active?" / "what do I currently believe about..." / "session state"
- Before `crystallize`, to review which hypotheses are ready to commit
- Before `reason`, to avoid duplicating an existing working hypothesis
- When asked to summarize current beliefs on a topic

## Tool call

```
recall(
  query: "{topic or session context}",
  include_hypotheses: true
)
```

Returns active WorkingHypotheses alongside matching memory nodes. Use a descriptive query to scope results to the relevant reasoning thread.

## What comes next

After querying belief state, you might:
- `crystallize` - promote hypotheses that have enough support to become Commitments
- `update-belief` - revise a hypothesis whose content or confidence needs adjustment
- `reason` - continue reasoning over the surfaced hypotheses to reach a conclusion

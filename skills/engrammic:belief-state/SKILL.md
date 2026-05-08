---
name: engrammic:belief-state
description: Query working hypotheses in a session. Use for "what hypotheses", "current beliefs", "session state".
allowed-tools:
  - mcp__engrammic__context_belief_state
---

Query the current state of working hypotheses in a reasoning session.

```
context_belief_state(
  session_id: "{session_id}",
  include_resolved: false
)
```

Returns all active WorkingHypotheses. Set `include_resolved: true` to also see crystallized/rejected ones.

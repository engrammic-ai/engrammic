---
name: engrammic:crystallize
description: Promote hypotheses to commitments. Use for "commit to", "finalize belief", "crystallize".
allowed-tools:
  - mcp__engrammic__context_crystallize
---

Promote one or more WorkingHypotheses to Commitments in the wisdom layer.

```
context_crystallize(
  session_id: "{session_id}",
  node_ids: ["{hypothesis_node_ids}"],
  reasoning: "Why these hypotheses are now commitments"
)
```

Creates Commitment nodes linked to the original hypotheses via DERIVED_FROM.

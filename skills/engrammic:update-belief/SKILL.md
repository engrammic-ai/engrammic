---
name: engrammic:update-belief
description: Mutate a working hypothesis. Use for "revise hypothesis", "update confidence", "add evidence".
allowed-tools:
  - mcp__engrammic__context_update_belief
---

Update an existing WorkingHypothesis in place.

```
context_update_belief(
  node_id: "{hypothesis_node_id}",
  content: "{revised_content}",
  confidence: 0.85,
  add_evidence: ["{new_evidence_node_ids}"]
)
```

All fields except `node_id` are optional. Only provided fields are updated.

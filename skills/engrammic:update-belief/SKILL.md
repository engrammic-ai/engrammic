---
name: engrammic:update-belief
description: Mutate a working hypothesis. Use for "revise hypothesis", "update confidence", "add evidence".
allowed-tools:
  - mcp__engrammic__revise
---

# Update Belief

Update an existing WorkingHypothesis in place. Use this when new evidence or reasoning changes the content or confidence of a live hypothesis without replacing it entirely.

## When to use

- "Revise hypothesis..." / "update confidence on..." / "add evidence to..."
- New information arrived that strengthens or weakens an existing hypothesis
- You want to refine a hypothesis content without discarding and recreating it
- After `belief-state` surfaces a hypothesis that needs a correction

## Tool call

```
revise(
  node_id: "{hypothesis_node_id}",
  content: "{revised_content}",       # optional
  confidence: 0.85,                   # optional
  add_evidence: ["{new_evidence_node_ids}"]  # optional
)
```

All fields except `node_id` are optional. Only provided fields are updated.

## What comes next

After updating a belief, you might:
- `crystallize` - if the revised hypothesis now has enough support to commit
- `reflect` - if the update marks a significant shift in understanding worth recording to meta-memory
- `belief-state` - to confirm the hypothesis now reflects the intended state

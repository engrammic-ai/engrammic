---
name: engrammic:update-belief
description: Mutate a working hypothesis. Use for "revise hypothesis", "update confidence".
allowed-tools:
  - mcp__engrammic__revise
---

# Update Belief

Update an existing WorkingHypothesis in place. Use this when new evidence or reasoning changes the content or confidence of a live hypothesis without replacing it entirely.

## When to use

- "Revise hypothesis..." / "update confidence on..."
- New information arrived that strengthens or weakens an existing hypothesis
- You want to refine a hypothesis content without discarding and recreating it
- After `belief-state` surfaces a hypothesis that needs a correction

## Tool call

```
revise(
  belief_id: "{hypothesis_node_id}",
  confidence: 0.85,
  reason: "Why this revision is being made",
  content: "{revised_content}"  # optional
)
```

`belief_id`, `confidence`, and `reason` are required. `content` is optional (only provided if updating the hypothesis text).

## What comes next

After updating a belief, you might:
- `crystallize` - if the revised hypothesis now has enough support to commit
- `reflect` - if the update marks a significant shift in understanding worth recording to meta-memory
- `belief-state` - to confirm the hypothesis now reflects the intended state

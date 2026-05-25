---
name: engrammic:reflect
description: Store meta-cognitive observation. Use for "I was wrong", "update belief", "flag contradiction".
allowed-tools:
  - mcp__engrammic__reflect
---

# Reflect

Store a meta-cognitive observation about your own reasoning or beliefs. Use this when your understanding changes, when you spot a contradiction, or when you want to record that a prior belief was revised.

## When to use

- "I was wrong about..." / "I need to update my belief on..."
- You discovered new evidence that contradicts something already stored
- Your confidence in a claim has shifted significantly
- You want to record a key realization or insight for provenance
- After `trace` or `recall` reveals a contradiction between two stored nodes

## Tool call

```
reflect(
  observation: "{observation}",
  type: "{type}",
  about: ["{relevant_node_ids}"],
  confidence: 0.8  # optional
)
```

**type values:**
- `belief_change` - updating a prior belief
- `contradiction` - flagging conflicting information
- `uncertainty` - noting low confidence
- `insight` - recording a realization

## What comes next

After reflecting, you might:
- `update-belief` - if the reflection involves a live WorkingHypothesis that needs revision
- `connect` - link the new insight to the nodes it supersedes (`SUPERSEDES` relationship)
- `learn` - if the reflection produced a new verifiable claim with evidence

## Example workflow

1. `recall(query: "embedding model latency", layers: ["knowledge"])` - retrieve existing knowledge
2. `reflect(observation: "Prior claim of 200ms avg is wrong; new benchmarks show 480ms", type: "belief_change", about: ["{old_node_id}"])` - record the correction
3. `connect(from_node: "{new_node_id}", to_node: "{old_node_id}", relationship: "SUPERSEDES")` - mark the old node as superseded

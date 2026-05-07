---
name: engrammic:reflect
description: Store meta-cognitive observation. Use for "I was wrong", "update belief", "flag contradiction".
allowed-tools:
  - mcp__engrammic__context_store
---

Store a meta-cognitive observation about your own reasoning or beliefs.

```
context_store(
  content: "{observation}",
  layer: "meta",
  about: ["{relevant_node_ids}"],
  observation_type: "{type}",
  tags: ["meta", "{observation_type}", "{domain}"]
)
```

**observation_type values:**
- `belief_change` - updating a prior belief
- `contradiction` - flagging conflicting information
- `uncertainty` - noting low confidence
- `insight` - recording a realization

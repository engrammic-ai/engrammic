---
name: delta-prime:trace
description: Trace provenance chain for a belief. Use for "why do I believe", "where did this come from".
allowed-tools:
  - mcp__delta-prime__context_admin
---

Trace the citation/evidence chain for a node to understand where a belief came from.

```
context_admin(
  action: "provenance",
  ref: "{node_id}"
)
```

Returns the chain of evidence and sources that support the belief.

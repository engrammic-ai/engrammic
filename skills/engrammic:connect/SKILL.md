---
name: engrammic:connect
description: Link two concepts with a typed relationship. Use for "X relates to Y", "connect these".
allowed-tools:
  - mcp__engrammic__context_link
---

Create a typed relationship between two nodes.

```
context_link(
  from_node: "{source_node_id}",
  to_node: "{target_node_id}",
  relation_type: "{type}"
)
```

**Common relation_type values:**
- `SUPPORTS` - evidence supports a claim
- `CONTRADICTS` - evidence contradicts a claim
- `DERIVED_FROM` - conclusion derived from premises
- `RELATED_TO` - general association
- `SUPERSEDES` - newer belief replaces older

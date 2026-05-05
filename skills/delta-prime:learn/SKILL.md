---
name: delta-prime:learn
description: Store fact with evidence to knowledge layer. Use for "assert that", "we know that".
allowed-tools:
  - mcp__delta-prime__context_store
---

Store a fact with evidence. Facts enter the knowledge layer and may be promoted by the custodian.

```
context_store(
  content: "{claim}",
  layer: "knowledge",
  evidence: ["{source_node_ids_or_uris}"],
  source_type: "agent",  # or: document|user|external
  tags: ["{domain}", "{type}", "{specific}"]
)
```

Always provide evidence refs (node IDs or URIs). Always tag with 2-5 relevant tags.

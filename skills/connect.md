---
name: delta-prime:connect
description: Create a typed relationship between two concepts. Use when user says "link X to Y", "X supports Y", "X contradicts Y", "relate these", or wants to wire two stored nodes together.
allowed-tools:
  - mcp__delta-prime__context_recall
  - mcp__delta-prime__context_link
when_to_use: Any time two nodes need an explicit edge in the knowledge graph. Recall both nodes first to get their IDs, then create the link.
---

Link two concepts with a typed relationship.

**Example:** User says "link the Redis cache observation to the latency claim"
1. Recall both nodes to get IDs
2. Create typed edge

```
# 1. Recall both concepts
a = context_recall(silo_id: "{silo_id}", query: "{concept_a}")
b = context_recall(silo_id: "{silo_id}", query: "{concept_b}")

# 2. Create the link
context_link(
  silo_id: "{silo_id}",
  from_node: "{a_node_id}",
  to_node: "{b_node_id}",
  relationship: "{type}"
)
```

Relationship types: SUPPORTS, CONTRADICTS, DERIVED_FROM, REFERENCES, RELATED_TO, CAUSES, CORROBORATES, PREVENTS

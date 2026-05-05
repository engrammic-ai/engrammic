---
name: delta-prime:trace
description: Trace provenance of a belief through the reasoning chain. Use when user says "why do we believe", "where did that come from", "trace this back", "show me the evidence for", or wants to audit a conclusion.
allowed-tools:
  - mcp__delta-prime__context_recall
when_to_use: Epistemic audits — understanding how a stored belief, claim, or conclusion was formed. Uses graph traversal at depth >= 2.
---

Trace how a belief was formed by walking the provenance graph.

**Example:** User says "why do we believe the clustering service is bottlenecked on Leiden?"
1. Find the belief node
2. Walk its provenance edges at depth 2

```
# 1. Find the belief
result = context_recall(silo_id: "{silo_id}", query: "{belief}", layers: ["wisdom", "knowledge"])

# 2. Get provenance chain via graph traversal
context_recall(silo_id: "{silo_id}", node_ids: ["{belief_node_id}"], depth: 2)
```

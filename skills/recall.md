---
name: delta-prime:recall
description: Search and retrieve from epistemic memory. Use when user says "what do we know about", "look up", "search for", "find", "retrieve", or asks a question that might be answered from stored context.
allowed-tools:
  - mcp__delta-prime__context_recall
when_to_use: Any read from the context store — semantic search, node fetch by ID, or layer-filtered lookup. For provenance tracing, use trace.md instead.
---

Search and retrieve from epistemic memory.

**Example:** User asks "what do we know about the Qdrant store?"
- query: "Qdrant store", top_k: 10

```
# Semantic search
context_recall(silo_id: "{silo_id}", query: "{question}", top_k: 10)

# Fetch specific nodes
context_recall(silo_id: "{silo_id}", node_ids: ["{ids}"])

# Filter by layer
context_recall(silo_id: "{silo_id}", query: "{topic}", layers: ["knowledge", "wisdom"])
```

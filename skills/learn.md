---
name: delta-prime:learn
description: Store a fact with evidence to knowledge layer. Use when user says "this is true", "assert that", "we know that", "add this as a fact", or provides a claim that should persist.
allowed-tools:
  - mcp__delta-prime__context_store
when_to_use: Durable facts grounded in evidence. Differs from observe.md (ephemeral) — facts here are eligible for custodian promotion to wisdom.
---

Store a fact with evidence. Facts enter the knowledge layer and may be promoted by the custodian.

**Example:** User says "assert that the context_recall p95 is under 250ms"
- content: "context_recall semantic search p95 latency is under 250ms"
- layer: knowledge
- source_type: "user"

```
context_store(
  silo_id: "{silo_id}",
  content: "{claim}",
  layer: "knowledge",
  evidence: ["{source_node_ids}"],
  source_type: "agent"  # or: document|user|external
)
```

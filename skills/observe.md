---
name: delta-prime:observe
description: Store an observation to memory layer. Use when user says "remember this", "note that", "I noticed", "keep track of", or wants to save something ephemeral for later.
allowed-tools:
  - mcp__delta-prime__context_store
when_to_use: Short-lived observations, session context, environmental notes. Memories decay over time — use learn.md for durable facts.
---

Store an observation to memory. Memories decay over time.

**Example:** User says "remember that the staging DB is flaky today"
- content: "staging DB is flaky today"
- layer: memory
- tags: ["infra", "staging", "database"]

```
context_store(
  silo_id: "{silo_id}",
  content: "{observation}",
  layer: "memory",
  tags: [{relevant_tags}]
)
```

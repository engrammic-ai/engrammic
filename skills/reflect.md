---
name: delta-prime:reflect
description: Store a meta-cognitive observation about reasoning or beliefs. Use when user says "I was wrong about", "update my belief", "flag a contradiction", "note my uncertainty", or wants to record an insight about prior reasoning.
allowed-tools:
  - mcp__delta-prime__context_store
when_to_use: Meta-memory writes — recording belief changes, contradictions, uncertainty, or insights about the agent's own reasoning. Links to the nodes being reflected on.
---

Store a meta-cognitive observation about your own reasoning or beliefs.

**Example:** User says "note that our earlier belief about Redis cache hit rate was based on stale data"
- content: "belief about Redis cache hit rate was based on stale benchmark data"
- layer: meta
- observation_type: "belief_change"

```
context_store(
  silo_id: "{silo_id}",
  content: "{observation}",
  layer: "meta",
  about: ["{relevant_node_ids}"],
  observation_type: "{type}"  # belief_change|contradiction|uncertainty|insight
)
```

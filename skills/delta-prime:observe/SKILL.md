---
name: delta-prime:observe
description: Store observation to memory. Use for "remember this", "note that", ephemeral context.
allowed-tools:
  - mcp__delta-prime__context_store
---

Store an observation to memory. Memories decay over time.

**Tagging:** Always include 2-5 tags. At minimum: one domain tag + one specificity tag.

```
context_store(
  content: "{observation}",
  layer: "memory",
  tags: ["{domain}", "{type}", "{specific}"]
)
```

Tag examples: `api`, `database`, `auth`, `ui`, `infra`, `bug`, `decision`, `session`, `project`

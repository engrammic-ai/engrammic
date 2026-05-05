---
name: delta-prime:recall
description: Search and retrieve context. Use for "what do I know about", "find", "search".
allowed-tools:
  - mcp__delta-prime__context_recall
---

Search or retrieve from epistemic memory.

**Semantic search:**
```
context_recall(query: "{question}", top_k: 10)
```

**Filter by layer:**
```
context_recall(query: "{question}", layers: ["knowledge", "wisdom"])
```

**Fetch specific nodes:**
```
context_recall(node_ids: ["{id1}", "{id2}"])
```

**Graph traversal (depth 1-3):**
```
context_recall(query: "{question}", depth: 2)
```

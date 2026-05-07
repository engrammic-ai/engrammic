---
name: engrammic:reason
description: Store reasoning chain with steps. Use for "figure out", "reason through", "derive".
allowed-tools:
  - mcp__engrammic__context_recall
  - mcp__engrammic__context_store
---

Gather evidence, then store a multi-step reasoning chain at the intelligence layer.

**Workflow:**
1. Recall relevant evidence
2. Store chain with explicit steps

```
# 1. Gather evidence
context_recall(query: "{topic}", top_k: 10)

# 2. Store reasoning chain
context_store(
  content: "{conclusion}",
  layer: "intelligence",
  steps: [
    {"step": "Observation", "reasoning": "...", "confidence": 0.9},
    {"step": "Inference", "reasoning": "...", "confidence": 0.8},
    {"step": "Conclusion", "reasoning": "...", "confidence": 0.85}
  ],
  tags: ["reasoning", "{domain}"]
)
```

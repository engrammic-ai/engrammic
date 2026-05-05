---
name: delta-prime:reason
description: Store a multi-step reasoning chain with audit trail. Use when user says "figure out", "reason through", "derive a conclusion", "synthesize", or when producing a conclusion that should be reproducible and traceable.
allowed-tools:
  - mcp__delta-prime__context_recall
  - mcp__delta-prime__context_store
when_to_use: Intelligence-layer writes. First gather evidence via recall, then store the reasoning chain so each step can be audited later.
---

Gather evidence, then store a multi-step reasoning chain at the intelligence layer.

**Example:** User says "reason through why context_link latency spiked last week"
1. Recall relevant evidence
2. Store chain with explicit steps and confidence

```
# 1. Gather evidence
context_recall(silo_id: "{silo_id}", query: "{topic}", top_k: 10)

# 2. Store reasoning chain
context_store(
  silo_id: "{silo_id}",
  content: "{conclusion}",
  layer: "intelligence",
  steps: [
    {"step": "Observation", "reasoning": "...", "confidence": 0.9},
    {"step": "Inference",   "reasoning": "...", "confidence": 0.8},
    {"step": "Conclusion",  "reasoning": "...", "confidence": 0.85}
  ],
  evidence: ["{source_node_ids}"]
)
```

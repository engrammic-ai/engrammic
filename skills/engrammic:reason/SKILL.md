---
name: engrammic:reason
description: Store reasoning chain with steps. Use for "figure out", "reason through", "derive".
allowed-tools:
  - mcp__engrammic__recall
  - mcp__engrammic__reason
---

# Reason

Gather evidence from memory, then store a multi-step reasoning chain at the intelligence layer. Use this when you need to make a non-trivial inference that connects multiple facts.

## When to use

- "Figure out..." / "reason through..." / "derive..." / "work out why..."
- You are about to form a conclusion from multiple pieces of evidence
- Debugging: you want to record the chain of thought so it can be reviewed or reused
- Before crystallizing a hypothesis, to document the reasoning that supports it

## Tool call

```
# 1. Gather evidence first
recall(query: "{topic}", top_k: 10)

# 2. Store the reasoning chain
reason(
  steps: [
    {"step": "Observation", "reasoning": "...", "confidence": 0.9},
    {"step": "Inference", "reasoning": "...", "confidence": 0.8},
    {"step": "Conclusion", "reasoning": "...", "confidence": 0.85}
  ],
  conclusion: "{conclusion}",  # optional
  evidence_used: ["{node_ids_from_recall}"]  # optional
)
```

## What comes next

After storing a reasoning chain, you might:
- `crystallize` - if the conclusion is strong enough to promote to a Commitment
- `learn` - to extract a specific verifiable claim from the conclusion and store it with evidence
- `reflect` - if the reasoning revealed an unexpected contradiction or change in understanding

## Example workflow

1. `recall(query: "Dagster job failures custodian heartbeat", top_k: 10)` - gather relevant facts
2. `reason(steps: [{step: "Observation", reasoning: "Heartbeat timeout is 30s, job takes 45s"}, {step: "Inference", reasoning: "Job outlives heartbeat window"}, {step: "Conclusion", reasoning: "Increase timeout or add keep-alive"}], evidence_used: [...])` - record the chain
3. `crystallize(session_id: "...", node_ids: ["..."], reasoning: "Root cause confirmed via logs")` - commit the conclusion once validated

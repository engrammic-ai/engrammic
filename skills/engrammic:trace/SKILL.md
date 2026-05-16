---
name: engrammic:trace
description: Trace provenance chain for a belief. Use for "why do I believe", "where did this come from".
allowed-tools:
  - mcp__engrammic__trace
---

# Trace

Trace the citation and evidence chain for a node to understand where a belief came from. Use this to audit the reasoning behind any stored fact, belief, or commitment.

## When to use

- "Why do I believe..." / "where did this come from?" / "what is the evidence for..."
- After `recall` returns a node you want to verify before relying on
- When a belief looks incorrect and you want to find which source introduced it
- After `connect` to verify the resulting provenance chain is correct

## Tool call

```
trace(
  node_id: "{node_id}"
)
```

Returns the chain of evidence and sources that support the belief.

## What comes next

After tracing, you might:
- `reflect` - if the trace reveals the belief rests on a weak or incorrect source
- `connect` - to add a missing link in the provenance chain
- `learn` - to replace a poorly-evidenced claim with a properly sourced one

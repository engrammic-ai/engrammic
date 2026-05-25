---
name: engrammic:accept
description: Accept a proposed belief. Use for "accept proposal", "approve belief".
allowed-tools:
  - mcp__engrammic__context_accept_belief
---

# Accept

**Internal tool, SAGE-only. Not for agent use.**

Accept a ProposedBelief from sage.synthesizer, converting it to a full Belief in the wisdom layer.

## When to use

- sage.synthesizer has surfaced a ProposedBelief and a reviewer is approving it
- Triggered by SAGE review workflows, not by agent reasoning flows
- Use `reject` instead if the proposal is incorrect or unsupported

## Tool call

```
context_accept_belief(
  node_id: "{proposed_belief_node_id}"
)
```

The ProposedBelief becomes a Belief node. Its status changes from `proposed` to `accepted`.

## What comes next

After accepting a belief, you might:
- `connect` - link the new Belief to related nodes it supports or derives from
- `trace` - verify the evidence chain attached to the accepted Belief

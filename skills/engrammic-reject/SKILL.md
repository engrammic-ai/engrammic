---
name: engrammic:reject
description: Reject a proposed belief. Use for "reject proposal", "decline belief".
allowed-tools:
  - mcp__engrammic__context_reject_belief
---

# Reject

**Internal tool, SAGE-only. Not for agent use.**

Reject a ProposedBelief from sage.synthesizer. The rejection reason is stored for provenance so sage.synthesizer can improve future proposals.

## When to use

- sage.synthesizer has surfaced a ProposedBelief that is incorrect, unsupported, or premature
- Triggered by SAGE review workflows, not by agent reasoning flows
- Use `accept` instead if the proposal is sound

## Tool call

```
context_reject_belief(
  node_id: "{proposed_belief_node_id}",
  reason: "Why this proposal is rejected"
)
```

The ProposedBelief status changes to `rejected`. The reason is stored for provenance.

## What comes next

After rejecting a belief, you might:
- `reflect` - record why this synthesis failed, to inform future sage.synthesizer runs
- `learn` - if the rejection reveals a gap in the knowledge base that should be filled explicitly

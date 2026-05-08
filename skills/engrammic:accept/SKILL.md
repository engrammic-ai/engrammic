---
name: engrammic:accept
description: Accept a proposed belief. Use for "accept proposal", "approve belief".
allowed-tools:
  - mcp__engrammic__context_accept_belief
---

Accept a ProposedBelief from custodian synthesis, converting it to a full Belief.

```
context_accept_belief(
  node_id: "{proposed_belief_node_id}"
)
```

The ProposedBelief becomes a Belief node. Its status changes from `proposed` to `accepted`.

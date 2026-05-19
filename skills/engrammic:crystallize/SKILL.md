---
name: engrammic:crystallize
description: Promote hypotheses to commitments. Use for "commit to", "finalize belief", "crystallize".
allowed-tools:
  - mcp__engrammic__commit
---

# Crystallize

Promote one or more WorkingHypotheses to Commitments in the wisdom layer. Use this when a hypothesis has been validated and you are ready to declare it as a position, not just a working assumption.

## When to use

- "Commit to..." / "finalize this belief" / "crystallize..."
- A hypothesis has been validated by evidence or reasoning and you are ready to act on it
- End of a reasoning session, recording which conclusions survived scrutiny
- Declaring a design or architectural decision that should persist across sessions

**Difference from Belief:** A Commitment is a declared position ("we will use X"). A Belief is a synthesized conclusion ("X appears to be faster based on benchmarks"). Both live in the wisdom layer but Commitments signal intent.

## Tool call

```
commit(
  belief_ids: ["{hypothesis_node_ids}"],
  reason: "Why these hypotheses are now commitments"  # optional
)
```

Creates Commitment nodes linked to the original hypotheses via DERIVED_FROM.

## What comes next

After crystallizing, you might:
- `connect` - link the new Commitment to nodes it depends on or supersedes
- `reflect` - record that this session produced a key decision
- `recall` - query to verify the Commitment is now visible in wisdom layer

## Example workflow

1. `belief-state(query: "auth strategy")` - surface active hypotheses on the topic
2. `reason(steps: [...], evidence_used: [...])` - validate the strongest hypothesis
3. `commit(belief_ids: ["{hypothesis_id}"], reason: "Validated against load tests; selecting JWT with Redis revocation")` - commit the decision

---
name: engrammic:eag-guide
description: Cognitive guide for EAG memory usage. When to remember, form beliefs, and use each layer.
---

# EAG Cognitive Guide

Use this when deciding how to interact with Engrammic's memory layers.

## The Memory Question: "Should I remember this?"

Before storing, ask:
1. Will this matter later?
2. Is this new information?
3. Who else might need this?
4. How long will it stay true?

**Heuristic:** If you wouldn't tell a colleague about it tomorrow, don't store it.

## The Knowledge Question: "Is this a fact?"

Before storing to Knowledge:
1. Do I have evidence? (No evidence = use Memory instead)
2. Is this verifiable? (Opinions are not facts)
3. Could this be wrong? (Use lower confidence)

**Heuristic:** If you'd need to cite a source to defend this claim, it belongs in Knowledge with that source as evidence.

## The Wisdom Question: "What do I believe?"

Form a belief when:
1. You've seen the same pattern multiple times
2. You've reasoned from facts to a conclusion
3. You need to take a position

**The belief test:** "Based on [these facts], I believe [this conclusion]." If you can't fill in [these facts], you don't have a belief - you have a hunch. Store hunches to Memory.

## Layer Quick Reference

| Layer | Store when | Evidence? | Persists? |
|-------|-----------|-----------|-----------|
| Memory | Raw observation, context | No | Decays (7d-5y) |
| Knowledge | Verifiable claim | Required | Until superseded |
| Wisdom | Synthesized belief/pattern | Links to facts | Indefinite |
| Intelligence | Reasoning steps | No | Session only |
| Meta | Understanding changed | Links to nodes | Never decays |

## Decay Classes

- `ephemeral` (7d): scratch work, temp context
- `standard` (90d): normal observations
- `durable` (540d): important, referenced repeatedly
- `permanent` (5y): foundational reference

## Belief Formation Flow

```
Observe → Store to Memory
    ↓
Extract claim with evidence → Store to Knowledge
    ↓
Corroboration (3+ sources) → Promoted to Fact
    ↓
Synthesize across facts → Form Belief in Wisdom
    ↓
Declare position → Commitment (optional)
    ↓
New evidence arrives → Supersede, record to Meta
```

## Commitment vs Belief

- **Belief:** "Based on benchmarks, X is faster" (grounded in facts)
- **Commitment:** "We will use X for all new work" (declared position)

Both live in Wisdom, but Commitments don't need evidence - they need declaration.

## When to Reflect (Meta-Memory)

Record to Meta when:
- You update a belief based on new evidence
- You notice a contradiction
- You correct a mistake
- Your confidence shifts significantly

The history of belief is as valuable as current belief.

## Full Reference

See `context/brainstorm/2026-05-10-eag-agent-instructions.md` for complete documentation.

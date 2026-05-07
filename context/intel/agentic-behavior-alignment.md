# Agentic Behavior Alignment

Research from 2026-05-07. Do frontier models naturally align with epistemic memory management?

## Key Finding

Models have the cognitive machinery for belief management but don't naturally use it persistently. They need scaffolding.

## What Models CAN Do (Intrinsically)

- Internal belief representations exist (~2/3 depth into model)
- "Language of thought" that's cross-lingual (Anthropic research)
- Theory of Mind capabilities — but context-dependent
- Reasoning pattern: fact identification → belief state tracking → logical inference → conclusion
- **Require appropriate guidance to express these capabilities**

## What Models DON'T Do (Naturally)

- Persist beliefs across sessions
- Track confidence without being asked
- Detect contradictions without being prompted
- Automatically revise beliefs on new evidence
- Crystallize learnings into durable stances

## The Alignment Gap

| Capability | Intrinsic? | Expressed Without Scaffolding? |
|------------|------------|-------------------------------|
| Belief tracking within turn | Yes | Yes |
| Confidence estimation | Partial | Rarely |
| Cross-session persistence | No | No |
| Contradiction detection | Partial | Only when prompted |
| Belief revision | Partial | Inconsistent |

## Implication for Engrammic

**We're eliciting latent capabilities, not fighting model behavior.**

### Design Principle: Alignment-Native

Don't expect models to call belief tools. Instead:

1. **Intercept natural behavior** — extract implicit beliefs from observations
2. **Surface at retrieval** — propose beliefs during recall
3. **Leverage existing cognition** — present contradicting items together

### Tool Design

```
Agent naturally does:     System does:
-------------------      -----------
Writes observation   ->  Extract confidence, entities, claims
Retrieves context    ->  Surface beliefs, flag contradictions  
Makes statement      ->  Check against belief store
```

### Path B is Alignment-Native

| Model Tendency | Path A (Agent-initiated) | Path B (System-initiated) |
|----------------|--------------------------|---------------------------|
| Doesn't track confidence | Fails | Works — system infers |
| Forgets across sessions | Fails | Works — system persists |
| Contradicts self | Fails | Works — system detects |
| Doesn't crystallize | Fails | Works — system proposes |

## Risk Mitigations for Inference

Since we're inferring beliefs from natural language:

1. **Conservative extraction** — only high-confidence claims
2. **Source attribution** — every belief links to supporting memories
3. **Transparent reasoning** — agent sees why belief was proposed
4. **Easy correction** — rejection teaches the system

## Sources

- [Anthropic Introspection Research](https://transformer-circuits.pub/2025/introspection/index.html)
- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Memory in the Age of AI Agents Survey](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)

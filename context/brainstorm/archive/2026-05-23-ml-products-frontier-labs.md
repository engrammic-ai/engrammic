# ML Products for Frontier Labs - Brainstorm

Date: 2026-05-23

## Summary

Exploring ML products Engrammic can sell to frontier model companies.

## Products Identified

### 1. Heat Model
- Predicts importance/relevance of knowledge given context
- Solves: "what goes in the context window"
- Architecture: Temporal Graph Neural Network (TGNN)
- Training data: structural signals only (heat curves, access patterns, graph topology)
- Timeline: 2-3 months to prototype
- Market: Broad (anyone building agents/RAG)

### 2. Memory Module
- Pre-trained component encoding epistemic reasoning
- Solves: "how do agents maintain coherent beliefs over time"
- Handles: belief formation, revision (supersession), provenance, confidence
- Architecture: Likely adapter/LoRA approach initially
- Timeline: 6+ months
- Market: Frontier labs

## Strategy: Open Weights First

1. Ship heat model integration for Llama/Mistral
2. Publish benchmarks showing context efficiency gains
3. Memory module follows same pattern
4. Frontier labs adopt/acquire/partner from position of leverage

## Research Context

### Problems frontier labs face:
- "Lost in the middle" - context windows big but attention doesn't scale
- Long-horizon agents need persistent, updatable memory
- Belief revision without retraining is hard (~30 models tested, most struggle)
- Hallucination fundamental to generative models

### Related research:
- DeepSeek Engram: O(1) static memory lookup
- Titans: learned memory prioritizing by "surprise"
- HINDSIGHT: unifies factual recall with preference reasoning
- Continuum Memory Architectures: alternatives to RAG

### Engrammic's unique value:
- Explicit belief revision tracking (supersession chains)
- Epistemic provenance (no one else models this)
- Dynamic vs static memory (DeepSeek is static)

## Advisor Input (Opus)

- Prioritize Heat Model first - faster validation, clearer metrics
- GTM: target applied research/infra teams, not core model research
- Risk: frontier labs may build it themselves if it works
- Alternative: consider enterprise agent market (faster sales, less competition)

## Researcher Input (Opus)

- Heat Model: TGNN architecture, query-conditioned attention
- Memory Module: adapter/LoRA, or Mamba-style state-space
- Gap we fill: explicit belief revision tracking
- Risk: synthetic data distribution shift, no benchmark exists

## Future Exploration: Alignment Research Tooling

**Paused pending interviews with alignment researchers.**

Potential direction: Model Behavior Observatory
- Instrument models to log epistemic behavior into Engrammic
- Researchers query patterns: hallucination, consistency, calibration
- Structured logging vs ad-hoc text dumps

Targets for interviews:
- Anthropic alignment team
- Redwood Research
- ARC (Alignment Research Center)
- Academic labs (Berkeley CHAI, MIT)

Questions to validate:
- How do you currently track findings/hypotheses?
- What's painful about studying model behavior at scale?
- Would structured epistemic logging be useful?

## Next Steps

1. Complete design spec (data capture, synthetic generation, benchmarks)
2. Write implementation plan
3. Schedule alignment researcher interviews (separate track)

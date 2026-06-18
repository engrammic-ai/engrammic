# Benchmark Strategy

Date: 2026-06-18
Status: Research complete, prioritization decided

## Target Benchmarks

### Priority 1: BEAM
- Tests contradiction resolution and temporal reasoning
- Plays to Engrammic's strengths (epistemic coherence, SUPERSEDES, belief updates)
- Proves "memory that doesn't rot" thesis
- TODO: Deep research needed

### Priority 2: LongMemEval-V2
- UCLA NLP benchmark (arxiv:2605.12493)
- Leaderboard empty - first-mover opportunity
- Tests 5 abilities: Static State Recall, Dynamic State Tracking, Workflow Knowledge, Gotchas, Premise Awareness
- Gotchas hardest category (20-48% even for best methods)

**Key finding:** Pure retrieval caps at ~58%. Top performer (AgentRunbook-C at 72%) uses coding agent to navigate trajectories.

**Gaps for Engrammic:**
| Gap | Severity |
|-----|----------|
| No multi-granularity pools (raw + transitions + consolidated) | HIGH |
| No gotcha/failure mode extraction | HIGH |
| No trajectory/sequence representation | HIGH |
| No programmatic evidence gathering | MEDIUM |

**Strategic concern:** LME-V2 is web-agent focused (WebArena, WorkArena). Engrammic's ICP is code/knowledge agents. Gotcha detection in web UIs != epistemic coherence.

### Priority 3: Supporting benchmarks
- **LoCoMo** - timeline ordering, multi-session reasoning
- **LongMemEval v1** - knowledge updates, abstention
- **MEME** - cascade updates, derived facts (mem0 scores "near floor" here)
- **MemoryArena** - 40-60% collapse from retrieval to agentic tasks

## What LME-V2 Does NOT Test

- Contradiction detection (A vs not-A)
- Cross-session temporal reasoning
- Belief revision / truth maintenance
- Multi-hop across entities

These are tested by BEAM and LoCoMo instead.

## LME-V2 Architecture Requirements

To compete (>60%):
1. Three-pool architecture: raw observations, state transitions, consolidated knowledge
2. Gotcha extraction pipeline (extract "what went wrong" from failures)
3. Multi-stream retrieval (decompose query per pool)

To win (>70%):
4. Programmatic evidence scaffolding (coding agent over trajectories)
5. Premise validation (detect invalid assumptions, abstain)

## Mapping to Engrammic Schema

| LME-V2 Pool | Engrammic Layer |
|-------------|-----------------|
| Raw state slices | Document (Memory) |
| State transitions | Could be edge metadata or separate node |
| Consolidated knowledge | Fact/Belief (Knowledge/Wisdom) |

Current schema may need:
- Trajectory/sequence representation
- Failure mode extraction (gotcha nodes?)
- Multi-pool retrieval strategy

## Sources

- [LongMemEval-V2 Paper](https://arxiv.org/abs/2605.12493)
- [LongMemEval-V2 GitHub](https://github.com/xiaowu0162/LongMemEval-V2)
- [Project Page](https://xiaowu0162.github.io/longmemeval-v2/)
- [MEME Benchmark](https://arxiv.org/html/2605.12477)

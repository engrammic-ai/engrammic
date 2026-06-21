# EAG Agent Prompting Learnings

Date: 2026-05-17

## Context

Session exploring how to get agents to use Engrammic MCP tools meaningfully vs mechanically.

## What didn't work well

### Batch processing prompts (v1)
```
For each .md file, read it and store a summary using mcp__engrammic__remember.
Format: "[filename]: [1-2 sentence summary]"
Tags: ["context-service", "spec", "docs"]
```

**Result:** 48 memory observations that are basically a document index. Functional for search but not "using EAG" - no epistemic structure, no reasoning, no meaningful beliefs.

### Task-oriented skill prompts (v2)
```
For each file:
1. Decide based on EAG guide: observation vs evidenced claim
2. Use engrammic:observe or engrammic:learn accordingly
3. After processing, form a belief about patterns
```

**Result:** Better layer separation (memory vs knowledge), but beliefs were checklist items - "The codebase uses thin wrappers." Quick summaries tacked on at the end, not conclusions from genuine reasoning. No intelligence layer usage.

## What works better

### Exploratory prompts (v3)
```
You are an exploratory agent. Your job is genuine sense-making, not task completion.

Wander. Read files that seem interesting. Follow threads.
- When you notice something curious, observe it
- When you find facts with evidence, learn them  
- When you're puzzled by a design choice, reason through it - build a multi-step chain
- When reasoning leads to a real conclusion, form a belief - but make it rich

No checklist. No quota. Explore until you've formed 2-3 genuinely reasoned beliefs.
```

**Key differences:**
1. No file list or iteration structure
2. Encourages curiosity ("puzzled by", "seems interesting")
3. Explicitly asks for reasoning chains, not just observations
4. Defines what a good belief looks like (rich, with evidence refs and implications)
5. Quality over quantity framing

## Belief quality spectrum

**Weak (checklist belief):**
> "The codebase uses thin wrappers."

**Medium (summary belief):**
> "Engrammic's design decisions consistently follow a 'constrain complexity early' pattern."

**Strong (reasoned belief):**
> "After tracing through [node refs], I believe the thin-wrapper pattern exists because [reasoning]. This has implications for [X] - it means [Y]. The evidence that convinced me was [specific things]. A counterargument might be [Z], but I think [response]."

## Layer usage patterns

| Layer | When agents use it naturally | When they don't |
|-------|------------------------------|-----------------|
| Memory | Always - lowest friction | - |
| Knowledge | When explicitly told "evidence required" | Default to memory otherwise |
| Wisdom | When told "form a belief at the end" | Rarely spontaneous |
| Intelligence | Almost never without explicit prompt | Need "reason through", "why is X" |

## Prompting heuristics for EAG

1. **Don't give file lists** - agents will iterate mechanically
2. **Use curiosity language** - "puzzled", "interesting", "why would they..."
3. **Explicitly name the `reason` skill** - agents default to observe/learn
4. **Define belief quality** - show an example of a rich belief
5. **No quotas** - "2-3 meaningful" beats "process all files"
6. **Frame as sense-making** - "understand this codebase" not "document this codebase"

## Open questions

- Can we get reasoning chains without any prompting? (Pure tool discovery)
- Do beliefs improve if agent has to defend them to another agent?
- Would multi-turn exploration (checkpoint and continue) produce deeper reasoning?

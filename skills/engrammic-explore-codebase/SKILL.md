---
name: engrammic:explore-codebase
description: Two-phase codebase exploration with Engrammic memory. Phase 1 spawns parallel targeted explorers (arch, patterns, quality, domain). Phase 2 spawns a wanderer to fill gaps. All findings tagged for later recall.
---

# Explore Codebase with Engrammic Memory

Two-phase exploration:
1. **Targeted explorers** (parallel) - build structured foundation
2. **Wanderer** (after) - fill gaps, find surprises, cross-link

## Arguments

- `path` - codebase root (default: current directory)
- `tag` - tag for all stored nodes (required, e.g. "somnus")
- `focus` - optional focus to narrow exploration

Example: `/engrammic:explore-codebase tag=somnus`

## Phase 1: Targeted Exploration

### Create team and spawn 4 parallel agents

```
TeamCreate({ team_name: "explore-{tag}" })
```

Launch these **in parallel**. Each agent:
1. Invokes `/engrammic:eag-guide` first
2. Explores their focus area
3. Tags all nodes with "{tag}"

#### arch-explorer
```
prompt: |
  Explore {path} architecture. First invoke `/engrammic:eag-guide`.
  Focus: structure, modules, data flow, abstractions.
  Tag everything with "{tag}".
```

#### patterns-explorer
```
prompt: |
  Explore {path} patterns. First invoke `/engrammic:eag-guide`.
  Focus: design patterns, conventions, idioms, protocols.
  Tag everything with "{tag}".
```

#### quality-explorer
```
prompt: |
  Explore {path} quality. First invoke `/engrammic:eag-guide`.
  Focus: tests, error handling, tech debt, coverage gaps.
  Tag everything with "{tag}".
```

#### domain-explorer
```
prompt: |
  Explore {path} domain. First invoke `/engrammic:eag-guide`.
  Focus: problem solved, domain concepts, terminology.
  Tag everything with "{tag}".
```

### Wait for Phase 1 completion

Collect summaries from all 4 agents. Note the node count.

## Phase 2: Wandering

After targeted explorers complete, spawn a wanderer who can see what's been stored.

```
prompt: |
  The codebase at {path} has been explored by 4 targeted agents.
  Their findings are in Engrammic tagged "{tag}".
  
  First invoke `/engrammic:eag-guide`, then recall what's stored:
  - Query for tag "{tag}" to see what's known
  - Look for gaps, contradictions, missing connections
  
  Then invoke `/engrammic:wander` to explore with curiosity.
  Find what the focused explorers missed. Tag everything with "{tag}".
  Link your findings to theirs where relevant.
```

## Synthesize

After wanderer completes:
1. Form synthesized beliefs from cross-agent findings
2. Create cross-links between related nodes
3. Report total nodes and key insights

## Output

```markdown
# Codebase Exploration: {tag}

## Phase 1 Summary
| Agent | Nodes | Key Findings |
|-------|-------|--------------|
| arch | N | ... |
| patterns | N | ... |
| quality | N | ... |
| domain | N | ... |

## Phase 2: Wanderer Additions
[gaps filled, surprises found, cross-links created]

## Total: N nodes tagged "{tag}"

Recall with: recall(query="...", tags=["{tag}"])
```

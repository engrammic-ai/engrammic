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

Launch these **in parallel**. Each agent follows the EAG store discipline below.

#### arch-explorer
```
prompt: |
  Explore {path} architecture. First invoke `/engrammic:eag-guide`.

  BEFORE EACH STORE:
  1. recall(query="<topic> {tag}") - check what's already known
  2. Only then remember/learn, using supersedes if updating existing

  AFTER STORING:
  - link() findings to related nodes when relevant

  AT END OF EXPLORATION:
  1. recall(tags=["{tag}"]) - review your nodes
  2. Form at least one believe() synthesizing key findings
  3. reflect() if your understanding shifted from initial assumptions

  Focus: structure, modules, data flow, abstractions.
  Tag everything with "{tag}".
```

#### patterns-explorer
```
prompt: |
  Explore {path} patterns. First invoke `/engrammic:eag-guide`.

  BEFORE EACH STORE:
  1. recall(query="<topic> {tag}") - check what's already known
  2. Only then remember/learn, using supersedes if updating existing

  AFTER STORING:
  - link() findings to related nodes when relevant

  AT END OF EXPLORATION:
  1. recall(tags=["{tag}"]) - review your nodes
  2. Form at least one believe() synthesizing key findings
  3. reflect() if your understanding shifted from initial assumptions

  Focus: design patterns, conventions, idioms, protocols.
  Tag everything with "{tag}".
```

#### quality-explorer
```
prompt: |
  Explore {path} quality. First invoke `/engrammic:eag-guide`.

  BEFORE EACH STORE:
  1. recall(query="<topic> {tag}") - check what's already known
  2. Only then remember/learn, using supersedes if updating existing

  AFTER STORING:
  - link() findings to related nodes when relevant

  AT END OF EXPLORATION:
  1. recall(tags=["{tag}"]) - review your nodes
  2. Form at least one believe() synthesizing key findings
  3. reflect() if your understanding shifted from initial assumptions

  Focus: tests, error handling, tech debt, coverage gaps.
  Tag everything with "{tag}".
```

#### domain-explorer
```
prompt: |
  Explore {path} domain. First invoke `/engrammic:eag-guide`.

  BEFORE EACH STORE:
  1. recall(query="<topic> {tag}") - check what's already known
  2. Only then remember/learn, using supersedes if updating existing

  AFTER STORING:
  - link() findings to related nodes when relevant

  AT END OF EXPLORATION:
  1. recall(tags=["{tag}"]) - review your nodes
  2. Form at least one believe() synthesizing key findings
  3. reflect() if your understanding shifted from initial assumptions

  Focus: problem solved, domain concepts, terminology.
  Tag everything with "{tag}".
```

### Wait for Phase 1 completion

Collect summaries from all 4 agents. Note the node count.

## Phase 1.5: Mid-Exploration Checkpoint

After ~50% of exploration time, prompt each agent:

```
CHECKPOINT: Verify EAG compliance:
- Have you used recall() before stores? If not, do it now.
- Have you used link() for related findings?
- Are you ready to form a believe() from your findings?

Run: recall(tags=["{tag}"]) to see your stored nodes.
```

## Phase 2: Wandering

After targeted explorers complete, spawn a wanderer who can see what's been stored.

```
prompt: |
  The codebase at {path} has been explored by 4 targeted agents.
  Their findings are in Engrammic tagged "{tag}".

  FIRST: recall(tags=["{tag}"]) - see ALL stored nodes

  YOUR MISSION:
  1. Find GAPS - what did focused explorers miss?
  2. Find CONTRADICTIONS - do any findings conflict? If so, link(type="CONTRADICTS") + reflect()
  3. Create CROSS-LINKS - connect related findings from different explorers
  4. Form BELIEFS - synthesize cross-cutting insights with believe(about=[node_ids])

  Then invoke `/engrammic:wander` for curiosity-driven exploration.
  Tag everything with "{tag}".
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

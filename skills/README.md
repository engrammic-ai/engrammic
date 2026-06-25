# Engrammic Skills

Skills for working with Engrammic MCP tools.

## Installing

Copy skill directories to the portable agent-skills location:

```bash
cp -r skills/engrammic-* ~/.agents/skills/
```

Claude Code also reads `~/.claude/skills/`.

## Skills

| Skill | Purpose |
|-------|---------|
| `engrammic-eag-guide` | LeAP cognitive guide: layer selection, store/recall triggers, conflict handling |
| `engrammic-explore-codebase` | Two-phase codebase exploration with memory |
| `engrammic-wander` | Gap-filling exploration for missed areas |

### ICP Presets (not for local install)

| Skill | Purpose |
|-------|---------|
| `coding:onboarding` | Developer persona onboarding |
| `b2b-ops:onboarding` | B2B ops persona onboarding |

These are served by the Engrammic server per-tenant. Don't copy locally.

## MCP Tool Surface

Full reference: `docs/api/mcp-tools-reference.md`

| Tool | Purpose |
|------|---------|
| `remember` | Store observation to Memory |
| `learn` | Record claim with evidence to Knowledge |
| `recall` | Search or fetch knowledge |
| `update` | Supersede existing knowledge |
| `trace` | Walk provenance chain |
| `forget` | Tombstone a node |
| `tick` | Engagement check |
| `introspect` | Metacognitive queries |
| `agents` | List agents in silo |
| `conflicts` | List contradictions |
| `dismiss_conflict` | Mark as not-a-conflict |
| `escalate_conflict` | Flag for human review |
| `resolve_conflict` | Pick winner |

## Prerequisites

1. Engrammic MCP server connected
2. Valid auth token

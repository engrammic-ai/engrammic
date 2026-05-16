# Context Skills

Skills for working with engrammic context-service MCP tools.

## Installing skills locally

Engrammic skills follow the SKILL.md open standard. Copy the base skill
directories into the portable agent-skills location so any compatible harness
(Claude Code, Codex, Cursor, Windsurf, Gemini CLI) can discover them:

```bash
cp -r skills/engrammic:* ~/.agents/skills/
```

Claude Code also reads `~/.claude/skills/`; either location works for that
harness. ICP overlay skills (`coding:*`, `b2b-ops:*`) are delivered per
tenant through the `patterns` MCP tool and are not installed from the
filesystem.

### Other Agents

Load skill content from `{skill}/SKILL.md` into your agent's system prompt on-demand.

## Skills

### Cognitive Guide

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `eag-guide` | "how should I use memory", "when to form beliefs" | Cognitive framework for EAG layer usage |

### Write Operations

| Skill | Trigger | Layer |
|-------|---------|-------|
| `observe` | "remember this", "note that" | memory |
| `learn` | "assert that", "we know that" | knowledge |
| `reason` | "figure out", "derive" | intelligence |
| `reflect` | "I was wrong", "flag contradiction" | meta |
| `connect` | "X relates to Y", "link these" | link |

### Belief Operations

| Skill | Trigger | Layer |
|-------|---------|-------|
| `belief-state` | "what hypotheses", "session beliefs" | intelligence (read) |
| `update-belief` | "revise hypothesis", "add evidence" | intelligence |
| `crystallize` | "commit to", "finalize belief" | wisdom |
| `accept` | "accept proposal", "approve belief" | wisdom |
| `reject` | "reject proposal", "decline belief" | wisdom |

### Read Operations

| Skill | Trigger | Layer |
|-------|---------|-------|
| `recall` | "what do I know", "search for" | read |
| `trace` | "why do I believe", "provenance" | admin |

## Tagging Guidelines

Always include `tags` when storing context (2-5 tags per node).

**Categories:**
- **Domain:** `api`, `database`, `auth`, `ui`, `infra`
- **Type:** `bug-fix`, `feature`, `decision`, `spec`, `checkpoint`
- **Scope:** `session`, `project`

**Rules:** lowercase, hyphenated, specific over generic.

## Token Cost

- Index in system-reminder: ~30 tokens/skill (~210 total)
- On-demand load: ~100-150 tokens per skill when invoked
- MCP tool schemas: ~300 tokens/tool (~1,200 total)

## Prerequisites

1. Context-service MCP server running
2. MCP tools connected (`context_store`, `context_recall`, `context_link`, `context_admin`)

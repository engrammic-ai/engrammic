# Context Skills

Skills for working with engrammic context-service MCP tools.

## Installation

### Claude Code

Copy skills to your Claude Code skills directory:

```bash
cp -r skills/engrammic:* ~/.claude/skills/
```

Skills appear in your session as `engrammic:observe`, `engrammic:learn`, etc. Invoke via `/engrammic:observe` or the `Skill` tool.

### Other Agents

Load skill content from `{skill}/SKILL.md` into your agent's system prompt on-demand.

## Skills

| Skill | Trigger | Layer |
|-------|---------|-------|
| `observe` | "remember this", "note that" | memory |
| `learn` | "assert that", "we know that" | knowledge |
| `recall` | "what do I know", "search for" | read |
| `reason` | "figure out", "derive" | intelligence |
| `reflect` | "I was wrong", "update belief" | meta |
| `trace` | "why do I believe", "provenance" | admin |
| `connect` | "X relates to Y", "link these" | link |

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

# OSS Adoption Helpers Design

## Goal

First MCP call in under 5 minutes for new users.

## Target Audience

1. **Primary:** Anyone building multi-agent systems, via hosted Engrammic (MCP registry)
2. **Secondary:** Local/offline users via engrammic-engine
3. **Tertiary:** Framework builders using primitives directly

## Packages

- `engrammic-primitives` - EAG schema/types (framework builders)
- `engrammic-engine` - single-tenant local engine (devs wanting offline/local)
- `engrammic-mcp` - MCP server connecting to hosted service (primary entry point)

## Design

### 1. engrammic-mcp README (Primary)

60-second quickstart optimized for MCP registry install:

```markdown
# Engrammic MCP

Persistent memory for AI agents.

## Quickstart

1. Install from MCP registry (or `uvx engrammic-mcp`)
2. Set `ENGRAMMIC_API_KEY` (get one at engrammic.ai)
3. Done

## Examples

Store something:
> "Remember that the user prefers dark mode"

Recall it later:
> "What do I know about user preferences?"

## Tools

| Tool | Purpose |
|------|---------|
| context_store | Store to memory/knowledge/wisdom |
| context_recall | Search and retrieve context |
| context_link | Connect concepts |

## Learn More

- [EAG Concepts](docs/eag-concepts.md) - understand the memory model
- [Claude Code Skills](skills/) - deeper integration for Claude Code users
```

### 2. engrammic-engine README (Local/Offline)

For local or offline usage:

```markdown
# Engrammic Engine

Local EAG engine with MCP server. No cloud, no API key.

## Quickstart

uvx engrammic-engine serve

Configure your MCP client to point to `http://localhost:8000/mcp`

## When to use

- Offline environments
- Privacy-sensitive projects
- Experimenting before committing to hosted
```

### 3. engrammic-primitives README (Framework Builders)

Schema-focused, minimal:

```markdown
# Engrammic Primitives

EAG schema primitives for building epistemic context systems.

## Install

pip install engrammic-primitives

## Usage

from primitives.schema import MemoryNode, KnowledgeNode
from primitives.eag import CognitiveTier

## When to use

Building your own EAG-compatible system or extending Engrammic.
```

### 4. Level 2: Skills (Claude Code users)

Already exist in `skills/`. Add a one-liner to mcp-client README:

> "Using Claude Code? Copy `skills/` to `~/.claude/skills/` for EAG workflow guidance."

### 5. Level 2: EAG Concepts Doc

Short doc explaining memory/knowledge/wisdom/meta for users who want to understand before using. Not required for quickstart.

Location: `docs/eag-concepts.md` in mcp-client repo.

## What NOT to build

- Interactive tutorials (friction)
- CLI wizards (friction)
- Video walkthroughs (maintenance burden)
- Multiple example repos (fragmentation)

## Success Criteria

- User can go from MCP registry install to first `context_store` call in <5 mins
- README fits on one screen
- Zero required reading before first call

## Implementation Order

1. mcp-client README rewrite
2. eag-concepts.md (level 2 doc)
3. engine README rewrite  
4. primitives README rewrite
5. Skills README update with install instructions

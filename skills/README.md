# Context Skills

Prompt templates for working with delta-prime context-service MCP tools.

## What are Skills?

Skills are agent-side prompt templates that compose the core MCP tools. They're not executable code - they're patterns that agents learn to follow.

**Core MCP Tools (3):**
- `context_store` - write to epistemic memory
- `context_recall` - read from epistemic memory
- `context_link` - create relationships

**Skills (9):** Prompt templates that teach agents when and how to use those tools.

## Installation

### Claude Code / CLAUDE.md

Append to your project's CLAUDE.md:

```bash
curl -s https://raw.githubusercontent.com/delta-prime/context-service/main/skills/context-skills.md >> CLAUDE.md
```

Or copy the relevant sections manually.

### Python / LangGraph

```python
from pathlib import Path

# Load skills as system prompt addition
skills_prompt = Path("skills/context-skills.md").read_text()

agent = Agent(
    system_prompt=f"{your_base_prompt}\n\n{skills_prompt}",
    tools=[context_store, context_recall, context_link]
)
```

### Pi Agent

```bash
# Copy to Pi skills directory
curl -o ~/.pi/skills/context-skills.md \
  https://raw.githubusercontent.com/delta-prime/context-service/main/skills/context-skills.md
```

## Skills Overview

### Core (always use)

| Skill | Trigger | What it does |
|-------|---------|--------------|
| observe | "remember this" | Store to memory layer |
| learn | "I learned" | Store fact with evidence |
| recall | "what do I know" | Search/retrieve |
| trace | "why do I believe" | Provenance chain |
| reflect | "I notice a pattern" | Meta-observation |
| reason | "let me think through" | Structured reasoning |

### Workflow-Adjacent (defer to gsd/superpowers for complex work)

| Skill | Trigger | What it does |
|-------|---------|--------------|
| research | "research this" | Deep dive on topic |
| fact_check | "is this true" | Verify against knowledge |
| connect | "how does X relate to Y" | Link concepts |

## Token Cost

Skills add ~70 tokens each to system prompt. Full skills file is ~1200 tokens.

Compare to 15 MCP tool schemas at ~2250 tokens - skills are more efficient and more learnable.

## Prerequisites

1. Context-service MCP server running
2. MCP tools connected (`context_store`, `context_recall`, `context_link`)
3. Skills file in agent's system prompt or context

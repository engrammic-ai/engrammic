# OSS Adoption Helpers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite READMEs for engrammic-mcp, engrammic-engine, and engrammic-primitives to enable first MCP call in <5 minutes.

**Architecture:** Docs-only changes. Each README follows quickstart-first pattern: install, configure, done. Level 2 content (EAG concepts, skills) linked but not required.

**Tech Stack:** Markdown

---

### Task 1: Rewrite mcp-client README

**Files:**
- Modify: `../mcp-client/README.md`

- [ ] **Step 1: Replace README with quickstart-first version**

```markdown
# Engrammic MCP

Persistent memory for AI agents.

## Quickstart

1. Install from [MCP Registry](https://registry.mcp.io/engrammic) or `uvx engrammic-mcp`
2. Set `ENGRAMMIC_API_KEY` (get one at [engrammic.ai](https://engrammic.ai))
3. Done

## Examples

Store something:
> "Remember that the user prefers dark mode"

Recall it later:
> "What do I know about user preferences?"

## Tools

| Tool | Purpose |
|------|---------|
| `context_store` | Store to memory/knowledge/wisdom |
| `context_recall` | Search and retrieve context |
| `context_link` | Connect concepts |
| `context_admin` | Usage info, provenance, history |
| `context_belief_state` | Query active hypotheses |
| `context_crystallize` | Promote hypotheses to commitments |

## Configuration

```bash
export ENGRAMMIC_API_KEY=eng_xxx
```

Or add to Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "engrammic": {
      "command": "engrammic-mcp",
      "env": {
        "ENGRAMMIC_API_KEY": "eng_xxx"
      }
    }
  }
}
```

## Self-Hosting

For local/offline usage, see [engrammic-engine](https://github.com/engrammic/engine).

## Learn More

- [EAG Concepts](docs/eag-concepts.md) - understand the memory model
- Using Claude Code? Copy [skills/](https://github.com/engrammic/context-service/tree/main/skills) to `~/.claude/skills/` for EAG workflow guidance

## License

Apache 2.0
```

- [ ] **Step 2: Commit**

```bash
cd ../mcp-client && git add README.md && git commit -m "docs: quickstart-first README for MCP registry"
```

---

### Task 2: Create eag-concepts.md

**Files:**
- Create: `../mcp-client/docs/eag-concepts.md`

- [ ] **Step 1: Create docs directory if needed and write eag-concepts.md**

```markdown
# EAG Concepts

EAG (Epistemic Augmented Generation) is a memory model for AI agents. It organizes context into four layers:

## The Four Layers

| Layer | What it holds | Lifetime |
|-------|---------------|----------|
| **Memory** | Observations, events, things you noticed | Decays over time |
| **Knowledge** | Facts backed by evidence | Persists until contradicted |
| **Wisdom** | Beliefs synthesized from facts | Revises on new evidence |
| **Intelligence** | Reasoning chains | Session-scoped |

## When to Use Each Layer

**Memory** - "I noticed X" or "The user said Y"
- Ephemeral observations
- No evidence required
- Decays naturally

**Knowledge** - "X is true because [evidence]"
- Claims you can back up
- Requires evidence URI
- Persists until contradicted

**Wisdom** - "Based on [facts], I believe [conclusion]"
- Synthesized understanding
- Emerges from multiple facts
- Revises when evidence changes

**Intelligence** - "Let me reason through this"
- Working memory for current task
- Disappears after session

## Quick Heuristics

- **Memory:** Would I tell a colleague about this tomorrow? If no, don't store.
- **Knowledge:** Do I have evidence? If no, use Memory.
- **Wisdom:** Can I fill in "Based on [facts], I believe [conclusion]"? If no, it's a hunch - use Memory.

## Tools Mapping

| Tool | Typical Layer |
|------|---------------|
| `context_store` | Any layer (specify in call) |
| `context_recall` | Reads from all layers |
| `context_link` | Creates cross-layer relationships |
| `context_crystallize` | Promotes Intelligence to Wisdom |
```

- [ ] **Step 2: Commit**

```bash
cd ../mcp-client && git add docs/eag-concepts.md && git commit -m "docs: add EAG concepts explainer"
```

---

### Task 3: Rewrite engine README

**Files:**
- Modify: `../engine/README.md`

- [ ] **Step 1: Replace README with quickstart-first version**

```markdown
# Engrammic Engine

Local EAG engine with MCP server. No cloud, no API key.

## Quickstart

```bash
uvx engrammic-engine serve
```

Configure your MCP client to point to `http://localhost:8000/mcp`

## When to Use

- Offline or air-gapped environments
- Privacy-sensitive projects
- Non-commercial use
- Experimenting before committing to hosted

For hosted service with no setup, see [engrammic-mcp](https://github.com/engrammic/mcp-client).

## Installation

```bash
pip install engrammic-engine
```

Or from source:

```bash
git clone https://github.com/engrammic/engine
cd engine
pip install -e ".[dev]"
```

## Tools

| Tool | Purpose |
|------|---------|
| `context_store` | Store to memory/knowledge/wisdom |
| `context_recall` | Search and retrieve context |
| `context_link` | Create relationships between nodes |

## Skills

Agent-side prompts that teach when/how to use the tools. Install by copying to your agent's config:

```bash
curl -s https://raw.githubusercontent.com/engrammic/engine/main/skills/context-skills.md >> CLAUDE.md
```

## Learn More

- [engrammic-primitives](https://github.com/engrammic/primitives) - EAG schema library
- [EAG Concepts](https://github.com/engrammic/mcp-client/blob/main/docs/eag-concepts.md) - understand the memory model

## License

Apache 2.0
```

- [ ] **Step 2: Commit**

```bash
cd ../engine && git add README.md && git commit -m "docs: quickstart-first README for local engine"
```

---

### Task 4: Rewrite primitives README

**Files:**
- Modify: `../primitives/README.md`

- [ ] **Step 1: Replace README with simplified version**

```markdown
# Engrammic Primitives

EAG schema primitives for building epistemic context systems.

## Install

```bash
pip install engrammic-primitives
```

## Usage

```python
from primitives.schema import MemoryNode, KnowledgeNode, WisdomNode
from primitives.eag import CognitiveTier

# Create a memory node
node = MemoryNode(
    content="User prefers dark mode",
    importance=0.7,
)

# Check cognitive tier
tier = CognitiveTier.MEMORY
```

## When to Use

Building your own EAG-compatible system or extending Engrammic.

For using Engrammic directly, see:
- [engrammic-mcp](https://github.com/engrammic/mcp-client) - hosted service
- [engrammic-engine](https://github.com/engrammic/engine) - local engine

## Modules

| Module | Purpose |
|--------|---------|
| `primitives.schema` | Node and edge type definitions |
| `primitives.eag` | EAG-specific implementations |
| `primitives.protocols` | Storage and lifecycle interfaces |
| `primitives.scoring` | Decay and freshness formulas |

## License

Apache 2.0
```

- [ ] **Step 2: Commit**

```bash
cd ../primitives && git add README.md && git commit -m "docs: simplify README for framework builders"
```

---

### Task 5: Update skills README with install instructions

**Files:**
- Modify: `skills/README.md`

- [ ] **Step 1: Read current skills README**

Run: `cat skills/README.md`

- [ ] **Step 2: Add install instructions to top of README**

Add this section after the title:

```markdown
## Installation

Copy to your Claude Code skills directory:

```bash
cp -r skills/engrammic:* ~/.claude/skills/
```

Or download individually:

```bash
curl -sL https://github.com/engrammic/context-service/raw/main/skills/engrammic:eag-guide/index.md -o ~/.claude/skills/engrammic:eag-guide/index.md
```
```

- [ ] **Step 3: Commit**

```bash
git add skills/README.md && git commit -m "docs: add skills install instructions"
```

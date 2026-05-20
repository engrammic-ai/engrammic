# Engrammic Documentation Site Design

## Overview

Public documentation site for Engrammic at docs.engrammic.ai. Built with Starlight (Astro), deployed on GCP (Cloud Run or similar).

## Target Audiences

1. **Evaluators** - AI/ML engineers assessing the architecture
2. **Developers** - Integrating Engrammic via MCP
3. **Beta users** - Getting started quickly

## Information Architecture

Landing page presents a fork: "Understand Engrammic" (theory path) vs "Start Building" (developer path). Both paths converge at MCP Tools reference.

```
/ (landing - splash, sidebar hidden, hamburger to reveal)
   ├── "Understand Engrammic" → /concepts/overview
   └── "Start Building" → /guides/quickstart

├── Concepts (theory path)
│   ├── overview.md
│   ├── cognitive-layers.md
│   ├── belief-formation.md
│   ├── meta-memory.md
│   ├── how-it-works.md
│   └── why-not-rag.md
│
├── Guides (developer path)
│   ├── quickstart.md
│   ├── working-with-memory.md
│   └── examples.md
│
└── MCP Tools (reference)
    ├── overview.md
    ├── remember.md
    ├── learn.md
    ├── believe.md
    ├── recall.md
    ├── trace.md
    ├── link.md
    ├── reason.md
    ├── reflect.md
    ├── hypothesize.md
    ├── revise.md
    ├── commit.md
    └── patterns.md
```

## Page Specifications

### Landing Page

- Hero with tagline: "Epistemic memory for AI agents"
- Two CTAs side-by-side:
  - "Understand Engrammic" → /concepts/overview
  - "Start Building" → /guides/quickstart
- 4 feature cards below hero:
  - Epistemic Memory: structured memory with evidence and provenance
  - MCP Native: works with Claude Code, Cursor, any MCP client
  - Cognitive Layers: Memory/Knowledge/Wisdom/Intelligence hierarchy
  - Built for Agents: designed for AI agents that remember across sessions
- Splash template (no sidebar by default, hamburger reveals it)

### Concepts Section

Written fresh for clarity, light on jargon, heavy on examples.

| Page | Content |
|------|---------|
| overview | What is Engrammic, the problem it solves, EAG paradigm summary |
| cognitive-layers | Memory/Knowledge/Wisdom/Intelligence, when to use each, heuristics |
| belief-formation | Flow diagram (observe → claim → fact → belief), confidence, evidence |
| meta-memory | Provenance tracking, time-travel queries, reflection |
| how-it-works | SAGE system overview, background synthesis, how beliefs form (very high-level, no internals) |
| why-not-rag | The category error in RAG, what EAG does differently |

### Guides Section

Practical, developer-focused, minimal theory.

| Page | Content |
|------|---------|
| quickstart | MCP config snippet, first `remember`, verify with `recall`, 5 minutes |
| working-with-memory | Practical patterns, decay classes, tagging, when to use each tool |
| agent-usage | Cognitive guide for agents: when to store, layer heuristics, anti-patterns (adapted from primitives/docs/07-agent-usage.md) |
| examples | 2-3 real scenarios: session context, learning from docs, forming beliefs |

### MCP Tools Section

Each tool page follows consistent structure:
- Description (1-2 sentences)
- Parameters table
- 2-3 examples
- When to use / when not to use

**Standard profile tools:**
- remember - Store observations (no evidence required)
- learn - Store facts with evidence
- believe - Form conclusions from facts
- recall - Search and retrieve
- trace - Provenance chain
- link - Typed relationships

**Reasoning profile tools (advanced):**
- reason - Reasoning chains with steps
- reflect - Meta-observations
- hypothesize - Tentative beliefs
- revise - Update hypotheses
- commit - Crystallize to commitment

**Always available:**
- patterns - Skills/workflow templates

## Content Sources

| Target | Source | Approach |
|--------|--------|----------|
| Concepts | Write fresh | User-friendly, use primitives/docs as background (don't link or copy directly) |
| Guides | Write fresh + adapt | Practical; agent-usage adapted from primitives/docs/07-agent-usage.md |
| MCP Tools | Adapt from CLAUDE.md | Consistent format per tool |

## Tech Stack

- Starlight (Astro)
- Tailwind CSS
- Deployed on GCP (Cloud Run or similar)
- Custom domain: docs.engrammic.ai

## Out of Scope (for now)

- Deep EAG paradigm theory (defer to primitives/docs)
- Internal tool documentation (context_admin, etc.)
- REST API reference (admin-only, not public-facing)
- Versioned docs

# Engrammic Documentation Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Engrammic documentation site with landing page, concepts, guides, and MCP tool reference.

**Architecture:** Starlight (Astro) site already scaffolded in `../docs`. Update config for proper navigation, wire logos, create all content pages following the spec structure. Content is markdown/MDX.

**Tech Stack:** Starlight, Astro, Tailwind CSS, MDX

---

## File Structure

```
../docs/
├── astro.config.mjs          # Update: sidebar navigation
├── src/
│   ├── assets/
│   │   ├── logo-light.png    # Already copied
│   │   └── logo-dark.png     # Already copied
│   ├── content/docs/
│   │   ├── index.mdx         # Update: dual CTA landing
│   │   ├── concepts/
│   │   │   ├── overview.md       # Create
│   │   │   ├── cognitive-layers.md # Update (exists)
│   │   │   ├── belief-formation.md # Create
│   │   │   ├── meta-memory.md      # Create
│   │   │   ├── how-it-works.md     # Create
│   │   │   └── why-not-rag.md      # Create
│   │   ├── guides/
│   │   │   ├── quickstart.md       # Update (exists)
│   │   │   ├── working-with-memory.md # Create
│   │   │   ├── agent-usage.md      # Create
│   │   │   └── examples.md         # Create
│   │   ├── mcp-tools/
│   │   │   ├── overview.md         # Create
│   │   │   ├── remember.md         # Update (exists)
│   │   │   ├── learn.md            # Create
│   │   │   ├── believe.md          # Create
│   │   │   ├── recall.md           # Create
│   │   │   ├── trace.md            # Create
│   │   │   ├── link.md             # Create
│   │   │   ├── reason.md           # Create
│   │   │   ├── reflect.md          # Create
│   │   │   ├── hypothesize.md      # Create
│   │   │   ├── revise.md           # Create
│   │   │   ├── commit.md           # Create
│   │   │   └── patterns.md         # Create
│   │   └── reference/
│   │       └── api.md              # Delete
```

---

## Task 1: Configuration and Structure

**Files:**
- Modify: `../docs/astro.config.mjs`
- Delete: `../docs/src/content/docs/reference/api.md`

- [ ] **Step 1: Update astro.config.mjs with correct sidebar and logo config**

```javascript
// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  integrations: [
      starlight({
          title: 'Engrammic',
          logo: {
              light: './src/assets/logo-light.png',
              dark: './src/assets/logo-dark.png',
              replacesTitle: true,
          },
          social: [
              { icon: 'github', label: 'GitHub', href: 'https://github.com/engrammic-ai' },
              { icon: 'linkedin', label: 'LinkedIn', href: 'https://www.linkedin.com/company/engrammic' },
          ],
          sidebar: [
              {
                  label: 'Concepts',
                  items: [
                      { label: 'Overview', slug: 'concepts/overview' },
                      { label: 'Cognitive Layers', slug: 'concepts/cognitive-layers' },
                      { label: 'Belief Formation', slug: 'concepts/belief-formation' },
                      { label: 'Meta-Memory', slug: 'concepts/meta-memory' },
                      { label: 'How It Works', slug: 'concepts/how-it-works' },
                      { label: 'Why Not RAG?', slug: 'concepts/why-not-rag' },
                  ],
              },
              {
                  label: 'Guides',
                  items: [
                      { label: 'Quickstart', slug: 'guides/quickstart' },
                      { label: 'Working with Memory', slug: 'guides/working-with-memory' },
                      { label: 'Agent Usage', slug: 'guides/agent-usage' },
                      { label: 'Examples', slug: 'guides/examples' },
                  ],
              },
              {
                  label: 'MCP Tools',
                  items: [
                      { label: 'Overview', slug: 'mcp-tools/overview' },
                      { label: 'remember', slug: 'mcp-tools/remember' },
                      { label: 'learn', slug: 'mcp-tools/learn' },
                      { label: 'believe', slug: 'mcp-tools/believe' },
                      { label: 'recall', slug: 'mcp-tools/recall' },
                      { label: 'trace', slug: 'mcp-tools/trace' },
                      { label: 'link', slug: 'mcp-tools/link' },
                      { label: 'reason', slug: 'mcp-tools/reason' },
                      { label: 'reflect', slug: 'mcp-tools/reflect' },
                      { label: 'hypothesize', slug: 'mcp-tools/hypothesize' },
                      { label: 'revise', slug: 'mcp-tools/revise' },
                      { label: 'commit', slug: 'mcp-tools/commit' },
                      { label: 'patterns', slug: 'mcp-tools/patterns' },
                  ],
              },
          ],
          editLink: {
              baseUrl: 'https://github.com/engrammic-ai/docs/edit/main/',
          },
          customCss: ['./src/styles/global.css'],
      }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
});
```

- [ ] **Step 2: Delete the reference/api.md file**

```bash
rm ../docs/src/content/docs/reference/api.md
rmdir ../docs/src/content/docs/reference
```

- [ ] **Step 3: Verify build passes**

```bash
cd ../docs && pnpm build
```

Expected: Build succeeds (may warn about missing pages, that's OK)

- [ ] **Step 4: Commit**

```bash
cd ../docs && git add -A && git commit -m "chore: update config and remove reference section"
```

---

## Task 2: Landing Page

**Files:**
- Modify: `../docs/src/content/docs/index.mdx`

- [ ] **Step 1: Update landing page with dual CTAs**

```mdx
---
title: Engrammic
description: Epistemic memory for AI agents.
template: splash
hero:
  tagline: Give your AI agents structured, persistent memory with epistemic rigor.
  actions:
    - text: Understand Engrammic
      link: /concepts/overview/
      icon: open-book
    - text: Start Building
      link: /guides/quickstart/
      icon: right-arrow
      variant: secondary
---

import { Card, CardGrid } from '@astrojs/starlight/components';

## Why Engrammic?

<CardGrid stagger>
  <Card title="Epistemic Memory" icon="star">
    Not just storage. Structured memory with evidence, confidence, and provenance tracking.
  </Card>
  <Card title="MCP Native" icon="puzzle">
    First-class Model Context Protocol support. Works with Claude Code, Cursor, and any MCP client.
  </Card>
  <Card title="Cognitive Layers" icon="list-format">
    Memory, Knowledge, Wisdom, Intelligence. Each layer serves a distinct epistemic purpose.
  </Card>
  <Card title="Built for Agents" icon="rocket">
    Designed for AI agents that need to remember, learn, and reason across sessions.
  </Card>
</CardGrid>
```

- [ ] **Step 2: Verify landing page renders**

```bash
cd ../docs && pnpm dev
```

Open http://localhost:4321 and verify:
- Logo displays
- Tagline shows
- Two CTAs visible side-by-side
- Four feature cards below

- [ ] **Step 3: Commit**

```bash
cd ../docs && git add src/content/docs/index.mdx && git commit -m "feat: update landing page with dual CTAs"
```

---

## Task 3: Concepts Section

**Files:**
- Create: `../docs/src/content/docs/concepts/overview.md`
- Update: `../docs/src/content/docs/concepts/cognitive-layers.md`
- Create: `../docs/src/content/docs/concepts/belief-formation.md`
- Create: `../docs/src/content/docs/concepts/meta-memory.md`
- Create: `../docs/src/content/docs/concepts/how-it-works.md`
- Create: `../docs/src/content/docs/concepts/why-not-rag.md`

- [ ] **Step 1: Create concepts/overview.md**

```markdown
---
title: What is Engrammic?
description: An introduction to epistemic memory for AI agents.
---

Engrammic gives AI agents structured, persistent memory with epistemic rigor. Instead of treating all information equally, Engrammic distinguishes between observations, facts, and beliefs, each with different persistence and evidence requirements.

## The Problem

Most AI memory systems are glorified key-value stores. They dump everything into a vector database and hope semantic search finds the right context. This works for simple recall but breaks down when agents need to:

- Track where information came from
- Update beliefs when evidence changes
- Distinguish between "I saw this" and "I know this"
- Reason about confidence and contradictions

## The Solution

Engrammic implements EAG (Epistemic Augmented Generation), a four-layer cognitive architecture:

| Layer | Purpose | Persistence |
|-------|---------|-------------|
| **Memory** | Raw observations | Decays over time |
| **Knowledge** | Facts with evidence | Until superseded |
| **Wisdom** | Synthesized beliefs | Indefinite |
| **Intelligence** | Reasoning chains | Session only |

Each layer has different rules for storage, retrieval, and revision. The system tracks provenance so you always know where a belief came from.

## How Agents Use It

Agents interact with Engrammic via MCP tools:

```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User prefers TypeScript over JavaScript"
  }
}
```

The agent stores observations, claims facts with evidence, forms beliefs, and queries context. Engrammic handles the epistemology, the agent focuses on the task.

## Next Steps

- [Cognitive Layers](/concepts/cognitive-layers/) - Deep dive into each layer
- [Quickstart](/guides/quickstart/) - Get running in 5 minutes
```

- [ ] **Step 2: Update concepts/cognitive-layers.md**

```markdown
---
title: Cognitive Layers
description: Understanding Engrammic's four-layer memory architecture.
---

Engrammic organizes knowledge into four cognitive layers, each serving a distinct epistemic purpose.

## Memory Layer

Raw observations without evidence requirements. Use for ephemeral context, preferences, and session notes.

**Store when:** You observe something that might be useful later.

**Heuristic:** If you wouldn't tell a colleague about it tomorrow, don't store it.

```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User is debugging the auth flow"
  }
}
```

**Decay classes:**
| Class | Duration | Use for |
|-------|----------|---------|
| `ephemeral` | 7 days | Scratch work, temp context |
| `standard` | 90 days | Normal observations |
| `durable` | 540 days | Important, referenced repeatedly |
| `permanent` | 5 years | Foundational reference |

## Knowledge Layer

Facts with evidence. Claims must be supported by sources.

**Store when:** You have verifiable information with a source.

**Heuristic:** If you'd need to cite a source to defend this claim, it belongs in Knowledge.

```json
{
  "tool": "learn",
  "arguments": {
    "claim": "OAuth tokens expire after 1 hour",
    "evidence": "https://docs.example.com/auth#expiry",
    "confidence": 0.95
  }
}
```

## Wisdom Layer

Synthesized beliefs from corroborated facts. Formed through the belief pipeline.

**Store when:** You've seen patterns across multiple facts and want to form a conclusion.

**Heuristic:** "Based on [these facts], I believe [this conclusion]." If you can't fill in [these facts], it's a hunch, not a belief.

```json
{
  "tool": "believe",
  "arguments": {
    "belief": "This codebase follows repository pattern for data access",
    "about": ["node_abc123", "node_def456"]
  }
}
```

## Intelligence Layer

Reasoning chains and derivations. Ephemeral by design.

**Store when:** You're working through a complex problem and want to capture your reasoning.

**Important:** Intelligence is session-scoped. It won't persist across conversations.

```json
{
  "tool": "reason",
  "arguments": {
    "goal": "Determine root cause of auth failure",
    "steps": [
      "Token is present in request",
      "Token signature validates",
      "Token is expired (issued 2 hours ago)",
      "Conclusion: token refresh not triggering"
    ]
  }
}
```

## Quick Reference

| Layer | Store when | Evidence? | Persists? |
|-------|-----------|-----------|-----------|
| Memory | Raw observation | No | Decays |
| Knowledge | Verifiable claim | Required | Until superseded |
| Wisdom | Synthesized belief | Links to facts | Indefinite |
| Intelligence | Reasoning steps | No | Session only |
```

- [ ] **Step 3: Create concepts/belief-formation.md**

```markdown
---
title: Belief Formation
description: How Engrammic forms and revises beliefs.
---

Beliefs in Engrammic don't appear from nowhere. They're synthesized from evidence through a deliberate process.

## The Flow

```
OBSERVE  →  Memory (decays)
    ↓
CLAIM    →  Knowledge (with evidence)
    ↓
VERIFY   →  Claim promoted to Fact (3+ sources)
    ↓
SYNTHESIZE → Belief formed (links multiple Facts)
    ↓
REVISE   →  When new evidence, supersede (don't delete)
```

## From Observation to Belief

**1. Observation**

You notice something. Store it to Memory.

```json
{"tool": "remember", "arguments": {"observation": "API returns 429 frequently"}}
```

**2. Claim**

You find evidence. Store to Knowledge.

```json
{
  "tool": "learn",
  "arguments": {
    "claim": "API rate limit is 100 requests/minute",
    "evidence": "https://api.example.com/docs/limits",
    "confidence": 0.9
  }
}
```

**3. Corroboration**

When multiple independent sources support the same claim, the system promotes it from Claim to Fact. This happens automatically when corroboration threshold (default: 3 sources) is met.

**4. Belief**

You synthesize across facts to form a belief.

```json
{
  "tool": "believe",
  "arguments": {
    "belief": "We need request batching to stay under rate limits",
    "about": ["node_rate_limit_fact", "node_429_observations"]
  }
}
```

## Confidence

Confidence scores indicate certainty:

| Score | Meaning | Use when |
|-------|---------|----------|
| 0.95+ | Near certain | Multiple reliable sources, verified |
| 0.8-0.95 | Confident | Single reliable source |
| 0.6-0.8 | Probable | Reasonable inference |
| 0.4-0.6 | Uncertain | Plausible but unverified |
| <0.4 | Speculative | Weak evidence |

## Revision, Not Deletion

When beliefs change, supersede rather than delete:

```json
{
  "tool": "learn",
  "arguments": {
    "claim": "API rate limit is 200 requests/minute",
    "evidence": "https://api.example.com/changelog#2024-03",
    "supersedes": "node_old_rate_limit"
  }
}
```

The old belief remains in the graph with a `SUPERSEDES` edge. This preserves history and enables time-travel queries.
```

- [ ] **Step 4: Create concepts/meta-memory.md**

```markdown
---
title: Meta-Memory
description: Tracking provenance, changes, and reflection.
---

Meta-memory is Engrammic's audit layer. It tracks where knowledge came from, how beliefs changed, and why.

## Provenance

Every node in Engrammic has provenance: a record of its origin.

**Key relationship types:**

| Relationship | Meaning |
|--------------|---------|
| `DERIVED_FROM` | This came from that source |
| `EXTRACTED_FROM` | Extracted from a document |
| `SUPERSEDES` | This replaces that (newer understanding) |
| `PROMOTED_FROM` | Claim promoted to Fact |

Use `trace` to follow the provenance chain:

```json
{
  "tool": "trace",
  "arguments": {
    "node_id": "node_abc123"
  }
}
```

Returns the full chain: where it came from, what it superseded, what promoted it.

## Time Travel

Because supersession creates chains rather than overwrites, you can query past states:

"What did I believe about X on date Y?"

The graph preserves the complete history. Old beliefs aren't deleted, they're marked as superseded with timestamps.

## Reflection

When your understanding changes, record it:

```json
{
  "tool": "reflect",
  "arguments": {
    "observation": "I was wrong about the auth flow. Tokens refresh client-side, not server-side.",
    "about": ["node_old_belief", "node_new_evidence"]
  }
}
```

**Record a reflection when:**
- You update a belief based on new evidence
- You notice a contradiction
- You correct a mistake
- Your confidence shifts significantly

The history of belief is as valuable as current belief. Reflections capture the "why" of changes.
```

- [ ] **Step 5: Create concepts/how-it-works.md**

```markdown
---
title: How It Works
description: High-level architecture of Engrammic.
---

Engrammic combines graph storage, vector search, and background synthesis to create an epistemic memory system.

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│              MCP Interface                   │
│   (remember, learn, believe, recall, ...)   │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│              Context Engine                  │
│   - Query planning                          │
│   - Retrieval orchestration                 │
│   - Response assembly                       │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│              Storage Layer                   │
│   - Graph (relationships, provenance)       │
│   - Vector (semantic search)                │
│   - Cache (hot paths)                       │
└─────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│              SAGE (Background)               │
│   - Synthesis                               │
│   - Corroboration                           │
│   - Decay management                        │
└─────────────────────────────────────────────┘
```

## SAGE: Background Intelligence

SAGE runs asynchronously to maintain the knowledge graph:

**Synthesis:** When multiple facts support a conclusion, SAGE proposes beliefs for review.

**Corroboration:** When claims from independent sources align, SAGE promotes them to facts.

**Decay:** SAGE applies time-based decay to Memory layer nodes, ensuring old observations fade naturally.

You don't interact with SAGE directly. It works in the background to keep your knowledge graph healthy.

## Query Flow

When you call `recall`:

1. **Parse query** - Understand what you're looking for
2. **Search vectors** - Find semantically similar content
3. **Traverse graph** - Follow relationships for context
4. **Rank results** - Score by relevance, recency, confidence
5. **Assemble response** - Return structured context

The combination of vector search (what's similar?) and graph traversal (what's related?) enables rich contextual retrieval.

## Multi-Tenancy

Engrammic supports multiple isolated silos. Each silo has its own:
- Knowledge graph
- Vector index  
- Configuration

Silos don't share data. This enables per-user, per-project, or per-team memory isolation.
```

- [ ] **Step 6: Create concepts/why-not-rag.md**

```markdown
---
title: Why Not RAG?
description: The category error in retrieval-augmented generation.
---

RAG (Retrieval-Augmented Generation) revolutionized how LLMs access external knowledge. But it has a fundamental limitation: it treats all information the same.

## The Category Error

RAG asks: "What text chunks are semantically similar to this query?"

This works for simple retrieval but conflates:
- Observations with facts
- Claims with evidence
- Current beliefs with superseded ones
- Your knowledge with someone else's

When you search a RAG system for "API rate limits," you might get:
- An outdated doc from 2022
- A Slack message where someone guessed
- The actual current limit from official docs

RAG can't distinguish between them. It just returns similar text.

## What EAG Does Differently

EAG (Epistemic Augmented Generation) asks: "What do I know, believe, or remember about this, and why?"

| RAG | EAG |
|-----|-----|
| All chunks equal | Layers with different semantics |
| No provenance | Full source tracking |
| No confidence | Explicit uncertainty |
| Overwrite updates | Supersession chains |
| Semantic similarity only | Graph + vector hybrid |

## When RAG is Fine

RAG works well when:
- Content is static (documentation, reference)
- Sources are equally authoritative
- History doesn't matter
- You just need "relevant text"

## When You Need EAG

EAG shines when:
- Knowledge evolves over time
- Source credibility varies
- You need to explain why you believe something
- Contradictions must be tracked, not hidden
- Agents need to learn and update beliefs

## The Core Insight

RAG retrieves text. EAG retrieves knowledge.

Text is what was written. Knowledge is what you believe to be true, with evidence, confidence, and the ability to revise when you learn more.
```

- [ ] **Step 7: Verify concepts section**

```bash
cd ../docs && pnpm build
```

Expected: Build succeeds, all concept pages created.

- [ ] **Step 8: Commit**

```bash
cd ../docs && git add src/content/docs/concepts/ && git commit -m "feat: add concepts section pages"
```

---

## Task 4: Guides Section

**Files:**
- Update: `../docs/src/content/docs/guides/quickstart.md`
- Create: `../docs/src/content/docs/guides/working-with-memory.md`
- Create: `../docs/src/content/docs/guides/agent-usage.md`
- Create: `../docs/src/content/docs/guides/examples.md`

- [ ] **Step 1: Update guides/quickstart.md**

```markdown
---
title: Quickstart
description: Get started with Engrammic in 5 minutes.
---

This guide gets you from zero to working memory in 5 minutes.

## Prerequisites

- An MCP-compatible client (Claude Code, Cursor, Windsurf, etc.)
- Access to the Engrammic beta

## 1. Add MCP Configuration

Add Engrammic to your MCP client. For Claude Code, edit `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "engrammic": {
      "url": "https://beta.engrammic.ai/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

Replace `YOUR_API_KEY` with your beta access key.

## 2. Verify Connection

Ask your agent to check the connection:

> "Use the Engrammic recall tool to search for anything"

You should see a response indicating the search completed (even if empty).

## 3. Store Your First Memory

Ask your agent to remember something:

> "Remember that I prefer TypeScript over JavaScript"

Behind the scenes, this calls:

```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User prefers TypeScript over JavaScript"
  }
}
```

## 4. Retrieve Context

Later, when relevant, your agent can recall:

> "What do you know about my language preferences?"

```json
{
  "tool": "recall",
  "arguments": {
    "query": "language preferences"
  }
}
```

Returns your stored observation.

## 5. Store a Fact

For claims with evidence, use `learn`:

> "Learn that our API rate limit is 100 requests/minute, based on https://docs.example.com/limits"

```json
{
  "tool": "learn",
  "arguments": {
    "claim": "API rate limit is 100 requests/minute",
    "evidence": "https://docs.example.com/limits",
    "confidence": 0.9
  }
}
```

## Next Steps

- [Working with Memory](/guides/working-with-memory/) - Patterns and best practices
- [Agent Usage Guide](/guides/agent-usage/) - When to use each tool
- [MCP Tools Reference](/mcp-tools/overview/) - Full tool documentation
```

- [ ] **Step 2: Create guides/working-with-memory.md**

```markdown
---
title: Working with Memory
description: Practical patterns for using Engrammic effectively.
---

This guide covers practical patterns for working with Engrammic's memory system.

## Choosing the Right Layer

| What you have | Tool to use | Layer |
|---------------|-------------|-------|
| An observation, no source | `remember` | Memory |
| A fact with a source | `learn` | Knowledge |
| A conclusion from multiple facts | `believe` | Wisdom |
| Reasoning you're doing now | `reason` | Intelligence |

## Decay Classes

When storing to Memory, choose the right decay:

```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User mentioned deadline is Friday",
    "decay_class": "ephemeral"
  }
}
```

| Class | Duration | Use for |
|-------|----------|---------|
| `ephemeral` | 7 days | Temp context, scratch work |
| `standard` | 90 days | Normal observations (default) |
| `durable` | 540 days | Important, referenced repeatedly |
| `permanent` | 5 years | Foundational reference |

**Heuristic:** Default to `standard`. Use `ephemeral` for session-specific context. Use `durable` for information you'll reference across many sessions.

## Tagging

Tags help organize and retrieve related content:

```json
{
  "tool": "remember",
  "arguments": {
    "observation": "Auth service uses JWT with RS256",
    "tags": ["auth", "security", "architecture"]
  }
}
```

Later, query by tag:

```json
{
  "tool": "recall",
  "arguments": {
    "query": "auth",
    "tags": ["architecture"]
  }
}
```

## Evidence Quality

When using `learn`, evidence quality affects confidence:

**Strong evidence (0.9+):**
- Official documentation
- Verified API responses
- Authoritative sources

**Medium evidence (0.7-0.9):**
- Blog posts from known experts
- Stack Overflow accepted answers
- Internal docs

**Weak evidence (0.5-0.7):**
- Forum discussions
- Unverified claims
- Inference from behavior

## Linking Related Content

Use `link` to create explicit relationships:

```json
{
  "tool": "link",
  "arguments": {
    "from_node": "node_auth_service",
    "to_node": "node_jwt_spec",
    "relationship": "IMPLEMENTS"
  }
}
```

Common relationship types:
- `SUPPORTS` / `CONTRADICTS`
- `CAUSES` / `PREVENTS`
- `IMPLEMENTS` / `EXTENDS`
- `RELATES_TO` (generic)

## Updating Information

Don't delete old information. Supersede it:

```json
{
  "tool": "learn",
  "arguments": {
    "claim": "API rate limit is 200 requests/minute",
    "evidence": "https://docs.example.com/changelog",
    "supersedes": "node_old_rate_limit"
  }
}
```

This preserves history while updating the current truth.
```

- [ ] **Step 3: Create guides/agent-usage.md**

```markdown
---
title: Agent Usage Guide
description: Cognitive guide for agents using Engrammic.
---

This guide helps AI agents make good decisions about when and how to use Engrammic's memory tools.

## The Memory Question: "Should I remember this?"

Before storing, ask:
1. **Will this matter later?** If only relevant now, skip.
2. **Is this new?** Don't duplicate existing knowledge.
3. **Who needs this?** Just you = ephemeral. Team = durable.
4. **How long is it true?** Choose decay class accordingly.

**Heuristic:** If you wouldn't tell a colleague about it tomorrow, don't store it.

## The Knowledge Question: "Is this a fact?"

Before storing to Knowledge:
1. **Do I have evidence?** No evidence = use Memory instead.
2. **Is this verifiable?** Opinions are not facts.
3. **Could this be wrong?** Use lower confidence.

**Heuristic:** If you'd need to cite a source to defend this claim, it belongs in Knowledge with that source as evidence.

## The Wisdom Question: "What do I believe?"

Form a belief when:
1. You've seen the same pattern multiple times
2. You've reasoned from facts to a conclusion
3. You need to take a position

**The belief test:** "Based on [these facts], I believe [this conclusion]." If you can't fill in [these facts], you don't have a belief. You have a hunch. Store hunches to Memory.

## Decision Tree

```
Is this worth storing?
├── No → Skip
└── Yes → What kind?
    ├── Raw observation/context → remember (pick decay class)
    ├── Verifiable claim with source → learn (include evidence)
    ├── Pattern/belief from multiple facts → believe (link to facts)
    ├── Reasoning I'm doing now → reason (session only)
    └── My understanding changed → reflect (audit trail)
```

## Anti-Patterns

Avoid these common mistakes:

1. **Storing to Knowledge without evidence**
   - Bad: `learn("API is fast")` 
   - Good: `learn("API p99 is 45ms", evidence="https://status.example.com")`

2. **Storing to Wisdom without linking to facts**
   - Bad: `believe("We should use caching")`
   - Good: `believe("We should use caching", about=["node_latency_data", "node_traffic_patterns"])`

3. **Expecting Intelligence layer across sessions**
   - `reason` is ephemeral. If you need the reasoning later, also store a Memory observation summarizing the conclusion.

4. **Deleting instead of superseding**
   - Don't delete outdated information. Use `supersedes` parameter to create a chain.

5. **Not reflecting on belief changes**
   - When you change your mind, use `reflect` to record why. The audit trail is valuable.

## When to Reflect

Use `reflect` when:
- You update a belief based on new evidence
- You notice a contradiction
- You correct a mistake
- Your confidence shifts significantly

The history of belief is as valuable as current belief.
```

- [ ] **Step 4: Create guides/examples.md**

```markdown
---
title: Examples
description: Real-world scenarios using Engrammic.
---

These examples show how to use Engrammic in common scenarios.

## Example 1: Session Context

An agent helping with code review stores preferences observed during the session.

**Observation:**
```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User prefers explicit error handling over try/catch blocks",
    "tags": ["preferences", "code-style"],
    "decay_class": "durable"
  }
}
```

**Later retrieval:**
```json
{
  "tool": "recall",
  "arguments": {
    "query": "code style preferences"
  }
}
```

The agent can now apply this preference in future reviews without being told again.

---

## Example 2: Learning from Documentation

An agent reads API documentation and stores structured facts.

**Store the fact:**
```json
{
  "tool": "learn",
  "arguments": {
    "claim": "createUser endpoint requires email and password fields",
    "evidence": "https://api.example.com/docs/users#create",
    "confidence": 0.95,
    "tags": ["api", "users", "auth"]
  }
}
```

**Store a related fact:**
```json
{
  "tool": "learn",
  "arguments": {
    "claim": "createUser returns 409 Conflict if email exists",
    "evidence": "https://api.example.com/docs/users#errors",
    "confidence": 0.95,
    "tags": ["api", "users", "errors"]
  }
}
```

**Link them:**
```json
{
  "tool": "link",
  "arguments": {
    "from_node": "node_create_user_requirements",
    "to_node": "node_create_user_errors",
    "relationship": "RELATES_TO"
  }
}
```

---

## Example 3: Forming a Belief

After observing patterns across multiple sessions, an agent forms a belief.

**Recall relevant facts:**
```json
{
  "tool": "recall",
  "arguments": {
    "query": "deployment issues production",
    "limit": 10
  }
}
```

Returns:
- "Deployment failed due to memory limit" (3 occurrences)
- "Production pods OOMKilled" (2 occurrences)  
- "Staging works, production fails" (4 occurrences)

**Form the belief:**
```json
{
  "tool": "believe",
  "arguments": {
    "belief": "Production environment needs higher memory limits than staging",
    "about": ["node_mem_fail_1", "node_mem_fail_2", "node_oom_1"],
    "confidence": 0.85
  }
}
```

---

## Example 4: Updating Knowledge

The API documentation changed. Update the stored knowledge.

**Store the new fact:**
```json
{
  "tool": "learn",
  "arguments": {
    "claim": "createUser endpoint now also accepts optional 'name' field",
    "evidence": "https://api.example.com/docs/users#create (v2.1)",
    "confidence": 0.95,
    "supersedes": "node_old_create_user_requirements"
  }
}
```

**Reflect on the change:**
```json
{
  "tool": "reflect",
  "arguments": {
    "observation": "API v2.1 added optional name field to user creation. Previous understanding was incomplete.",
    "about": ["node_old_requirements", "node_new_requirements"]
  }
}
```

The old fact remains in the graph but is marked as superseded. Time-travel queries can still access it.
```

- [ ] **Step 5: Verify guides section**

```bash
cd ../docs && pnpm build
```

Expected: Build succeeds, all guide pages created.

- [ ] **Step 6: Commit**

```bash
cd ../docs && git add src/content/docs/guides/ && git commit -m "feat: add guides section pages"
```

---

## Task 5: MCP Tools Section - Standard Profile

**Files:**
- Create: `../docs/src/content/docs/mcp-tools/overview.md`
- Update: `../docs/src/content/docs/mcp-tools/remember.md`
- Create: `../docs/src/content/docs/mcp-tools/learn.md`
- Create: `../docs/src/content/docs/mcp-tools/believe.md`
- Create: `../docs/src/content/docs/mcp-tools/recall.md`
- Create: `../docs/src/content/docs/mcp-tools/trace.md`
- Create: `../docs/src/content/docs/mcp-tools/link.md`

- [ ] **Step 1: Create mcp-tools/overview.md**

```markdown
---
title: MCP Tools Overview
description: Overview of Engrammic's MCP tool surface.
---

Engrammic exposes tools via the Model Context Protocol (MCP). These tools are the primary interface for agents.

## Tool Profiles

Tools are organized into profiles:

### Standard Profile (default)

Core tools for most use cases:

| Tool | Purpose |
|------|---------|
| [remember](/mcp-tools/remember/) | Store observations |
| [learn](/mcp-tools/learn/) | Store facts with evidence |
| [believe](/mcp-tools/believe/) | Form conclusions |
| [recall](/mcp-tools/recall/) | Search and retrieve |
| [trace](/mcp-tools/trace/) | Follow provenance |
| [link](/mcp-tools/link/) | Create relationships |

### Reasoning Profile

Standard tools plus advanced reasoning:

| Tool | Purpose |
|------|---------|
| [reason](/mcp-tools/reason/) | Record reasoning chains |
| [reflect](/mcp-tools/reflect/) | Meta-observations |
| [hypothesize](/mcp-tools/hypothesize/) | Tentative beliefs |
| [revise](/mcp-tools/revise/) | Update hypotheses |
| [commit](/mcp-tools/commit/) | Crystallize to commitment |

### Always Available

| Tool | Purpose |
|------|---------|
| [patterns](/mcp-tools/patterns/) | Workflow templates |

## Quick Reference

```
Storing:
  remember  → Memory (no evidence)
  learn     → Knowledge (with evidence)
  believe   → Wisdom (from facts)
  reason    → Intelligence (session-only)

Retrieving:
  recall    → Search by query or ID
  trace     → Follow provenance chain

Connecting:
  link      → Create typed relationship

Meta:
  reflect   → Record understanding change
  hypothesize/revise/commit → Working beliefs
  patterns  → Reusable workflows
```
```

- [ ] **Step 2: Update mcp-tools/remember.md**

```markdown
---
title: remember
description: Store observations to the Memory layer.
---

Store observations without evidence requirements. Best for ephemeral context, user preferences, and session notes.

## Usage

```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User prefers TypeScript over JavaScript"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `observation` | string | Yes | The observation to store |
| `tags` | string[] | No | Tags for organization and retrieval |
| `decay_class` | string | No | Decay rate: `ephemeral`, `standard` (default), `durable`, `permanent` |

## Examples

**Basic observation:**
```json
{
  "tool": "remember",
  "arguments": {
    "observation": "User is debugging authentication flow"
  }
}
```

**With tags and decay:**
```json
{
  "tool": "remember",
  "arguments": {
    "observation": "Project uses pnpm, not npm",
    "tags": ["tooling", "preferences"],
    "decay_class": "durable"
  }
}
```

## When to Use

- Session context that may be useful later
- User preferences and working style
- Temporary notes during exploration
- Observations without a verifiable source

## When NOT to Use

- Facts that need evidence (use [learn](/mcp-tools/learn/))
- Conclusions from multiple facts (use [believe](/mcp-tools/believe/))
- Information you need to cite (use [learn](/mcp-tools/learn/))
```

- [ ] **Step 3: Create mcp-tools/learn.md**

```markdown
---
title: learn
description: Store facts with evidence to the Knowledge layer.
---

Store verifiable claims with their evidence. Facts in Knowledge persist until superseded.

## Usage

```json
{
  "tool": "learn",
  "arguments": {
    "claim": "API rate limit is 100 requests/minute",
    "evidence": "https://docs.example.com/limits"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `claim` | string | Yes | The factual claim |
| `evidence` | string | Yes | Source URL or reference |
| `confidence` | float | No | Confidence score 0-1 (default: 0.8) |
| `tags` | string[] | No | Tags for organization |
| `supersedes` | string | No | Node ID this claim replaces |

## Examples

**Basic fact:**
```json
{
  "tool": "learn",
  "arguments": {
    "claim": "OAuth tokens expire after 1 hour",
    "evidence": "https://docs.example.com/auth#expiry",
    "confidence": 0.95
  }
}
```

**Updating a fact:**
```json
{
  "tool": "learn",
  "arguments": {
    "claim": "OAuth tokens now expire after 2 hours",
    "evidence": "https://docs.example.com/changelog#v2",
    "confidence": 0.95,
    "supersedes": "node_old_expiry_fact"
  }
}
```

## When to Use

- Verifiable information from documentation
- API behaviors confirmed by testing
- Configuration values from official sources
- Anything you'd need to cite

## When NOT to Use

- Observations without sources (use [remember](/mcp-tools/remember/))
- Opinions or preferences (use [remember](/mcp-tools/remember/))
- Conclusions from multiple facts (use [believe](/mcp-tools/believe/))
```

- [ ] **Step 4: Create mcp-tools/believe.md**

```markdown
---
title: believe
description: Form conclusions in the Wisdom layer.
---

Form synthesized beliefs from multiple facts. Beliefs link to their supporting evidence.

## Usage

```json
{
  "tool": "believe",
  "arguments": {
    "belief": "This codebase follows repository pattern",
    "about": ["node_repo_class_1", "node_repo_class_2"]
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `belief` | string | Yes | The belief statement |
| `about` | string[] | Yes | Node IDs this belief is based on |
| `confidence` | float | No | Confidence score 0-1 (default: 0.7) |
| `tags` | string[] | No | Tags for organization |

## Examples

**From observed patterns:**
```json
{
  "tool": "believe",
  "arguments": {
    "belief": "Production environment needs higher memory limits than staging",
    "about": ["node_oom_incident_1", "node_oom_incident_2", "node_staging_success"],
    "confidence": 0.85
  }
}
```

**Architecture conclusion:**
```json
{
  "tool": "believe",
  "arguments": {
    "belief": "The system uses event sourcing for audit trails",
    "about": ["node_event_store_fact", "node_replay_capability"],
    "confidence": 0.9,
    "tags": ["architecture"]
  }
}
```

## When to Use

- Conclusions synthesized from multiple facts
- Patterns observed across sources
- Architectural or design beliefs
- Positions you're taking based on evidence

## When NOT to Use

- Single observations (use [remember](/mcp-tools/remember/))
- Individual facts (use [learn](/mcp-tools/learn/))
- Hunches without supporting facts (use [remember](/mcp-tools/remember/))

**The belief test:** "Based on [these facts], I believe [this conclusion]." If you can't fill in [these facts], it's not a belief yet.
```

- [ ] **Step 5: Create mcp-tools/recall.md**

```markdown
---
title: recall
description: Search and retrieve from memory.
---

Search across all layers or retrieve specific nodes by ID.

## Usage

**Search:**
```json
{
  "tool": "recall",
  "arguments": {
    "query": "authentication flow"
  }
}
```

**By ID:**
```json
{
  "tool": "recall",
  "arguments": {
    "node_id": "node_abc123"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No* | Semantic search query |
| `node_id` | string | No* | Specific node to retrieve |
| `tags` | string[] | No | Filter by tags |
| `layers` | string[] | No | Filter by layer: `memory`, `knowledge`, `wisdom` |
| `limit` | int | No | Max results (default: 10) |

*One of `query` or `node_id` required.

## Examples

**Semantic search:**
```json
{
  "tool": "recall",
  "arguments": {
    "query": "API rate limiting",
    "limit": 5
  }
}
```

**Filtered search:**
```json
{
  "tool": "recall",
  "arguments": {
    "query": "user preferences",
    "layers": ["memory"],
    "tags": ["preferences"]
  }
}
```

**Retrieve specific node:**
```json
{
  "tool": "recall",
  "arguments": {
    "node_id": "node_abc123"
  }
}
```

## Response Format

Returns array of nodes with:
- `id`: Node identifier
- `content`: The stored content
- `layer`: Which layer (memory/knowledge/wisdom)
- `confidence`: Confidence score
- `created_at`: Timestamp
- `tags`: Associated tags
- `relationships`: Connected nodes

## When to Use

- Finding relevant context before a task
- Retrieving specific stored information
- Checking what you already know about a topic
```

- [ ] **Step 6: Create mcp-tools/trace.md**

```markdown
---
title: trace
description: Follow the provenance chain of a node.
---

Trace where knowledge came from and how it evolved.

## Usage

```json
{
  "tool": "trace",
  "arguments": {
    "node_id": "node_abc123"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_id` | string | Yes | Node to trace |
| `depth` | int | No | How far to follow (default: 3) |
| `direction` | string | No | `backward` (default), `forward`, or `both` |

## Examples

**Trace origins:**
```json
{
  "tool": "trace",
  "arguments": {
    "node_id": "node_belief_xyz",
    "direction": "backward"
  }
}
```

**Trace impact:**
```json
{
  "tool": "trace",
  "arguments": {
    "node_id": "node_old_fact",
    "direction": "forward"
  }
}
```

## Response Format

Returns provenance chain:
```json
{
  "node": { "id": "node_belief", "content": "..." },
  "chain": [
    { "relationship": "DERIVED_FROM", "node": { "id": "node_fact_1", "content": "..." } },
    { "relationship": "DERIVED_FROM", "node": { "id": "node_evidence", "content": "..." } }
  ]
}
```

## Relationship Types

| Relationship | Meaning |
|--------------|---------|
| `DERIVED_FROM` | This came from that source |
| `EXTRACTED_FROM` | Extracted from document |
| `SUPERSEDES` | This replaces that |
| `PROMOTED_FROM` | Claim promoted to fact |
| `SUPPORTS` | Evidence supports claim |

## When to Use

- Understanding why you believe something
- Verifying the source of information
- Finding what superseded old information
- Auditing the evolution of knowledge
```

- [ ] **Step 7: Create mcp-tools/link.md**

```markdown
---
title: link
description: Create typed relationships between nodes.
---

Create explicit relationships between nodes in the knowledge graph.

## Usage

```json
{
  "tool": "link",
  "arguments": {
    "from_node": "node_abc",
    "to_node": "node_xyz",
    "relationship": "SUPPORTS"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `from_node` | string | Yes | Source node ID |
| `to_node` | string | Yes | Target node ID |
| `relationship` | string | Yes | Relationship type |

## Relationship Types

**Provenance:**
| Type | Meaning |
|------|---------|
| `DERIVED_FROM` | Source derivation |
| `EXTRACTED_FROM` | Document extraction |
| `SUPERSEDES` | Replaces older node |

**Semantic:**
| Type | Meaning |
|------|---------|
| `SUPPORTS` | Evidence for claim |
| `CONTRADICTS` | Conflicts with |
| `CORROBORATES` | Same claim, different source |
| `CAUSES` | Causal relationship |
| `PREVENTS` | Preventive relationship |
| `IMPLEMENTS` | Implementation of |
| `EXTENDS` | Extension of |
| `RELATES_TO` | Generic relation |

## Examples

**Evidence supports claim:**
```json
{
  "tool": "link",
  "arguments": {
    "from_node": "node_doc_reference",
    "to_node": "node_rate_limit_claim",
    "relationship": "SUPPORTS"
  }
}
```

**Track contradiction:**
```json
{
  "tool": "link",
  "arguments": {
    "from_node": "node_new_info",
    "to_node": "node_old_belief",
    "relationship": "CONTRADICTS"
  }
}
```

## When to Use

- Connecting evidence to claims
- Tracking contradictions
- Building concept maps
- Creating explicit dependencies
```

- [ ] **Step 8: Verify standard tools**

```bash
cd ../docs && pnpm build
```

Expected: Build succeeds.

- [ ] **Step 9: Commit**

```bash
cd ../docs && git add src/content/docs/mcp-tools/ && git commit -m "feat: add standard profile MCP tool pages"
```

---

## Task 6: MCP Tools Section - Reasoning Profile

**Files:**
- Create: `../docs/src/content/docs/mcp-tools/reason.md`
- Create: `../docs/src/content/docs/mcp-tools/reflect.md`
- Create: `../docs/src/content/docs/mcp-tools/hypothesize.md`
- Create: `../docs/src/content/docs/mcp-tools/revise.md`
- Create: `../docs/src/content/docs/mcp-tools/commit.md`
- Create: `../docs/src/content/docs/mcp-tools/patterns.md`

- [ ] **Step 1: Create mcp-tools/reason.md**

```markdown
---
title: reason
description: Record reasoning chains in the Intelligence layer.
---

Capture step-by-step reasoning. Intelligence layer is session-scoped.

## Usage

```json
{
  "tool": "reason",
  "arguments": {
    "goal": "Determine root cause of auth failure",
    "steps": [
      "Token is present in request",
      "Token signature validates",
      "Token is expired",
      "Conclusion: token refresh not triggering"
    ]
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `goal` | string | Yes | What you're reasoning about |
| `steps` | string[] | Yes | Sequential reasoning steps |
| `conclusion` | string | No | Final conclusion |
| `confidence` | float | No | Confidence in conclusion |

## Examples

**Debugging reasoning:**
```json
{
  "tool": "reason",
  "arguments": {
    "goal": "Why is the API returning 500?",
    "steps": [
      "Request reaches load balancer (verified in logs)",
      "Load balancer routes to backend (verified)",
      "Backend receives request (verified)",
      "Database query times out (found in traces)",
      "Timeout causes unhandled exception"
    ],
    "conclusion": "Database connection pool exhausted",
    "confidence": 0.85
  }
}
```

## Important

**Intelligence is session-scoped.** Reasoning chains do not persist across conversations. If you need the conclusion later, also store it via `remember` or `believe`.

## When to Use

- Complex problem-solving
- Multi-step analysis
- Decision-making with explicit steps
- Debugging investigations

## When NOT to Use

- Simple observations (use [remember](/mcp-tools/remember/))
- Information you need to persist (add a [remember](/mcp-tools/remember/) too)
```

- [ ] **Step 2: Create mcp-tools/reflect.md**

```markdown
---
title: reflect
description: Record meta-observations about understanding changes.
---

Capture when and why your understanding changed. Creates audit trail.

## Usage

```json
{
  "tool": "reflect",
  "arguments": {
    "observation": "I was wrong about the auth flow. Tokens refresh client-side.",
    "about": ["node_old_belief", "node_new_evidence"]
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `observation` | string | Yes | What changed in your understanding |
| `about` | string[] | No | Related node IDs |
| `tags` | string[] | No | Tags for organization |

## Examples

**Correcting a mistake:**
```json
{
  "tool": "reflect",
  "arguments": {
    "observation": "Previous belief about rate limits was outdated. API v2 doubled the limits.",
    "about": ["node_old_rate_limit", "node_new_rate_limit"]
  }
}
```

**Noting a contradiction:**
```json
{
  "tool": "reflect",
  "arguments": {
    "observation": "Documentation says X but code does Y. Need to verify which is correct.",
    "about": ["node_doc_claim", "node_code_behavior"],
    "tags": ["contradiction", "needs-verification"]
  }
}
```

## When to Use

- You update a belief based on new evidence
- You notice a contradiction
- You correct a mistake
- Your confidence shifts significantly

The history of belief is as valuable as current belief.
```

- [ ] **Step 3: Create mcp-tools/hypothesize.md**

```markdown
---
title: hypothesize
description: Create tentative beliefs for later crystallization.
---

Form working hypotheses that can be revised or committed later.

## Usage

```json
{
  "tool": "hypothesize",
  "arguments": {
    "hypothesis": "The memory leak is in the connection pool",
    "based_on": ["node_heap_dump", "node_connection_count"]
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `hypothesis` | string | Yes | The tentative belief |
| `based_on` | string[] | No | Supporting node IDs |
| `confidence` | float | No | Initial confidence (default: 0.5) |
| `tags` | string[] | No | Tags for organization |

## Examples

**Investigation hypothesis:**
```json
{
  "tool": "hypothesize",
  "arguments": {
    "hypothesis": "Cache invalidation is not propagating to all nodes",
    "based_on": ["node_stale_data_report", "node_cache_config"],
    "confidence": 0.6,
    "tags": ["investigation", "caching"]
  }
}
```

## Workflow

1. **hypothesize** - Form initial hypothesis
2. **revise** - Update as you learn more
3. **commit** - Crystallize to belief when confident

## When to Use

- Starting an investigation
- Forming a theory to test
- When you're not ready to commit to a belief

## Related Tools

- [revise](/mcp-tools/revise/) - Update hypotheses
- [commit](/mcp-tools/commit/) - Crystallize to belief
- [believe](/mcp-tools/believe/) - Direct belief (skip hypothesis stage)
```

- [ ] **Step 4: Create mcp-tools/revise.md**

```markdown
---
title: revise
description: Update working hypotheses with new information.
---

Modify existing hypotheses as you gather more evidence.

## Usage

```json
{
  "tool": "revise",
  "arguments": {
    "hypothesis_id": "node_hypothesis_xyz",
    "new_content": "Memory leak is in the event listener cleanup",
    "confidence": 0.75,
    "new_evidence": ["node_event_listener_count"]
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `hypothesis_id` | string | Yes | Hypothesis to revise |
| `new_content` | string | No | Updated hypothesis text |
| `confidence` | float | No | Updated confidence |
| `new_evidence` | string[] | No | Additional supporting nodes |

## Examples

**Refine based on evidence:**
```json
{
  "tool": "revise",
  "arguments": {
    "hypothesis_id": "node_cache_hypothesis",
    "new_content": "Cache invalidation fails specifically on Redis cluster failover",
    "confidence": 0.8,
    "new_evidence": ["node_redis_logs", "node_failover_timeline"]
  }
}
```

**Increase confidence:**
```json
{
  "tool": "revise",
  "arguments": {
    "hypothesis_id": "node_hypothesis_abc",
    "confidence": 0.9,
    "new_evidence": ["node_confirmed_test"]
  }
}
```

## When to Use

- New evidence supports or refines hypothesis
- Confidence level changes
- Scope of hypothesis narrows

## Related Tools

- [hypothesize](/mcp-tools/hypothesize/) - Create hypotheses
- [commit](/mcp-tools/commit/) - Crystallize when ready
```

- [ ] **Step 5: Create mcp-tools/commit.md**

```markdown
---
title: commit
description: Crystallize working hypotheses to beliefs.
---

Convert hypotheses to permanent beliefs in the Wisdom layer.

## Usage

```json
{
  "tool": "commit",
  "arguments": {
    "hypothesis_id": "node_hypothesis_xyz"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `hypothesis_id` | string | Yes | Hypothesis to crystallize |
| `final_statement` | string | No | Refined belief statement |
| `confidence` | float | No | Final confidence (defaults to hypothesis confidence) |

## Examples

**Simple commit:**
```json
{
  "tool": "commit",
  "arguments": {
    "hypothesis_id": "node_memory_leak_hypothesis"
  }
}
```

**With refinement:**
```json
{
  "tool": "commit",
  "arguments": {
    "hypothesis_id": "node_cache_hypothesis",
    "final_statement": "Redis cluster failover causes 30-second cache staleness window",
    "confidence": 0.9
  }
}
```

## What Happens

1. Hypothesis is marked as committed
2. New Belief node created in Wisdom layer
3. Evidence links preserved
4. Hypothesis remains for audit trail

## When to Use

- Investigation complete
- Confidence is high enough to act on
- Ready to treat hypothesis as established belief

## Related Tools

- [hypothesize](/mcp-tools/hypothesize/) - Create hypotheses
- [revise](/mcp-tools/revise/) - Update before committing
- [believe](/mcp-tools/believe/) - Direct belief (skips hypothesis)
```

- [ ] **Step 6: Create mcp-tools/patterns.md**

```markdown
---
title: patterns
description: Access workflow templates and skills.
---

Retrieve and apply reusable workflow patterns.

## Usage

**Get a pattern:**
```json
{
  "tool": "patterns",
  "arguments": {
    "action": "get",
    "name": "investigation"
  }
}
```

**List patterns:**
```json
{
  "tool": "patterns",
  "arguments": {
    "action": "list"
  }
}
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | `get`, `list`, or `search` |
| `name` | string | No | Pattern name (for `get`) |
| `query` | string | No | Search query (for `search`) |

## Available Patterns

| Pattern | Purpose |
|---------|---------|
| `onboarding` | New agent setup workflow |
| `investigation` | Structured debugging approach |
| `code-review` | Code review memory workflow |
| `learning` | Documentation learning workflow |

## Examples

**Get onboarding workflow:**
```json
{
  "tool": "patterns",
  "arguments": {
    "action": "get",
    "name": "onboarding"
  }
}
```

**Search patterns:**
```json
{
  "tool": "patterns",
  "arguments": {
    "action": "search",
    "query": "debug"
  }
}
```

## When to Use

- Starting a new type of task
- Need structured approach to a problem
- Onboarding to Engrammic

## Availability

`patterns` is always available regardless of tool profile.
```

- [ ] **Step 7: Verify all MCP tools**

```bash
cd ../docs && pnpm build
```

Expected: Build succeeds with all pages.

- [ ] **Step 8: Commit**

```bash
cd ../docs && git add src/content/docs/mcp-tools/ && git commit -m "feat: add reasoning profile MCP tool pages"
```

---

## Task 7: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Full build**

```bash
cd ../docs && pnpm build
```

Expected: Clean build, no errors or warnings.

- [ ] **Step 2: Run dev server and verify all pages**

```bash
cd ../docs && pnpm dev
```

Verify each section:
- [ ] Landing page: dual CTAs, 4 feature cards, logo
- [ ] Concepts: all 6 pages render
- [ ] Guides: all 4 pages render
- [ ] MCP Tools: all 13 pages render
- [ ] Sidebar navigation correct
- [ ] Internal links work

- [ ] **Step 3: Final commit**

```bash
cd ../docs && git add -A && git commit -m "docs: complete Engrammic documentation site"
```

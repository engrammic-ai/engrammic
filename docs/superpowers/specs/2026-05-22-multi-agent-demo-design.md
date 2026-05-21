# Multi-Agent Knowledge Sharing Demo

**Status:** Approved  
**Date:** 2026-05-22  
**Deployment:** `../web/showcase`

## Purpose

Marketing asset visualizing how multiple agents share knowledge through Engrammic. Target audience: non-technical investors (Nordic style). Not a production feature.

**Core message:** "Agents share a brain, not messages."

## Architecture

### Two-Zone Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          YOUR HARNESS                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  Researcher  │    │   Analyst    │    │   Outreach   │              │
│  │  [active]    │    │  [waiting]   │    │  [waiting]   │              │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘              │
├─────────┼──────────────────┼──────────────────┼────────────────────────┤
│         │                  │                  │                        │
│         ▼                  ▼                  ▼                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                                                                 │   │
│  │                        ENGRAMMIC                                │   │
│  │                                                                 │   │
│  │     ○ observed  ● verified  ◉ believed        [legend]         │   │
│  │                                                                 │   │
│  │                    ◉                                            │   │
│  │                   /|\                                           │   │
│  │                  ● ● ●                                          │   │
│  │                 /|\ /|\                                         │   │
│  │                ○ ○ ○ ○ ○                                        │   │
│  │                                                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key constraints:**
- Agents never connect to each other horizontally
- All connections go DOWN into graph (learn) or UP from graph (recall)
- Graph is the only coordination mechanism — this IS the visual story
- Explicit "Your Harness" / "Engrammic" labeling to clarify positioning

### Visual Hierarchy

| Zone | Purpose | Visual weight |
|------|---------|---------------|
| Your Harness (top) | Shows agents as external, yours to choose | ~30% of canvas |
| Engrammic (bottom) | The product — knowledge graph | ~60-70% of canvas |
| Event log (strip) | MCP calls, timestamps | ~10% optional |

## Visual Design

### Overall Aesthetic
- Dark background (#0a0a0f or similar)
- Clean, minimal UI chrome
- Graph is visually dominant

### Agent Cards (Your Harness zone)
- Generic role labels: "Researcher", "Analyst", "Writer" (per scenario)
- Status indicator: Active / Recalling / Learning / Idle
- Brief activity text
- Subtle color per agent (traces contributions in graph)

### Graph (Engrammic zone)
- **2.5D:** Flat layout with depth cues (shadows, parallax, layering)
- Nodes colored by contributing agent

### Epistemic Layering (visual, not labeled)

| Layer | Visual treatment | Position |
|-------|------------------|----------|
| Memory (observations) | Small, faded, lower opacity | Back layer, edges |
| Knowledge (facts) | Medium, solid, clear edges | Mid layer, central |
| Wisdom (beliefs) | Large, glowing, prominent | Front layer, focal |

**Legend** (always visible, corner of Engrammic zone):
```
○ observed  ● verified  ◉ believed
```

### Connection Animations
- **learn:** Line animates DOWN from agent to graph, node blooms with agent's color
- **recall:** Line pulses UP from graph to agent, relevant nodes highlight

## Key Moments

### 1. Simultaneity Beat
Demonstrates "no messaging" by showing parallel activity:
- Agent A is still active (status: "Analyzing...")
- Agent B recalls and uses A's node at the same time
- Visual: Both agents highlighted, pulse flows from graph to B while A is running

### 2. Provenance Beat
Answers "how do I know it's not hallucinating?":
- Final belief node pulses
- Evidence chain highlights in sequence (belief → facts → observations → source)
- ~2 second pause to let viewer trace the chain
- Optional "Why?" label appears briefly

## Scenarios

### Scope
- **Launch:** Deals scenario only, fully polished
- **Fast-follows:** Research and Code scenarios added post-launch
- Scenario picker exists from start (others show "coming soon")

### Scenario 1: Deal Qualification (primary)
- **Agents:** Researcher → Analyst → Outreach
- **Story:** Qualify a lead, assess fit, draft personalized outreach
- **Duration:** ~30-45 seconds
- **Aha moments:**
  - Simultaneity: Analyst uses Researcher's finding while Researcher still working
  - Provenance: Outreach recommendation traces back through assessment to raw research

### Scenario 2: Research Synthesis (fast-follow)
- **Agents:** Researcher → Analyst → Writer
- **Story:** Gather info, process findings, synthesize report
- **Duration:** ~30-45 seconds

### Scenario 3: Code/Debugging (fast-follow)
- **Agents:** Investigator → Historian → Fixer
- **Story:** Trace bug, recall similar past issues, apply learned solution
- **Duration:** ~30-45 seconds

## Data Model

### Scenario File Format

```json
{
  "id": "deals",
  "title": "Deal Qualification",
  "description": "Watch agents qualify and engage a prospect",
  "agents": [
    {"id": "a1", "role": "Researcher", "color": "#3b82f6"},
    {"id": "a2", "role": "Analyst", "color": "#22c55e"},
    {"id": "a3", "role": "Outreach", "color": "#f59e0b"}
  ],
  "events": [...]
}
```

### Event Types

| Type | Purpose | Fields |
|------|---------|--------|
| `status` | Update agent activity text | `agent`, `text` |
| `learn` | Create node in graph | `agent`, `node` (id, content, layer, evidence), `links` |
| `recall` | Highlight existing nodes | `agent`, `query`, `highlights` (node ids) |
| `link` | Draw edge between nodes | `from`, `to`, `type` |
| `pause` | Breathing room at key moments | `duration` (ms) |
| `trace` | Trigger provenance animation | `node` (id), `duration` |

### Node Schema

```json
{
  "id": "n1",
  "content": "Prospect raised $5M Series A",
  "layer": "knowledge",
  "evidence": ["https://techcrunch.com/..."],
  "agent": "a1"
}
```

### Example Event Sequence (deals scenario)

```json
[
  {"t": 0, "agent": "a1", "type": "status", "text": "Researching prospect..."},
  {"t": 2000, "agent": "a1", "type": "learn", "node": {
    "id": "n1", "content": "Prospect raised $5M Series A", "layer": "memory",
    "evidence": ["https://techcrunch.com/..."]
  }},
  {"t": 2500, "type": "pause", "duration": 1000},
  {"t": 3500, "agent": "a1", "type": "learn", "node": {
    "id": "n2", "content": "Budget confirmed at $50K/year", "layer": "knowledge",
    "evidence": ["node:n1", "https://linkedin.com/..."]
  }, "links": [{"from": "n2", "to": "n1", "type": "DERIVES"}]},
  {"t": 4500, "agent": "a1", "type": "status", "text": "Analyzing tech stack..."},
  {"t": 5000, "agent": "a2", "type": "status", "text": "Assessing fit..."},
  {"t": 5500, "agent": "a2", "type": "recall", "query": "prospect budget", "highlights": ["n2"]},
  {"t": 6500, "agent": "a2", "type": "learn", "node": {
    "id": "n3", "content": "Strong fit: budget and stage match ICP", "layer": "wisdom",
    "evidence": ["node:n2"]
  }, "links": [{"from": "n3", "to": "n2", "type": "DERIVES"}]},
  {"t": 7000, "type": "pause", "duration": 1500},
  {"t": 8500, "agent": "a3", "type": "recall", "query": "prospect fit assessment", "highlights": ["n3", "n2"]},
  {"t": 9500, "agent": "a3", "type": "status", "text": "Drafting outreach..."},
  {"t": 11000, "type": "trace", "node": "n3", "duration": 2000}
]
```

## Pacing Guidelines

- **Fast moments:** Status updates, background activity (~500ms between)
- **Key moments:** Node creation, recalls (~1-1.5s pause after)
- **Aha moments:** Simultaneity beat, provenance trace (~2s pause)
- Let nodes settle visually before next event
- Total scenario duration: 30-45 seconds feels right

## Scope Boundaries

### In scope (v1)
- Scripted replay engine
- One polished scenario (deals)
- Scenario picker UI (with "coming soon" for others)
- Desktop-focused layout
- 2.5D graph with epistemic layering
- Simultaneity and provenance beats
- Adjustable playback speed

### Out of scope (v1)
- Real-time interactivity (visitor queries)
- Mobile optimization (show "best on desktop")
- Audio/voiceover
- Click-to-explore graph interactions

### Fast-follows (v1.1+)
- Research and Code scenarios
- Optional click-to-trace interaction
- Embed widget for third-party sites

## Success Criteria

1. Non-technical investor watches for 30 seconds and understands "agents share knowledge without messaging"
2. Technical founder watches and thinks "I want this for my agents"
3. Runs smoothly on average laptop (60fps target)
4. Loads in < 3 seconds
5. The two aha moments (simultaneity, provenance) are unmissable

## Open Items

1. Exact color palette for agents and layers
2. Animation easing curves
3. Whether to include subtle ambient motion when idle
4. Font choices

---

*Reviewed by Opus agent 2026-05-22. Adjustments incorporated: legend for layers, simultaneity beat, provenance trace, pacing pauses, scope tightened to one launch scenario.*

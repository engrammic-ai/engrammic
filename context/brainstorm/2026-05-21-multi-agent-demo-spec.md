# Multi-Agent Knowledge Sharing Demo

Status: Spec
Date: 2026-05-21

## Purpose

Marketing/showcase demo visualizing how multiple agents share knowledge through Engrammic. Not a production feature — a polished visual asset for website and investor demos.

Core message: "Agents share a brain, not messages."

## Concept

3+ agents working on a task. As each agent learns, the shared knowledge graph updates. Other agents recall and build on each other's work. The visualization shows this happening in real-time.

## UI Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Engrammic — Multi-agent knowledge sharing              [Replay ▶] [1x] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                         SHARED KNOWLEDGE GRAPH                          │
│                         (WebGL canvas, ~60% height)                     │
│                                                                         │
│                    Nodes colored by source agent                        │
│                    Edges animate on recall/link                         │
│                    Active subgraph highlighted                          │
│                                                                         │
├────────────────┬────────────────┬────────────────┬──────────────────────┤
│   AGENT A      │    AGENT B     │    AGENT C     │   EVENT LOG          │
│   [icon] Name  │   [icon] Name  │   [icon] Name  │                      │
│   Role label   │   Role label   │   Role label   │   Scrolling feed of  │
│ ┌────────────┐ │ ┌────────────┐ │ ┌────────────┐ │   MCP calls with     │
│ │ Current    │ │ │ Current    │ │ │ Current    │ │   timestamps         │
│ │ activity   │ │ │ activity   │ │ │ activity   │ │                      │
│ │ or output  │ │ │ or output  │ │ │ or output  │ │   Click to highlight │
│ └────────────┘ │ └────────────┘ │ └────────────┘ │   in graph           │
└────────────────┴────────────────┴────────────────┴──────────────────────┘
```

## Visual Design

### Graph aesthetics
- Dark background (#0a0a0f or similar)
- Nodes: Glowing circles, colored by source agent
  - Agent A: Blue (#3b82f6)
  - Agent B: Green (#22c55e)  
  - Agent C: Amber (#f59e0b)
  - Shared/system: White/gray
- Node size: Scaled by confidence or edge count
- Edges: Subtle lines, animate with flowing particles on activity
- Layout: Force-directed, but with manual tuning for demo clarity

### Animations
- `learn`: Node fades in with glow pulse, edges draw from evidence nodes
- `recall`: Subgraph highlights, edges pulse toward recalling agent
- `link`: Edge draws between nodes with particle flow
- Agent activity: Subtle glow/pulse on agent card when active

### Agent cards
- Avatar/icon (can be simple geometric shapes)
- Name and role (e.g., "Researcher", "Analyst", "Writer")
- Current status: Thinking / Recalling / Learning / Idle
- Truncated current output or task

## Data Model

### Recorded session format
```json
{
  "scenario": "Research synthesis",
  "description": "Three agents collaborate on competitive analysis",
  "agents": [
    {"id": "agent-a", "name": "Scout", "role": "Researcher", "color": "#3b82f6"},
    {"id": "agent-b", "name": "Apex", "role": "Analyst", "color": "#22c55e"},
    {"id": "agent-c", "name": "Scribe", "role": "Writer", "color": "#f59e0b"}
  ],
  "events": [
    {
      "t": 0,
      "agent": "agent-a",
      "type": "status",
      "content": "Researching competitor landscape..."
    },
    {
      "t": 2500,
      "agent": "agent-a", 
      "type": "learn",
      "node_id": "abc-123",
      "content": "Competitor X raised Series B, pivoting to enterprise",
      "evidence": ["https://techcrunch.com/..."],
      "tags": ["competitive", "funding"]
    },
    {
      "t": 3000,
      "agent": "agent-b",
      "type": "recall",
      "query": "competitor funding news",
      "results": ["abc-123"]
    },
    {
      "t": 4500,
      "agent": "agent-b",
      "type": "learn",
      "node_id": "def-456",
      "content": "Competitor X enterprise pivot threatens our mid-market positioning",
      "evidence": ["node:abc-123"],
      "tags": ["analysis", "competitive"]
    }
  ]
}
```

### Graph state
- Nodes: id, content (truncated for display), agent_source, layer, position (x,y,z)
- Edges: from, to, type, animated (bool)
- Active highlight: list of node_ids currently emphasized

## Technical Stack

### Frontend
- **Framework**: React + TypeScript
- **Graph rendering**: react-force-graph-3d (Three.js based)
  - Supports WebGL, 3D optional (can flatten to 2D view)
  - Good animation primitives
  - Handles node/edge updates smoothly
- **Styling**: Tailwind CSS
- **State**: Zustand or simple useState (not complex)

### Playback engine
- Load scenario JSON
- Step through events on timer (adjustable speed)
- Expose controls: play/pause, speed (0.5x/1x/2x), scrub timeline
- Trigger graph updates and agent card updates per event

### Deployment
- Static build, deploy to Vercel/Cloudflare Pages
- Embed via iframe on main website
- Can also run standalone for live demos

## Scenarios to Build

### 1. Competitive research (primary)
- Scout researches 3 competitors
- Apex analyzes findings, identifies threats
- Scribe synthesizes into brief
- Shows: research -> analysis -> synthesis flow

### 2. Customer intelligence
- Support agent logs customer pain points
- Product agent recalls patterns across customers
- Strategy agent forms recommendations
- Shows: front-line learning -> pattern recognition -> strategic insight

### 3. Code review / debugging (technical audience)
- Investigator agent traces bug
- Historian agent recalls similar past issues
- Fixer agent applies learned solution
- Shows: technical use case, appeals to dev ICP

## Implementation Phases

### Phase 1: Core player (3-4 days)
- React app scaffold
- Graph component with react-force-graph
- Event playback engine
- Basic agent cards
- One hardcoded scenario

### Phase 2: Polish (2-3 days)
- Visual design pass (colors, glow effects, particles)
- Smooth animations and transitions
- Playback controls (speed, scrub)
- Responsive layout

### Phase 3: Scenarios (1-2 days per scenario)
- Record/script realistic agent sessions
- Tune graph layouts for visual clarity
- Add scenario selector

### Phase 4: Integration (1 day)
- Build for production
- Embed on website
- Test on mobile (graceful fallback or simplified view)

## Total effort estimate
- MVP (one scenario, polished): ~1 week
- Full (3 scenarios, production-ready): ~2 weeks

## Open questions

1. 3D or 2D graph? 3D is flashier but 2D might be clearer
2. Audio/voiceover? Could add narration explaining what's happening
3. Interactive variant? Let visitors type prompts (Phase 2+, more eng work)
4. Mobile: Simplified view or skip graph entirely?

## Success criteria

- Non-technical person watches for 30 seconds and understands "agents share knowledge"
- Technical person watches and thinks "I want this for my agents"
- Runs smoothly on average laptop (60fps)
- Loads in < 3 seconds

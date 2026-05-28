# Engrammic Demo Visualizer

**Status:** Approved  
**Date:** 2026-05-29  
**Purpose:** Interactive demo for Antler investor presentations

## Problem

Memory systems are hard to demo. The value is invisible - agents "just know" things, but you can't point at it. A video of chat doesn't convey what's happening under the hood.

## Solution

A split-screen web app that visualizes the knowledge graph updating in real-time as a scripted conversation plays out. Investors see both the chat AND the underlying memory structure.

## Layout

```
+-------------------------------------------------------------+
|  [Engrammic Demo]                              [scenario v] |
+---------------------------+---------------------------------+
|                           |                                 |
|   Chat Panel              |   Knowledge Graph               |
|   (left, ~40%)            |   (right, ~60%)                 |
|                           |                                 |
|   [User]: message         |        o---o                    |
|   [Agent]: response       |       /     \                   |
|                           |      o       o--o               |
|   [press enter]           |               \                 |
|                           |                o                |
|                           |                                 |
+---------------------------+---------------------------------+
|  Status: "Recalling..."   |     Nodes: 12  |  Edges: 8      |
+-------------------------------------------------------------+
```

### Panels

**Chat Panel (left, 40%)**
- Scripted conversation, advances on Enter keypress
- Shows user messages and agent responses
- Status indicator for current operation (storing, recalling, etc.)

**Graph Panel (right, 60%)**
- Knowledge graph visualization
- Pre-positioned nodes (no physics jitter)
- Updates on MCP operations

**Footer**
- Current operation status
- Node/edge counts

**Header**
- Scenario dropdown to switch between vignettes

## Interaction Flow

1. Page loads with scenario 1, graph shows pre-existing nodes (~15)
2. User presses Enter - first chat message appears
3. MCP call fires to real backend
4. Graph updates: new node fades in or edge animates
5. On recall: relevant nodes/edges glow briefly
6. Repeat until scenario ends
7. Dropdown to switch scenarios (resets graph to that scenario's initial state)

## Scenarios

Three vignettes demonstrating memory failures and fixes:

### Scenario 1: "I already told you that"

**Setup:** User states "I prefer TypeScript with functional style, no classes"

**Test:** Few exchanges later, user asks "Write me a React component for a user card"

**Without memory:** Agent writes class component

**With memory:** Agent writes functional component, graph shows recall path to preference node

**Graph events:**
- Preference node created on initial statement
- Recall lights up preference node when generating component

### Scenario 2: "We already rejected that"

**Setup:** User states "I tried Redux before, it was overkill, let's avoid it"

**Test:** Later asks "How should I handle global state?"

**Without memory:** Agent suggests Redux

**With memory:** Agent suggests Zustand/Jotai, avoids Redux

**Graph events:**
- Rejection node created
- Recall shows rejection being checked before recommendation

### Scenario 3: "Remember the constraints"

**Setup:** User states "Budget is $20/mo max for hosting"

**Test:** Later asks "What's the best way to deploy this?"

**Without memory:** Agent suggests expensive stack (Vercel Pro + PlanetScale)

**With memory:** Agent suggests Railway free tier, stays within budget

**Graph events:**
- Constraint node created
- Recall shows budget constraint influencing recommendation

## Visual Design

### Color Palette

| Role | Color | Usage |
|------|-------|-------|
| Primary | Bone white (#F5F5F0) | Background, canvas |
| Secondary | Charcoal (#333333) | Nodes, edges, text |
| Accent | Oxide red (#B7410E) | Recall glow, new node pulse, active paths |

### Node Styling

- **Default:** Charcoal fill, subtle darker border, rounded
- **New node:** Fade in with brief oxide red pulse, settles to charcoal
- **Recalled:** Oxide red glow ring, fades after 1-2s

### Edge Styling

- **Default:** Charcoal, thin (1-2px)
- **New edge:** Draw animation (line extends from source to target)
- **Recalled path:** Shifts to oxide red, slightly thicker

### Animations

Keep minimal - no constant motion, only on state changes:

- **Node appear:** 300ms fade in + subtle scale (0.8 to 1.0)
- **Edge appear:** 400ms draw animation
- **Recall glow:** 200ms ease-in, hold 1s, 500ms fade-out
- **No physics simulation** - positions are pre-defined per scenario

## Graph Constraints

- **Max 25 nodes** at any time per scenario
- **Pre-existing:** ~15 nodes (context, prior knowledge)
- **Added during demo:** ~8 nodes (new preferences, reasoning)
- **Reset between scenarios** - each vignette has its own graph state

## Node Types

| Type | Visual | Description |
|------|--------|-------------|
| Memory | Circle | User observations, preferences |
| Knowledge | Rounded square | Verified facts with evidence |
| Belief | Diamond | Conclusions, decisions |
| Constraint | Hexagon | Boundaries, limits |

## Data Model

### Scenario Definition

```typescript
interface Scenario {
  id: string;
  name: string;
  description: string;
  initialGraph: GraphState;
  steps: ScenarioStep[];
}

interface ScenarioStep {
  role: 'user' | 'agent';
  message: string;
  graphEvents?: GraphEvent[];
  delay?: number; // ms before next step is allowed
}

interface GraphEvent {
  type: 'add_node' | 'add_edge' | 'recall';
  data: NodeData | EdgeData | RecallData;
}

interface GraphState {
  nodes: NodeData[];
  edges: EdgeData[];
}

interface NodeData {
  id: string;
  type: 'memory' | 'knowledge' | 'belief' | 'constraint';
  label: string;
  position: { x: number; y: number };
}

interface EdgeData {
  id: string;
  source: string;
  target: string;
  label?: string;
}

interface RecallData {
  nodeIds: string[];
  edgeIds: string[];
}
```

### Example Scenario Step

```json
{
  "role": "user",
  "message": "I prefer TypeScript with functional style, no classes",
  "graphEvents": [
    {
      "type": "add_node",
      "data": {
        "id": "pref-functional",
        "type": "memory",
        "label": "Prefers functional style",
        "position": { "x": 200, "y": 150 }
      }
    },
    {
      "type": "add_edge",
      "data": {
        "source": "user-context",
        "target": "pref-functional",
        "label": "stated"
      }
    }
  ]
}
```

## Technical Approach

### Frontend

- **Framework:** React (or vanilla JS + D3 for lighter weight)
- **Graph rendering:** D3.js for SVG-based graph
- **State:** Local state, no Redux needed
- **Scenario data:** JSON files, bundled or fetched

### Backend Integration

- Calls real Engrammic MCP endpoints for authenticity
- Can fall back to mocked responses if backend unavailable
- WebSocket not required - scripted timing is sufficient for demo

### Deployment

- Static site (Vercel, Netlify, or GCS bucket)
- No auth required - demo scenarios only
- URL: demo.engrammic.ai or similar

## Implementation Estimate

| Task | Time |
|------|------|
| Layout + chat panel | 0.5 day |
| Graph rendering (D3) | 1 day |
| Animations (node/edge/glow) | 0.5 day |
| Scenario data authoring | 0.5 day |
| Backend integration | 0.5 day |
| Polish + testing | 0.5 day |
| **Total** | **3-4 days** |

## Out of Scope

- Agent "walking" animation on graph
- Real-time physics layout
- Reasoning chain visualization
- WebSocket streaming
- Multiple simultaneous users
- Mobile responsiveness

## Success Criteria

1. Investor can press Enter repeatedly and watch demo play out
2. Graph updates are smooth and clearly tied to conversation
3. Recall moments create visible "aha" when paths light up
4. Three scenarios demonstrate distinct memory value props
5. Runs reliably during live presentation

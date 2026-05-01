# EAG System Infographic Spec

Reference diagrams for design partner presentations. Jane produces final assets.

## Style Reference

Isometric line-art, inspired by Nobody Engineering (see `style-reference/` folder):
- Black strokes on white background
- Single accent color for wires/connections and highlights
- Clean isometric 3D blocks (30-degree projection)
- Smooth curved cables connecting components
- Bracket-style callout labels
- Minimal detail inside blocks

## Diagrams

### 1. Layer Stack (`01-layer-stack.svg`)

Four isometric blocks stacked vertically, bottom to top:

```
           _______________
          /              /|
         /  Intelligence/ |
        /_____________/  |
        |             |  /
        |_____________|/
           _______________
          /              /|
         /    Wisdom    / |
        /_____________/  |
        |             |  /
        |_____________|/
           _______________
          /              /|
         /  Knowledge   / |
        /_____________/  |
        |             |  /
        |_____________|/
           _______________
          /              /|
         /    Memory    / |
        /_____________/  |
        |             |  /
        |_____________|/
```

- Each block same size, slight vertical gap between them
- Labels on the side with bracket callouts
- No wires in this view

Purpose: "Here are the four layers"

---

### 2. Transitions (`02-transitions.svg`)

Same isometric stack with wire connections showing data flow:

```
        ┌─────────────────┐
        │  Intelligence   │
        └────────┬────────┘
                 │ ←─── consensus (to Knowledge)
                 │ ←─── trace (to Memory)
                 │ ←─── commit (to Wisdom)
        ┌────────┴────────┐
        │     Wisdom      │
        └────────┬────────┘
                 ↑ synthesize
                 │ (+ revise loops back to self)
        ┌────────┴────────┐
        │   Knowledge     │
        └────────┬────────┘
                 ↑ extract
                 │ (+ supersede loops back to self)
        ┌────────┴────────┐
        │     Memory      │
        └─────────────────┘
                 ↑ 
              (input)
```

Wires to show:
- Memory to Knowledge: "extract"
- Knowledge to Wisdom: "synthesize"
- Knowledge to Knowledge (self-loop): "supersede"
- Wisdom to Wisdom (self-loop): "revise"
- Intelligence to Knowledge: "consensus"
- Intelligence to Memory: "trace"
- Intelligence to Wisdom: "commit"

Wire style: smooth curves like the orange cables in Nobody Engineering reference. Labels are transition names along the wires.

Purpose: "How information flows between layers"

---

### 3. Inputs/Outputs (`03-inputs-outputs.svg`)

The stack as a unit with I/O elements:

```
     INPUTS                              CONSUMERS

  ┌─────────┐                           ┌─────────┐
  │Documents│───┐                  ┌───→│ Agent A │
  └─────────┘   │                  │    └─────────┘
  ┌─────────┐   │    ┌─────────┐   │
  │  Convos │───┼───→│  STACK  │───┤
  └─────────┘   │    └─────────┘   │
  ┌─────────┐   │                  │    ┌─────────┐
  │ Actions │───┘                  └───→│ Agent B │
  └─────────┘                           └─────────┘
```

- Left: input sources (documents, conversations, agent actions) as small isometric blocks
- Center: the 4-layer stack as one unit (can be simplified or show all 4 layers)
- Right: agents consuming from the system
- Wires connecting inputs to stack to agents

Purpose: "What goes in, who uses it"

---

### 4. Overview (`04-overview.svg`)

Combined view showing full system:

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   INPUTS          LAYER STACK            CONSUMERS      │
│                                                         │
│  ┌────────┐      ┌───────────┐                         │
│  │  Docs  │─┐    │Intelligence│───┐      ┌─────────┐   │
│  └────────┘ │    └─────┬─────┘   │       │         │   │
│  ┌────────┐ │    ┌─────┴─────┐   │       │  Agent  │   │
│  │ Convos │─┼───→│  Wisdom   │───┼──────→│    A    │   │
│  └────────┘ │    └─────┬─────┘   │       │         │   │
│  ┌────────┐ │    ┌─────┴─────┐   │       └─────────┘   │
│  │Actions │─┘    │ Knowledge │───┤                     │
│  └────────┘      └─────┬─────┘   │       ┌─────────┐   │
│                  ┌─────┴─────┐   │       │  Agent  │   │
│                  │  Memory   │───┴──────→│    B    │   │
│                  └───────────┘           └─────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- Full isometric stack in center with transition wires visible
- I/O elements flanking left and right
- All transition flows shown
- Denser than the others

Purpose: "Whole system at a glance"

---

## SVG Wireframes

The accompanying `.svg` files are structural wireframes showing:
- Exact isometric block positions and sizes
- Wire routing paths
- Label placements

They are not styled. Jane applies the line-art style (stroke weights, accent color, final typography).

## Usage

These are visual aids for live explanation to design partners. Keep them clean and scannable. You talk, you point at the diagram.

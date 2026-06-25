# Reference Agent + Decision Classifiers Design

## Problem Statement

MCP tool descriptions have a ceiling on behavioral enforcement. Research confirms:
- Instruction attention decays exponentially over long conversations
- Tools mid-manifest get less attention (lost-in-the-middle effect)
- Multi-turn tool compliance is under-explored in literature
- 65% of enterprise AI failures attributed to context drift

Engrammic cannot rely on agents using memory tools correctly via MCP alone. External enforcement is necessary.

## Strategy

**Reference agent + small model augmentation:**

1. Build a reference agent that uses Engrammic correctly (controlled loop)
2. Use it to generate training data (10k-100k decision trajectories)
3. Distill into small models (timing, routing, salience classifiers)
4. Deploy classifiers as sidecar/wrapper for any agent

The reference agent serves dual purpose: proof point (benchmark) and data flywheel (training).

## Reference Agent

### Type

Research + task hybrid agent. Manages projects across sessions, gathers information from multiple sources, reconciles conflicting claims, tracks state changes.

Maps to BEAM benchmark requirements (contradiction resolution, temporal reasoning, belief updates).

### Integration Architecture

State machine skeleton + LLM judge at transitions + self-report within turns.

#### State Machine (6 states)

| State | Description | Entry Trigger |
|-------|-------------|---------------|
| `idle` | No active task | Task completion or session start |
| `orienting` | Understanding task scope, loading context | User provides task |
| `researching` | Gathering information, exploring | Scope understood |
| `synthesizing` | Drawing conclusions from gathered info | Research complete |
| `executing` | Taking action based on conclusions | Conclusions formed |
| `completing` | Wrapping up, final documentation | Execution done |

#### Transition Memory Operations

| Transition | Mandatory Decision Point |
|------------|-------------------------|
| idle -> orienting | Recall relevant prior knowledge |
| orienting -> researching | Tick (engagement signal) |
| researching -> synthesizing | Learn findings with evidence |
| synthesizing -> executing | Trace provenance before acting |
| executing (on corrections) | Update with supersedes |
| * -> completing | Learn final conclusions |

#### LLM Judge

At each transition, a separate LLM call evaluates:
- What Engrammic operations apply?
- With what parameters?
- Explicit reasoning for the decision

Structured output:
```json
{
  "ops": [
    {"tool": "learn", "params": {"content": "...", "evidence": [...]}, "reason": "..."}
  ],
  "skipped": [
    {"tool": "remember", "reason": "ephemeral, not worth storing"}
  ]
}
```

#### Self-Report (Mid-Turn)

Within states, agent emits memory actions in structured blocks:

```xml
<memory_actions>
[{"action": "remember", "content": "...", "reason": "..."}]
</memory_actions>
```

Position before response to reduce skipping. Require reason field for training data quality.

## Training Data Schema

Every decision logged:

```json
{
  "session_id": "...",
  "timestamp": "...",
  "state": "researching",
  "trigger": "transition | mid_turn",
  "context": {
    "conversation_window": "last N turns",
    "graph_summary": "relevant existing nodes",
    "task_description": "..."
  },
  "decision": {
    "ops": [{"tool": "learn", "params": {...}, "reason": "..."}],
    "skipped": [{"tool": "remember", "reason": "..."}]
  },
  "outcome": {
    "stored_node_ids": ["..."],
    "later_retrieved": true,
    "helped_task": true,
    "retrieval_turn": 15
  }
}
```

Outcome tracking enables RL: reward signal based on whether stored memory was retrieved and helpful.

## Small Model Pipeline

### Phase 1: Data Collection (4-8 weeks)

Reference agent generates 10k+ decision trajectories through:
- Internal dogfooding (daily usage)
- Synthetic task generation
- Beta user sessions (with consent)

Target: 10k minimum, 50k stretch goal.

### Phase 2: Classifier Distillation (2-4 weeks)

Train classifier heads on BGE-M3 embeddings:

| Classifier | Input | Output | Architecture |
|------------|-------|--------|--------------|
| Timing | conversation window embedding | should_call: bool | MLP head |
| Routing | statement embedding | layer: Memory/Knowledge/Skip | MLP head |
| Salience | statement embedding | worth_storing: float | MLP head |
| Supersession | statement + graph context | supersedes_node_id: str? | Retrieval + MLP |

Initial training: behavioral cloning from logged decisions.

### Phase 3: RL Correction (2-4 weeks)

Fine-tune with outcome rewards:
- Positive: stored memory was retrieved AND helped task
- Negative: stored memory was never retrieved OR hurt task
- Neutral: stored but outcome unclear

Addresses distribution shift from pure imitation.

### Phase 4: Sidecar Deployment (1-2 weeks)

Package classifiers as:
- Standalone process monitoring agent conversation
- Injects Engrammic operations via same MCP connection
- Works with any base agent (Claude, GPT, Gemini, etc.)

## Deliverables

### Phase A: Proof Point

Reference agent that:
- Wins BEAM benchmark (contradiction resolution, temporal reasoning)
- Demonstrates correct memory behavior across sessions
- Generates training data continuously

### Phase B: Infrastructure

Decision classifiers that:
- Run as sidecar alongside any agent
- Handle timing, routing, salience decisions
- Integrate via MCP (same tool surface)
- Work across harnesses (Claude Code, Codex, Gemini, etc.)

## Research Validation

This design is informed by:

| Finding | Source | How Addressed |
|---------|--------|---------------|
| Multi-turn compliance under-explored | arxiv tool following survey | State machine + continuous logging |
| Instruction attention decays | Lost in the Middle (TACL 2024) | External classifiers, not relying on attention |
| 3B models match 7B+ with task-specific SFT | arxiv distillation papers | Classifier heads on embeddings |
| BC + RL beats pure imitation | Reinforced Distillation (2509.14257) | RL correction phase planned |
| Provenance underdeveloped | Agent memory survey | CITE schema, trace tool |
| Write policies are heuristic | A-MEM, Mem0 papers | Learned classifiers replace heuristics |

## Non-Goals

- Full agent runtime (use existing harnesses)
- Replacing MCP surface (classifiers invoke same tools)
- Real-time contradiction detection in v1 (add after core classifiers work)
- Multi-agent coordination in v1 (single-agent focus first)

## Open Questions

1. **Classifier granularity**: One multi-task model or pipeline of specialists?
2. **Latency budget**: How much overhead is acceptable per turn?
3. **Harness integration depth**: Sidecar vs embedded vs wrapper?
4. **Training data quality**: How to validate logged decisions are actually correct?

## Success Criteria

1. Reference agent achieves top-3 on BEAM benchmark
2. Classifiers reach >85% accuracy on held-out decisions
3. Sidecar adds <100ms latency per turn
4. At least one third-party agent successfully integrates

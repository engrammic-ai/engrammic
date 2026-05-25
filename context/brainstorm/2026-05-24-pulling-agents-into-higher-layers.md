# Pulling agents into the higher cognitive layers

Status: brainstorm, not a plan
Date: 2026-05-24

## The friction

Agents using Engrammic's MCP tools default to the lower two layers (`remember`, `learn`, `recall`). The upper two (`believe`, `reason`, `reflect`, `hypothesize`, `commit`) almost never get used unless the system prompt explicitly tells the agent to use them every turn. This is observable across harnesses (Claude Code, Cursor, Codex) and across models.

The cause is structural, not a tooling bug:

- Lower-layer verbs are I/O. They have natural triggers in an agent loop ("I just observed X" so save it, "I need to know Y" so look it up).
- Upper-layer verbs are metacognitive. They require the agent to pause and synthesize. There is no natural trigger for "now is the moment to form a belief."
- Current harnesses optimize for task completion. Metacognition is, from the harness's point of view, off-task.

Even with good tool descriptions and skill guidance, agents skip the higher layers because nothing forces them to engage.

## What the literature shows

Every mechanism that reliably produces metacognitive behavior in agents is **harness-controlled and mandatory**, not model-initiated and optional. Voluntary reflection tools get skipped.

- **Reflexion** (Shinn 2023). Harness-level evaluator scores each trial. Sub-threshold scores trigger a self-reflection model automatically. Reflection output is mandatorily prepended to next trial.
- **Generative Agents** (Park 2023). Observations carry importance scores. When the running sum crosses 150, a reflection cycle fires. Trigger lives in the simulator, not the agent.
- **A-MEM** (2025). Every write triggers LLM-driven memory linking and rewrites neighbor descriptions. No agent choice.
- **MemGPT/Letta**. Timer interrupts and message events fire memory ops before generation.
- **MemR³** (2025). Closest published analog. A router runs multiple retrieval rounds, feeding gaps into a reflect node before responding. Reflection lives inside the retrieval loop.

Production harnesses (Claude Code, Devin, OpenHands) have essentially no metacognitive architecture. Where reflection-like behavior exists, it is enforced by the harness, not chosen by the agent.

## The design

We pull agents into the higher layers through three coordinated mechanisms.

### 1. SAGE does the heavy lifting

Belief formation is mostly a system problem, not an agent problem. Agents are evidence producers; SAGE forms beliefs and surfaces them back.

- `sage.synthesizer` crystallizes ProposedBeliefs from fact clusters and merges overlapping beliefs. Needs to run more aggressively than today.
- `sage.validator` (currently planned but uncadenced) is the natural home for contradiction detection across the graph. Engagement candidates of the "two corroborated facts disagree" type originate here.
- `sage.groundskeeper`'s heat signals rank engagement candidates (hot nodes with unresolved hypotheses get higher priority).
- `sage.custodian` is not directly in this loop; it continues handling ingestion.

This matches the A-MEM pattern (system synthesizes) and fits the SAGE architecture we already have. Cost is more LLM spend in synthesizer and validator.

### 2. Pull-from-recall surfacing

When `recall` returns results, the response also surfaces pending-synthesis material the agent should engage with: pending WorkingHypotheses on this topic, open ProposedBeliefs from `sage.synthesizer`, contradictions flagged by `sage.validator`, stale Commitments where new evidence has arrived.

Attaches metacognitive prompts to an operation the agent already performs frequently. No new entry point, no new habit to build.

A soft field alone is still optional and agents will skim past it (same failure mode as today's tool descriptions). So we combine soft surfacing with a hard checkpoint trigger.

### 3. Soft field plus hard checkpoint

**Soft engagement field on `recall`.** Sparse and reference-only. Populated in maybe 10-20% of recalls when there is genuinely relevant pending synthesis. Format is a single short line:

```
engagement: "Pending hypothesis h_abc on this topic - commit/revise/ignore"
```

Roughly 30 tokens. The agent can act on it or skim past.

**Hard checkpoint when a threshold trips.** Modeled on Generative Agents' importance threshold. Triggered when (a) a high-confidence contradiction exists, (b) topic overlap with the agent's current trajectory is high, and (c) the agent has touched related nodes N+ times this session. When tripped, `recall` returns an "engagement required" object instead of normal results until the agent calls `commit`, `revise`, or `dismiss`. Rare, but not skippable.

The engagement payload, when present, borrows MemR³'s explicit (evidence, gaps) structure:

```
engagement: {
  evidence: ["Knowledge n_ab claims X, sourced [s1, s2]"],
  gaps: ["Hypothesis h_cd claims Y, unresolved"],
  decision_required: "commit | revise | dismiss"
}
```

Footprint-disciplined. Gives the agent something concrete instead of "there is a contradiction somewhere."

The mandatory-when-it-matters property matches what the literature shows actually works.

## How recall changes

Recall stays single-pass. We considered borrowing MemR³'s router-as-state-machine but their multi-round structure exists to solve "do I have enough evidence to answer?" - we already have what we retrieved. The state machine collapses into one decision applied once.

New shape:

1. Fetch nodes (existing path).
2. Run engagement detector concurrently with Memgraph hydrate (once Qdrant returns IDs, the about-set is known).
3. Single deterministic decision: tag the response with `engagement: null | soft_reference | hard_checkpoint`.

The agent still calls one tool. Metacognition happens server-side.

## Latency budget

Stated targets: 20ms cached, 250ms search, 500ms graph depth-2.

| Step                              | Cost      | Notes                                          |
|-----------------------------------|-----------|------------------------------------------------|
| Existing fetch (search)           | ~200ms    | Embedding + Qdrant + Memgraph hydrate          |
| Engagement detector (live graph)  | 50-200ms  | Markers touching the about-set                 |
| Router decision (deterministic)   | <5ms      | Rules over candidate set                       |

Sequential worst case ~450ms. Parallelized (detector runs alongside hydrate): closer to `max(fetch, detect)`, comfortably under 500ms.

Disciplines that keep us under budget:

- **Parallel, not sequential.** Detector starts as soon as Qdrant returns IDs.
- **Timeout-bounded.** Cap engagement detection at ~50ms. If it misses, return without an engagement field. Soft engagement is optional by definition; silent degrade is correct under load.
- **Precompute the engagement markers.** SAGE writes marker entities (e.g. Contradiction nodes from `sage.validator`, ProposedBelief from `sage.synthesizer`) async. Recall just queries "marker entities touching these about-ids." That keeps the detector cheap and reliable. Live semantic comparison at recall time is not viable inside the budget.

The 50-200ms range for the detector is a guess. The single measurement that discriminates "live detection works" from "we need to precompute everything" is running the detector query against a representative silo.

## Implementation order

Sequenced, not parallel:

1. **Tune `sage.synthesizer` and stand up `sage.validator`.** Synthesizer needs to produce ProposedBeliefs faster. Validator needs to exist at all - currently planned but uncadenced. Without these two doing their job, the engagement field is empty most of the time and we cannot tell if surfacing works or just has nothing to surface. Load-bearing.
2. **Measure the detector query.** Pick a representative silo, write the graph query for pending hypotheses + ProposedBeliefs + contradictions touching a given about-set. Measure cold and warm costs.
3. **Prototype the soft field, dark launch.** Ship engagement detection plus soft field in `recall`. Measure engagement-rate: when an engagement item is surfaced, does the agent ever follow up with `commit` / `revise` / `dismiss`? If below ~10%, soft is dead weight and we skip ahead.
4. **Build the precomputed hard-checkpoint index.** Denormalized `open_engagements_by_about_node` structure. Written by `sage.synthesizer` and `sage.validator`. Read in O(1) by recall.
5. **Ship hard checkpoint surfacing.** Recall returns engagement-required object instead of normal results until the agent acts.

## Open design questions

- **Marker shape.** When `sage.validator` detects a contradiction, what does it write? Probably a `Contradiction` node with `:CONFLICTING` edges to the two Knowledge nodes and `:TOUCHES` edges to about-nodes. Node form gives audit trail, independent status (open/resolved/dismissed), and lets validator accrue multiple pieces of evidence for the same conflict. Storage cost is bounded by contradiction count, which should be small relative to facts. Cleanup needs design (what happens when underlying nodes are superseded or forgotten).
- **Stale-commitment marker.** Less obvious than contradictions. Could be a node, an edge from new evidence to the commitment, or a flag on the commitment. "Evidence has arrived" is a fuzzier signal than "two claims oppose."
- **Session state.** Hard checkpoint threshold needs "agent has touched related nodes N times this session." We do not have a session concept today. Options: Redis key per `(silo_id, session_id)`, opaque token in responses, graph-native dismiss edges keyed to agent identity. Each has footprint and lifetime tradeoffs.
- **Dismiss verb.** Records "agent saw and rejected" with a reason. Drives threshold tuning over time. New tool or a `recall` parameter.
- **Per-write engagement.** Should `learn` also surface engagement (the new claim might contradict an existing belief)? Probably yes, but changes the write-path latency story.
- **Cardinality bounds in the detector query.** If an about-node is touched by hundreds of pending hypotheses, the query bloats. Need `ORDER BY confidence DESC LIMIT N` inside the query.
- **Freshness of markers.** If validator runs every N minutes and a contradiction lands between runs, recall will not see it until the next run. Acceptable, or do we need write-triggered validation for high-priority cases?
- **How this composes with `patterns` and skills.** Skills today nudge toward higher layers. Once engagement is surfaced structurally, do skills shrink, or shift to teaching agents how to respond well?

## Sources

- Reflexion: https://arxiv.org/abs/2303.11366
- Generative Agents: https://arxiv.org/abs/2304.03442
- A-MEM: https://arxiv.org/html/2502.12110v11
- MemR³: https://arxiv.org/pdf/2512.20237
- Memory for Autonomous LLM Agents (survey): https://arxiv.org/html/2603.07670v1
- Hindsight is 20/20: https://arxiv.org/html/2512.12818v1
- Dive into Claude Code: https://arxiv.org/html/2604.14228v1

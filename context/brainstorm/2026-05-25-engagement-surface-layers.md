# Engagement surface: MCP, hooks, harness

Status: brainstorm, not a plan
Date: 2026-05-25
Builds on: [2026-05-24-pulling-agents-into-higher-layers.md](2026-05-24-pulling-agents-into-higher-layers.md)

## Frame

The 05-24 doc establishes that pulling agents into the higher cognitive layers requires harness-enforced mechanisms, not voluntary tool descriptions. That conclusion raises a strategic question: how much of the engagement design can ship through the MCP tool surface alone, and how much needs a control loop we own?

We split the surface into three layers:

1. **Layer 1: MCP-only.** Tool response shapes, new agent verbs, skill nudges, AGENTS.md guidance. Ships in-process with the rest of the MCP server. Works in any harness that speaks MCP.
2. **Layer 2: Hook surface.** Cross-harness hook configs that invoke a lightweight MCP verb on schedule or after specific events. Closes the "agent never called recall" gap without forking the agent loop. We ship reference configs; the harness owns the trigger.
3. **Layer 3: Custom harness.** Full Reflexion-style control loop. Out of scope as a product. Speccing it as research / competitive intel only.

Engrammic ships layers 1 and 2. Layer 3 is a decision rule, not a roadmap item.

### Why this split

Engrammic's positioning is harness-agnostic. We support Claude Code, Codex, Cursor, Gemini CLI, and whatever comes next. Building a custom harness contradicts that distribution story. Hooks give us most of the control a harness would, without owning the loop.

The MCP-only layer is the durable surface. Hooks accelerate it where harnesses support them. Both should provide value independently: layer 2 should not be a prerequisite for layer 1 to be useful.

## Layer 1: MCP-only design

### Recall response shape

Recall gains an `engagement` field. Null when nothing is pending. Populated when the engagement detector finds markers touching the about-set.

```
recall_response: {
  results: Node[],
  engagement: null | {
    mode: "soft" | "hard",
    marker_ids: string[],
    evidence: string[],
    gaps: string[],
    decision_required: "commit" | "revise" | "dismiss"
  }
}
```

Soft engagement is an extra field the agent can read or skim past. Hard engagement is intended to be non-skippable. The exact shape of "non-skippable" is an open decision (see below).

### Agent verbs for responding

Today's agent surface has `commit` (crystallizes hypotheses into Commitments) and `revise` (updates working hypotheses). It does not have an agent-facing path to accept or reject system-synthesized ProposedBeliefs, or to resolve Contradiction markers. Internal-only `context_accept_belief` / `context_reject_belief` exist but are not in any profile.

To make engagement actionable from the agent surface, we extend the verb set minimally:

- **`commit`** extended to accept a `marker_id`. Semantics: "I accept this synthesized belief / I resolve this contradiction in favor of node X." For ProposedBeliefs, this is the agent-facing equivalent of `context_accept_belief`.
- **`dismiss(marker_id, reason)`** added as a new verb. Semantics: "I saw this and decided not to act on it." Records the dismissal with a reason for downstream threshold tuning.
- **`revise`** unchanged. Covers the "modify and then commit a different version" path.

Three changes total: one verb extension, one new verb, one verb left alone.

### Skill changes

- **New: `engrammic-engage`.** Fires when the agent sees an engagement payload. Teaches the commit / revise / dismiss decision. Short, opinionated, decision-tree style.
- **Update: `engrammic-recall`.** Adds "check the `engagement` field" as an explicit step in the recall workflow.
- **Update: `engrammic-onboarding`.** Mentions engagement as part of how recall works so agents starting fresh know to expect it.

### AGENTS.md / CLAUDE.md guidance

We ship a short block via the installer and skill bundle. Distributed text, harness-agnostic.

```
When you call recall and the response includes an `engagement` field,
treat it as the system flagging unresolved synthesis on a topic you
just queried. Read it, then call commit / revise / dismiss before
continuing. Hard engagement blocks further progress until acted on.
```

Three sentences. This is the public-facing contract.

### What layer 1 alone gets us

If recall frequency is high (which it should be for any agent benefiting from Engrammic), this captures most of the engagement payload value. Synthesis happens server-side via SAGE. The agent gets nudged on every recall, blocked on threshold trips, and has clean verbs to act.

The honest ceiling: agents in execute-mode that go many turns without calling recall never see any engagement payload. Layer 2 exists to close that gap.

## Open layer-1 decisions

These three need resolution before this becomes a plan.

### 1. Hard checkpoint payload shape

When `mode: "hard"`, what does the response look like?

#### What "non-skippable" actually means

We cannot force the agent to do anything. The agent's loop reads the tool result and decides what to do next. All we can do is shape the response so that engagement is the only sensible next action. The choice between options is a choice about how few alternatives we leave on the table.

#### Options

- **Option A: Replace results.** `results: []` or `results: null`, `engagement` is the only meaningful content. Closest to the literature pattern. Strongest enforcement.
- **Option B: Keep both, mark results unavailable.** `results: []` with explicit marker, `engagement` populated. Functionally equivalent to A with extra ceremony.
- **Option C: Keep results, add a strong flag.** `results` populated normally, `engagement.mode: "hard"` is the only signal. The skill teaches the agent to respect it.

#### Pressure on C

C is the gentlest but matches the failure mode the 05-24 doc identifies as fatal: agents skim past optional flags. Skill discipline alone does not work; that is the whole reason engagement is structural rather than tool-description-only.

Additionally, we ship cross-harness. Different harnesses render tool results differently — some truncate, some summarize, some place metadata in UI regions the agent may not see prominently. If enforcement depends on a flag being noticed, we are at the mercy of harness rendering. If the response itself leaves nothing else to act on (A), engagement reaches the agent regardless of how the harness renders it.

A is harness-agnostic enforcement. C is "we hope every harness surfaces our flag prominently."

#### Mitigations for the mis-firing failure mode

If A is the answer, mis-firing is the cost we have to design around. Two refinements:

1. **Conservative initial threshold.** Hard fires rarely. Soft engagement carries most of the load. Tune up from engagement-rate data, not down from complaints.
2. **Soft-before-hard escalation.** A marker surfaces as soft on first N recalls touching its about-set. Escalates to hard only after the agent has had multiple chances to engage voluntarily and ignored them. Matches Generative Agents' importance-accumulation rather than a single threshold trip.

#### Scope of the block

Two interpretations of "blocking":

- **Recall-scoped:** Only future recall calls return engagement-required until resolved. `remember`, `learn`, `link`, etc. work normally. Engagement surfaces on recall, engagement blocks recall.
- **Tool-wide:** Every tool call returns engagement-required until resolved.

Tool-wide is closer to a true "stop and engage" experience but breaks the agent in much more disruptive ways (cannot even record observations while figuring out the engagement). Recall-scoped is more surgical.

Lean: recall-scoped. Tool-wide is the kind of design choice that looks principled and feels terrible in practice.

#### Backwards compatibility

No production users yet. Breaking changes to the recall response shape are fine. Worth noting only because it affects rollout sequencing, not because it constrains the design.

#### Resolution

- **Option A.** Replace results when hard. Harness-agnostic enforcement is the deciding factor.
- **Soft-before-hard escalation.** Marker surfaces as soft first, escalates to hard only after repeated soft surfacing was ignored.
- **Recall-scoped block.** Hard engagement blocks future recalls until resolved, not all tools.
- **Conservative initial threshold.** Tune up from data.

### 2. Agent identity and the touch-counter

Hard checkpoint requires knowing "this caller has touched related nodes N+ times recently." Engrammic has no agent identity concept today.

**Why "session" is the wrong primitive.** The intended deployment pattern is multi-agent same-silo: multiple Claude Code / Cursor / Codex instances against the same silo, sub-agents dispatched by a parent, long-running orchestrators plus ephemeral workers, interactive plus CI agents sharing memory. Heat (silo-scoped) collapses these into a single signal and loses the per-caller precision the threshold needs. Session (process-lifetime-scoped) is also wrong, because a long-running Claude Code instance spans many distinct user tasks and the counter would over-accumulate.

What we actually need is **agent identity** plus a **time-decayed touch counter**. Identity stable across calls within a logical agent run, distinguishable across concurrent callers, with old activity decaying naturally so cross-task pollution does not fire the checkpoint inappropriately.

#### Where identity can come from

We do not have to invent it. Existing handles:

1. **MCP connection identity.** Every MCP transport gives the server a connection identifier. Stdio: one process, one connection. HTTP-streamable: explicit session ID header in the MCP spec. SSE: connection lifetime. The server keys state off this with no agent round-trip.
2. **MCP `clientInfo`.** Initialization payload includes client name + version. Useful for distinguishing harness kind, does not distinguish instances of the same kind.
3. **Auth subject.** If WorkOS auth is wired in, distinguishes humans/services but not concurrent instances of one human.
4. **None of these for unauthed beta deployments.** Worth naming the gap.

The cleanest is (1). Auth subject (3) layers on top if and when auth is universal across our deployments.

#### Revised options

- **Option A (revised): Server-managed state keyed off MCP connection identity.** No token round-tripping. Server uses the transport-provided connection identifier as the agent handle. Redis keys `(silo_id, connection_id, about_node_id) -> touch_count` with time decay (exponential or sliding window). Multi-agent precision falls out naturally because each connection is distinct.
- **Option B: Client-managed UUID.** Agent generates and passes a session identifier. De-prioritized: assumes harness behavior we do not control, and we already get equivalent identity from the transport.
- **Option C: Stateless recompute.** Recompute "touched recently" from graph traversal at recall time. No state stored. Pushes work into the recall hot path. Demoted to future / if Redis becomes a bottleneck.
- **Option D (rejected): Heat as the threshold.** Silo-scoped heat conflates concurrent agents in the same silo. Wrong for the intended multi-agent deployment pattern. Rejected.

Current lean: A revised. Connection-keyed, time-decayed, no round-trip.

#### Failure modes to price before committing

- **Connection drops mid-task.** New connection means fresh identity and a reset counter. Stdio: rare (process restart). HTTP-streamable: depends on how clients handle session IDs across requests. Worth verifying our FastMCP transports give stable connection identity in practice, not just in spec.
- **Sub-agents.** A parent Claude Code dispatching Task workers: do they share the parent's MCP connection or open their own? If shared, the threshold fires correctly (one logical agent). If split, touches are diluted across N workers and threshold under-fires. This needs to be tested against actual harness behavior, not assumed.
- **Connection ID stability across reconnects.** Most transports rotate connection IDs on reconnect. The counter resets, threshold under-fires for the rest of that logical task. Acceptable for now; auth subject layered on later resolves it.

#### Spike to do before locking this in

Verify what FastMCP gives us as a stable connection identifier across stdio, SSE, and HTTP-streamable transports. Roughly 30 minutes. Outcome determines whether revised-A is implementable as written or needs auth-subject from day one.

### 3. `commit` extension vs separate accept/reject agent verbs

Two shapes for the same behavior:

- **Option A: Extend `commit`.** `commit(hypothesis_ids?, marker_ids?)` accepts either. Semantically: "I commit to this," whether it's my own hypothesis or a system-proposed belief. Surface stays small.
- **Option B: Add agent-facing `accept(marker_id)` / `reject(marker_id)`.** Mirrors the internal verbs. Clearer separation between "I authored this belief" (commit) and "I ratified a system-proposed belief" (accept).

Tradeoffs: A keeps the agent surface smaller (good for adoption, fewer verbs to learn). B is semantically cleaner and matches the SAGE-vs-agent belief flow split documented in CLAUDE.md.

Current lean: A. Smaller surface wins. The semantic distinction matters internally but not at the agent verb level. We can keep `accept` / `reject` as internal-only.

## Layer 2: Hook surface

Speccing the shape, not the implementation. Layer 1 must not preclude this.

### `tick` verb

New lightweight MCP verb. Takes an optional `about_hint` (free text or node IDs). Returns either nothing or an engagement payload identical in shape to the one in recall responses.

Implementation: reads the precomputed marker index only. No graph traversal, no embedding, no semantic work. Must be safe to call frequently with zero side effects when nothing is pending.

This is the single integration point hooks call.

### Trigger conditions

Hooks invoke `tick` on:

- **N assistant turns since last memory call.** Catches execute-mode drift.
- **N tool calls since last recall.** Same intent, finer-grained.
- **Session start.** Surface any high-priority engagement before the agent picks up where it left off.
- **Post-`learn` / post-`remember`.** A new claim might contradict existing beliefs.

Each harness picks the subset it supports. Defaults are conservative.

### Cross-harness shape

We ship reference configs:

- Claude Code: hooks on `PostToolUse` and `SessionStart`.
- Codex: equivalent hook points.
- Cursor: rules / custom commands.
- Other: documented patterns.

We do not ship the harness. The hook config is distributed via the installer alongside skills.

### What layer 1 must provide for layer 2 to work

- `tick` verb (so we need to spec it as part of layer 1 even if hooks are not yet built).
- Precomputed marker index (already required for hard checkpoint, dual-use).
- Engagement payload shape stable enough to reuse.

If we get layer 1 right, layer 2 is mostly distribution and harness-specific config files.

## Layer 3: Custom harness

Out of scope as a product. Worth a short spec for two reasons:

1. **Decision rule.** When (if ever) would we build one? Only if (a) hooks prove empirically insufficient across multiple harnesses, and (b) we have product-market fit and can afford the harness-agnostic story breaking. Until both are true, do not build.
2. **Competitive intel.** Other agent-memory companies may go this route. Knowing what a full harness would look like helps us evaluate their tradeoffs.

Not specced further here.

## What we measure

The engagement-rate kill criterion from the 05-24 doc still holds:

> when an engagement item is surfaced, does the agent ever follow up with `commit` / `revise` / `dismiss`?

Open question: what is the baseline? If current voluntary upper-layer call rate is near zero, even a 5% engagement rate is meaningful. If it is higher than we think, the bar should be higher.

Measurement preconditions:

- We need telemetry on tool-call sequences (recall -> commit/revise/dismiss within N turns).
- We need to capture this both with and without the engagement payload, to isolate the lift.
- Dark launch on layer 1 (soft field only, no skills updated yet) gives us the baseline.

## Cross-references

- [2026-05-24-pulling-agents-into-higher-layers.md](2026-05-24-pulling-agents-into-higher-layers.md) — foundational thinking, SAGE design, latency budget
- `context/architecture.md` — service architecture
- `context/architecture/sage-system.md` — SAGE sub-agents
- `src/context_service/config/mcp_tools.yaml` — current tool surface, source of truth
- `CLAUDE.md` — belief architecture (agent vs SAGE flow)

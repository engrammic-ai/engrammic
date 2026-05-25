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

#### Constraint discovered during spike: `stateless_http=True`

`src/context_service/api/app.py:289` configures the FastMCP server with `stateless_http=True`. In stateless HTTP mode, FastMCP does not maintain per-connection state across requests. Every HTTP request is independent. `fastmcp_context` is not stable across calls, even within a logical "session."

This is a deliberate config choice — stateless mode enables horizontal scaling without sticky sessions or shared session state. Flipping to stateful is not free: it imposes sticky LB sessions or Redis-backed session state, which we do not want to take on for engagement alone.

Implication: **server-side connection identity does not exist as currently deployed**. Any session-state design must rely on something the client sends, not something the server tracks per-connection.

#### Existing infrastructure

`src/context_service/mcp/server.py:271` already extracts `x-session-id`, `x-agent-id`, `x-org-id`, and `authorization` headers from incoming HTTP requests. The mechanism for client-sent identity is already wired. We are not adding plumbing; we are deciding what to do with it.

The MCP spec also defines `mcp-session-id` as the standard header for HTTP-streamable session identity, separate from our custom `x-session-id`.

#### Revised options

- **Option A (revised again): Consume `x-session-id` / `mcp-session-id` header.** Server keys engagement state off the header the client sends. Redis keys `(silo_id, session_id, about_node_id) -> touch_count` with time decay. Stateless HTTP preserved. Burden on client/harness to send a stable identifier per their own session concept. No round-trip at the agent level — the harness handles the header in its MCP config.
- **Option B: Make the server stateful.** Flip `stateless_http=False`, add sticky sessions or Redis-backed FastMCP session state. Breaks the current scaling model for one feature. Rejected unless engagement proves to need it.
- **Option C: Stateless recompute.** Recompute "touched recently" from graph traversal at recall time. No state stored. Pushes work into the recall hot path. Demoted to future / if Redis becomes a bottleneck.
- **Option D (rejected earlier): Heat as the threshold.** Silo-scoped heat conflates concurrent agents in the same silo. Wrong for the intended multi-agent deployment pattern.
- **Option E: Auth subject.** Use the authenticated principal as identity. Only works when auth is universal across deployments. Not the case in beta yet. Layers on top of A naturally: `(silo, auth_subject, session_id)` becomes the richer tuple when auth is everywhere.

Current lean: A revised again. Header-keyed, time-decayed, stateless HTTP preserved.

#### The lower bar that makes this work

The engagement threshold (time-decayed touches) only needs stability *within a single MCP client process / conversation*, not across reconnects. If a client reconnects mid-task and rotates `x-session-id`, touch counts reset and hard checkpoint under-fires until counts rebuild. Graceful degradation, not a broken design.

This matters because most harnesses likely manage session ID per process/conversation, not across restarts. We do not need cross-reconnect stability to ship.

#### Failure modes to price

- **Harnesses do not send a session header by default.** Then engagement state can only be keyed by silo, which collapses concurrent agents. Mitigation: ship "add `x-session-id: <uuid>` to your MCP client config" instructions in the installer / skill bundle. Acceptable papercut.
- **Sub-agents.** A parent Claude Code dispatching Task workers: do they share the parent's session header or open new ones? If shared, threshold fires correctly. If split, touches are diluted across N workers and threshold under-fires. Needs empirical testing.
- **Header forgery.** A malicious client could send a session header matching another tenant. Mitigated by silo scoping already in place (sessions are namespaced under `silo_id`). Within a silo, header forgery is not a meaningful threat model because anyone with silo access can already read/write everything.

#### Empirical findings from spike

A standalone FastMCP probe server (`scripts/probe_identity_server.py`) was hit from Claude Code 2.1.150. Results:

**Stateless mode (matches production):**
- No `mcp-session-id`, `x-session-id`, `x-agent-id`, or `authorization` headers sent by Claude Code
- `client_id` always null (comes from MCP request `meta`, not auth)
- `session_id` (FastMCP attribute) rotates per request — fresh UUID every call
- `fmc_id` (Python object id of fastmcp_context) rotates per request
- **Conclusion:** stateless mode provides zero stable agent identity server-side, and Claude Code sends nothing identity-bearing at the HTTP level

**Stateful mode (`stateless_http=False`):**
- Server mints `mcp-session-id` on initialize, Claude Code echoes it back on every subsequent request
- `session_id` (FastMCP) stable across all calls in the connection
- Zero client config needed — Claude Code participates in MCP session protocol correctly
- **Blocked:** Cloud Run cold-start race (`Received request before initialization was complete`). Documented in `git show 58cfa20`. Known upstream issue (modelcontextprotocol/python-sdk#737, #1053). Already mitigated in our codebase by combined-lifespan composition in `api/app.py:303` — yet the error still occurred on Cloud Run. Fixing is a multi-hour platform investigation (FastMCP version bump, low-level `StreamableHTTPSessionManager` refactor, or Cloud Run `min-instances=1`), not pre-engagement work.

#### Locked: Path 1 (stateless + installer-distributed header)

Stateless HTTP preserved. Engrammic's installer writes MCP client configs that include `x-session-id: <stable-uuid>` per install / per session. Server consumes the header (already wired at `server.py:271`), keys engagement state off it.

- Zero user-facing config burden (installer handles it).
- Hand-configured clients get documented instructions.
- The cold-start fix can land later as a platform improvement that lets us drop the header requirement.
- Spec evolution (2026 MCP roadmap standardizes stateless session handling) eventually makes this the future-correct path anyway.

#### Probe cleanup

- Standalone probe at `scripts/probe_identity_server.py` — keep for future spikes
- Probe was added to `src/context_service/mcp/middleware.py` and reverted in this session
- `.mcp.json` has `engrammic-probe` entry — remove before merging engagement layer 1

### 3. Verb shape for responding to engagement

The engagement payload's `decision_required` field carries one of `commit | revise | dismiss` today, but that masks a more nuanced verb question: across the marker zoo, which verbs cleanly express the agent's response?

#### The marker zoo and natural responses

| Marker type | Natural responses |
|---|---|
| ProposedBelief (from `sage.synthesizer`) | ratify, modify, reject |
| Contradiction (from `sage.validator`) | resolve by asserting winning version, or acknowledge unresolved |
| WorkingHypothesis (touched repeatedly) | crystallize, update, drop |
| StaleCommitment (new evidence arrived) | form a new commitment, acknowledge as stale |

`commit` only naturally fits ProposedBelief and WorkingHypothesis. Contradictions and stale commitments are better served by `revise` (assert a new version) or `dismiss` (acknowledge without resolving).

#### Options

- **Option A: Extend `commit`.** `commit(hypothesis_ids?, marker_ids?)` accepts either. Mental model: "I commit to this," whether self-authored or system-proposed.
- **Option B: Promote internal verbs to agent surface.** `context_accept_belief` and `context_reject_belief` already exist as internal-only tools. Promote them as agent-facing `accept(marker_id)` and `reject(marker_id, reason)`, mirroring the SAGE-vs-agent belief flow split.

#### The discriminator

The cost calculus for B is different than it first appears. The verbs already exist in the codebase (`src/context_service/mcp/tools/context_accept_belief.py`, `context_reject_belief.py`). Promotion is mostly a yaml change to add them to a profile — not new code, new tests, or new semantics.

That weakens the "smaller surface" argument for A. We're not comparing "add 2 verbs" vs "extend 1 verb." We're comparing "expose 2 existing verbs" vs "extend 1 verb and lose semantic fidelity."

#### Why semantic fidelity matters here

Engrammic's product positioning is epistemic rigor. Provenance and trace are differentiators, not internal details. Three concrete places where the distinction matters:

- **Trace.** `trace(node_id)` should say "this belief was system-synthesized and ratified by the agent" vs "this belief was authored by the agent." Same verb (unified `commit`) produces ambiguous provenance unless we encode it back into a parameter, at which point separate verbs are cleaner.
- **Audit.** When a belief turns out wrong, knowing whether the agent generated it or merely accepted it changes failure-mode analysis.
- **Trust calibration.** A user reviewing memory should distinguish "the agent reasoned to this" from "the system proposed and the agent didn't push back." Different epistemic acts.

The asymmetry is honest: ratifying a system proposal is a different epistemic act than crystallizing one's own reasoning. The surface should reflect that.

#### Resolution

**Option B.** Promote `context_accept_belief` and `context_reject_belief` to agent-facing `accept` and `reject`.

Final verb set for engagement response:

- `commit(hypothesis_ids)` — unchanged, agent's own hypotheses only
- `accept(marker_id)` — agent ratifies a ProposedBelief (promoted from internal)
- `reject(marker_id, reason)` — agent rejects a ProposedBelief, marker archived, SAGE marks belief do-not-re-propose (promoted from internal)
- `revise(hypothesis_id | marker_id, ...)` — extended to handle contradiction and stale-commitment resolution via supersession; auto-archives the marker
- `dismiss(marker_id, reason)` — new verb for non-ProposedBelief markers; "saw and chose not to act"

Five verbs touch engagement, but each does one thing. The "not now" vs "rejected" distinction is preserved naturally: `reject` for ProposedBelief, `dismiss` for everything else.

## Layer 2: Hook surface

**Status: checkpointed. Revisit after layer 1 ships.**

Layer 2 design is deferred until layer 1 is implemented and we have engagement-rate data from real deployments. The shape below is sketched only to ensure layer 1 does not preclude it — concrete design happens after we know what layer 1 actually achieves on its own.

What we need from layer 1 to keep layer 2 viable:

- `tick`-shaped verb exists (or can be added without redesign). Reads only the precomputed marker index.
- Engagement payload shape is stable enough to reuse outside recall.
- Marker index supports fast lookup by about-set.

Sketch (do not lock in):

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

**Status: checkpointed indefinitely.** Out of scope as a product.

Decision rule for revisiting: only build if (a) hooks (layer 2) prove empirically insufficient across multiple harnesses, and (b) we have product-market fit and can afford the harness-agnostic positioning breaking. Until both are true, do not build.

Speccing further is deferred. If competitive pressure makes a research artifact useful, write that separately rather than developing this section.

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

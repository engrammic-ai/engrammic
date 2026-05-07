# Moat and Positioning Review - 2026-05-02

Working doc from strategic review session.

## Assumptions Pressure-Tested

### 1. Multi-agent is the wedge
- **Bet:** Teams hit the "second agent" wall; org-level memory is the gap
- **Risk:** Most enterprises still struggling with one agent. Multi-agent adoption may be 18-24 months out
- **Status:** REFINED - see "Validated Wedge" section below. Not multi-agent; it's cross-session memory loss and teams sharing one agent across massive context

### 2. MCP wins
- **Bet:** Protocol war is over; MCP is the standard
- **Risk:** OpenAI could still ship competing protocol. Google A2A is adjacent
- **Counter:** 97M SDK downloads is real traction
- **Status:** Fragile but defensible

### 3. Curation beats retrieval
- **Bet:** Custodian + draft/publish + cited findings is a product-shape moat
- **Risk:** Requires buyer education. "Curated findings" isn't a searched category
- **Status:** Novel but needs market validation

### 4. Context is the bottleneck
- **Bet:** Models are smart enough; structured access is the constraint
- **Risk:** This is true but not differentiating. Context engineering is becoming commodity
- **Status:** Weakest assumption - need differentiation beyond "we do context better"

### 5. Open-core wins trust
- **Bet:** Self-host path matters for developer adoption
- **Risk:** Open-core is GTM, not moat. Code is inspectable = copyable
- **Status:** Tactical advantage, not strategic moat

---

## The Positioning Problem

"Epistemology layer" is accurate but:
- Too academic
- Customer-repellent
- Investor-confusing

### Bridge Language (what we're using instead)

| Context | Phrase |
|---------|--------|
| Technical buyer | "Evidence-based memory for agent teams" |
| Business buyer | "Memory with receipts" |
| Anti-competitor | "Mem0 stores. Zep retrieves. We govern." |

**Core message:** You set the rules. We enforce them with citations and audit trails.

---

## Where We Sit in the Stack

Three engineering layers around LLMs (2026 framework):
1. **Prompt Engineering** - what instructions the model gets
2. **Context Engineering** - what the model sees, when
3. **Harness Engineering** - full runtime: tools, safety, execution, observability, memory

We sit in both **context engineering** and **memory engineering** (within harness).

Differentiation: We're not optimizing retrieval (commodity). We're adjudicating claims.

---

## Moat Analysis (Honest Assessment)

| Layer | Lead time | Durability |
|-------|-----------|------------|
| Four-layer architecture (Memory/Knowledge/Wisdom/Intelligence) | 6-12 mo | Copyable with effort |
| Org-level silos first-class | 6-12 mo | Expensive retrofit for competitors |
| Provenance invariants (I1-I6) | Built now | Foundation for UX moat |
| **Debugging UX** ("why does agent believe X") | Roadmap | Sticky moat |
| **Config UX** (rules you control) | Roadmap | Trust moat |

**Bottom line:** Architecture buys time (12mo). UX buys lock-in.

Within 12 months, Mem0/Zep could rebuild architecture. Must win on:
1. UX (debugging + config)
2. Category ownership (define the language)

---

## The Moat Without Benchmarks

Benchmarks measure retrieval (recall@k, LongMemEval). Wrong game.

Our primitives:

| Primitive | What it does | Why hard to copy |
|-----------|--------------|------------------|
| Contradiction detection | Same subject + predicate, different object = conflict | Requires predicate registry + entity resolution |
| Confidence math | `source_tier x corroboration x method_weight x raw` | Deterministic, auditable, replayable |
| Corroboration | N distinct sources saying the same thing | Requires claim-level extraction, not chunk storage |
| Provenance invariants | Every Fact traces to Memory; every Belief to Facts | Enforced at write time |

**Competitors store memories. We adjudicate claims.**

### Benchmark We Could Own

Not retrieval accuracy. **Epistemic integrity over time:**
- Does the system know when two agents disagree?
- Does it know which claim supersedes which?
- Can you query "what did we believe on March 1st"?
- When a source is discredited, do downstream beliefs update?

---

## UX Moat (To Build)

### Debugging UX - "why does my agent believe X?"

Requires:
- Provenance traces that work (I1-I6 invariants - have this)
- UI/CLI that walks the chain: Belief -> Facts -> Memories -> Sources
- Contradiction surfacing

**Concrete:** `contextr trace <belief-id>` or dashboard view

### Config UX - "what rules govern my memory?"

- Source tier definitions (which agents/docs are authoritative)
- Promotion thresholds (how many corroborating sources)
- Silo boundaries (what's shared vs scoped)
- Retention policies per layer

**Concrete:** Config file or dashboard. Version-controlled. Auditable.

---

---

## Validated Wedge (from Silt call 2026-05-02)

**Not "multi-agent teams" (future). Instead: "Teams sharing one agent across massive org context that contradicts itself."**

Silt validated this directly:

> "Cross-session memory loss is the core unsolved problem. Agents only have context of the session they are in."

### Pain Points Validated

| Pain (Silt's words) | Our solve |
|---------------------|-----------|
| Cross-session memory loss | Org-level silos, persistent layers |
| Context accuracy vs cost ("constant uphill battle") | Custodian curation nodes short-circuit traversal |
| Shared context across agents is expensive | Built for this from architecture up |
| Source authority matters | Signals layer (heat, trust tiers) |

### What Resonated (in their words)

- Epistemic layering (Memory/Knowledge/Wisdom/Intelligence) - "it lacks epistemics - that is the only differentiating part" (vs MemCP)
- Custodian curation nodes - agents don't walk full graph; summary nodes short-circuit
- Superseding edges for audit trails - compliance gap in current solutions
- Heat maps for pre-scoring at ingest time
- DAG chains for reusable reasoning - "agents don't need to reason out the same shit over and over"

### Moat Confirmation

> "Data layer is where both parties see the strategic moat. UI has lower switching costs."

Epistemics IS the moat. Not retrieval, not connectors.

---

## Stack Placement (Validated)

We are **pure infra**. Customer handles ingestion; we handle truth.

```
[Slack, Linear, Notion, CRM]
        |
[Customer's ingestion] <- they own sync, rate limits, pain
        |
   [Engrammic] <- evidence-based memory infra
        | (MCP / REST)
[Customer's agent / UI]
```

### Interface Requirements

| Buyer type | Primary interface |
|------------|-------------------|
| B2B (selling to business) | REST API |
| Developer / end-user tooling | MCP |

Quote: "REST API is needed. MCP is secondary if you are selling to a business."

Both surfaces must be strong.

---

## Gap Identified: Wiki Viewer

> "Unless they actually see what's going on, they are never really satisfied if it got the right result."

Silt has wiki-style browsable notes. Raw graph views are "a hairball." Human-in-the-loop trust requires legibility.

**We don't have this.** Add to roadmap.

---

## Concrete Applications

Primary verticals (validated):

### 1. Decision Memory (Silt-shaped)
- PM teams tracking decisions across Linear/Slack/Notion
- "What did we decide about feature X?"
- "When did that change?"
- Supersession + provenance

### 2. Customer Success Memory
- CS agents that remember account history across reps
- "What did we promise this customer?"
- Handoffs don't lose context

**Shared value prop:**

> "Memory for teams that can't afford to forget. Decisions, promises, context - tracked over time, cited to source, updated when things change."

Or:

> "You handle ingestion. We handle truth."

---

---

## Moat Thickness (Final Assessment)

| Layer | Thickness | Why |
|-------|-----------|-----|
| **Epistemic layering** | **Thick** | "The only differentiating part." Architectural commitment, not a feature. |
| **Custodian curation** | **Thick** | Changes the retrieval unit. Competitors store chunks; we serve curated nodes. |
| **Supersession + provenance** | **Medium-thick** | Requires bi-temporal data model. 6-12mo to copy properly. |
| **Org-level silos** | **Medium** | Expensive retrofit but not impossible. |
| **Signals (heat/trust tiers)** | **Medium** | Novel but copyable once understood. |
| **MCP-native** | **Thin** | Everyone has MCP now. Table stakes. |
| **Open-core** | **Thin** | GTM strategy, not moat. |

**Net:** Core moat is epistemic layering + curation. 12-18mo architectural lead. UX converts lead into lock-in.

---

## Final Positioning Statements

### For Investors

> "Agent memory is a $2B+ category forming now. Every player stores raw memories. We're the only one that adjudicates what's true - with evidence requirements, conflict detection, and audit trails. The architecture is a 12-month lead; the UX we're building on top is the lock-in."

### For Customers (Technical)

> "You handle ingestion. We handle truth. Evidence-based memory infrastructure with citations, supersession, and audit trails - as a layer under your agents."

### For Customers (Business)

> "Memory with receipts. Your agents know what was decided, when it changed, and why - with full audit trail."

### Anti-Positioning

> "We're not a connector platform. We're not an agent UI. We're the truth layer that sits between your data and your agents."

---

## Competitive Responses

### "Why not Mem0?"

> "Mem0 stores memories. We adjudicate claims. When two sources contradict, Mem0 picks one silently. We surface the conflict and let you set rules for what to trust. Different architecture, different problem."

### "Why not Zep/Graphiti?"

> "Zep is single-agent enrichment with temporal graphs. We're org-level shared memory with epistemic layering. They optimize retrieval; we optimize truth. Complementary if you need both."

### "What about Google's memory agent?"

> "Google's AOMA is a template. No org concept, no governance, no audit. We're what you deploy when you need production-grade memory with compliance built in."

### "Isn't this just RAG?"

> "RAG retrieves documents. We adjudicate claims. RAG has one persistence model for everything. We have four layers with different semantics - experiences decay, facts persist until superseded, beliefs update on evidence. Different category."

---

## Next Steps

1. ~~Validate wedge with design partners~~ DONE (Silt call)
2. Ship debugging UX (trace command / dashboard)
3. Ship config UX (rules file / dashboard)
4. Ship wiki viewer for legibility/trust
5. Define "epistemic integrity" benchmark (rot-bench or similar)
6. Strengthen REST API surface for B2B sales

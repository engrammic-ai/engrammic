# Design Partner Notes: Silt

## Background (pre-call notes)

> "Canvas that bridges human thinking and AI execution... designing the cognitive boundary between human decision-making and agentic processing."

- One place for product teams
- Share one AI agent with full context (no isolated conversations)
- Full decision history with context preserved
- Export decisions to Cursor with context transfer
- Template processes and reuse across projects

Team: Young builders from Helsinki, Turku, and Lahti, Finland

| Silt's stated need | Our solution |
|---|---|
| "Full decision history" | Bi-temporal queries, supersession |
| "Context preserved" | Provenance invariants |
| "No isolated conversations" | Org-level silos, shared memory |
| "Cognitive boundary" | Four-layer split (Memory / Knowledge / Wisdom / Intelligence) |

---

## Call notes: 2026-05-02

Speaker_0 = Aliasgar (us). Speaker_1 = Nitesh, Silt founding engineer.
Linnards is CTO, Artemi is CEO. They are preparing for a seed round (Slush).

### What they are building

They have converged on essentially the same architecture: a graph-based, layered context system
with clustering, embeddings, and a wiki-style viewer. Their framing is two layers:

- **Org layer** — Slack, Linear synced externally. Retrieve and understand, not maintain.
- **Canvas layer** — personal/session-evolving. Built on Karpathy's wiki approach. Evolves based
  on what the user says in-session.

They do Leiden clustering + semantic reasoning on both layers. They have a wiki viewer so users can
browse what context has been stored.

Key quote: "I think we're building the same things, more or less."

### Pain points they validated

**Cross-session memory loss is the core unsolved problem.**
Agents only have context of the session they are in. Chat one, chat two, chat three are isolated.
Stitching context across sessions is the primary problem they are solving.

**Context accuracy vs. cost is a constant tension.**
More accurate context requires more edges and nodes, which is both expensive and slow. Graph
traversal alone can take 0.5 to 20 seconds on a non-trivial org. "It's a constant uphill battle."

**Initial data sync (especially Slack) is the hardest onboarding problem.**
Slack API rate limits mean a full initial sync for a 500-person, 7-year-old org can take days.
Customers tolerate it because they trust the value is coming. Linear is less of an issue.

**Shared context maintenance across agents is "quite high" overhead.**
Keeping multi-agent teams coherent is expensive and brittle. Active pain point for them, not just
for customers.

**Source authority matters for signal quality.**
Not all Slack messages are equally meaningful. Who said something — their organizational
credibility — should influence the heat/weight of a node. Raised unprompted, maps directly to
our signals layer.

### What resonated about our approach

- Epistemic layering (Memory / Knowledge / Wisdom / Intelligence) differentiated us from flat
  memory stores like MemCP. Their read: "it lacks epistemics — that is the only differentiating
  part."
- Custodian curation nodes: agents do not need to walk the full graph; summary nodes short-circuit
  traversal. They found this compelling.
- Superseding edges for audit trails: compliance and auditability is a real enterprise concern;
  in-place mutation without history is a gap in current solutions.
- Heat maps trained on aggregate anonymized data to pre-score nodes at ingest time. Positive
  reaction; this could reduce cost before full ingestion completes.
- DAG chains for reusable reasoning (Intelligence layer): "agents don't need to reason out the
  same shit over and over again." They are building something similar.

### Interface preferences

For B2B (selling to a business): REST API is primary. MCP is secondary.

For end-user / developer tooling: MCP first.

Quote: "REST API is needed. MCP is secondary if you are selling to a business."

Implication: our REST surface is the right integration point for a Silt partnership; MCP is what
their agents would consume.

### Wiki viewer as trust anchor

Silt confirmed their wiki viewer is essential — raw graph views (Obsidian-style) are useless to
humans ("a hairball"), but wiki-style browsable notes make investors and users trust the system.
Human-in-the-loop trust requires legibility. This is a gap on our side: no equivalent viewer today.

Quote: "Unless they actually see what's going on, they are never really satisfied if it got the
right result."

### Competitive / partnership dynamics

- Silt may become a direct competitor if both of us build data layers. They acknowledged this
  explicitly: "if we don't take each other's help and build the same thing, we will end up
  competing over time."
- Alternative framing they proposed: we become their data layer; they build UI on top. We would
  not own the org sync pipeline; we provide the agentic memory graph as a layer sitting on top of
  their data, with pointers not copies.
- The cleaner near-term path: provide MCP layer access so they can test without code-sharing
  commitments. No promises on either side.
- Artemi (CEO) is protective of owning the data layer. Nitesh will need to convince him. That
  conviction only comes through testing.

### Agreed next steps

- Send materials (architecture, API examples, fit analysis) to Nitesh by Monday/Tuesday.
- Optionally share the repository.
- Nitesh will run it by Linnards and Artemi and assess fit.
- Potential shared test repo for evaluation.

### Nitesh sentiment breakdown

**Overall read: cautiously interested, not sold.** He agreed to test but the agreement was
conditional ("without testing I cannot give you any code or anything") and driven by peer curiosity
more than conviction.

**The problem space** — genuinely enthusiastic. Volunteered pain points unprompted. Lived
experience, no performance.

**Your architecture** — respectful surprise, competitive recognition. "I think we're building the
same things" repeated twice with chuckles. Sees convergence, not differentiation.

**The epistemic layering** — politely engaged, not deeply probing. Acknowledged it separates us
from MemCP but never asked follow-up questions about how it works. Social agreement more than
technical curiosity.

**The data ownership question** — most animated, most defensive. Immediately pushed back when the
idea of sitting on top of their data layer came up. He's protecting Silt's data moat and was
testing whether we'd be a dependency or a threat.

**The partnership framing** — warm but non-committal. "I'm rooting for you" + "we'll be willing
to test it out." Note the structure: Aliasgar sends materials, Nitesh runs them by Artemi and
Linnards. He's creating a review gate, not championing internally. The decision is above him.

**Cost concerns** — genuine skepticism, raised unprompted three times. This is the core objection,
not capability or fit.

**The competitive risk** — lucid and matter-of-fact. Already thought through the scenario and
isn't scared of it, which means he's not desperate for the partnership either.

| Signal | What it means |
|---|---|
| Agreed to test | Low bar — doesn't cost him anything |
| Never asked a deep technical question | Not yet convinced there's something novel enough to dig into |
| Raised cost 3x unprompted | The actual blocker |
| "Without testing I cannot give you anything" | Needs proof before he advocates internally |
| Rooting for you, not integrating with you | Warm personally, arm's length professionally |
| Decision goes to Artemi/Linnards | He's a screener, not the decision-maker |

**Bottom line:** the materials we send need to make the economic case, not the technical one. He
already gets the architecture.

### Other signals

- Neo Cognition (HippoRAG productionization) raised $40M. Market tailwind confirmed.
- Only 33% of companies are currently attempting AI adoption; agentic memory reliability is cited
  as a primary blocker industry-wide.
- Data layer is where both parties see the strategic moat. UI has lower switching costs.
- Self-hostable deployment was flagged as important, especially if compliance (GDPR, SOC 2) is
  handled at the data layer.
- Silt tracks "decisions" internally (active / deferred, with rationale). Closest analogue in our
  system is `context_commit` + custodian consensus + meta-memory.
- Additional design partner in parallel: Jason's company (Mozilla-adjacent), multi-agent memory
  problems, proposal going out Monday.

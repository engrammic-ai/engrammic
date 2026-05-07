# Open-Source Strategy and Manifesto

Status: Draft
Date: 2026-05-02

## Goals

- Thought leadership: establish EAG as the paradigm for agent memory
- Developer adoption: get engineers building on primitives + engine

## Package Structure

Two repos in `delta-prime/`:

**primitives/** (existing)
- License: MIT
- Contains: epistemology math, scoring, schema, protocols
- Fully open, no restrictions

**engine/** (new repo)
- License: Apache 2.0 (enterprise-friendly, explicit patent grant)
- Depends on: primitives
- Contains:
  - `engine/store/` - SQLite-backed single-tenant store
  - `engine/mcp/` - Basic MCP server (read/write tools)
  - `engine/__main__.py` - Run with `python -m engine`
  - `examples/` - Quickstart code

**primitives/docs/manifesto.md** - The practitioner manifesto (MIT, freely quotable)

**context-service** remains private (full production system).

## Licensing Rationale

At pre-seed, the primary threat is obscurity, not cloning.

The actual moat is in context-service:
- Custodian workers (automated claim-to-fact promotion, supersession)
- Multi-tenancy architecture
- Dagster pipeline orchestration
- Production-scale backends

The primitives math and engine wrapper are adoption drivers, not IP to protect. Apache 2.0 on engine removes BSL friction (legal teams, "is this open source?" skepticism) while keeping context-service proprietary.

Revisit licensing in 12-18 months if free-rider competitors emerge. FSL (Sentry model) or AGPL are options then.

## Licensing Boundary

Open (MIT via primitives):
- Epistemology math (confidence, promotion rules, contradiction detection)
- Scoring formulas (Gaussian decay)
- Schema definitions (node types, edge types)
- Protocol interfaces
- The manifesto

Open (Apache 2.0 via engine):
- Single-tenant SQLite engine
- Basic MCP server surface
- Manual promotion (no custodian)

Proprietary (context-service):
- Multi-tenancy (silo_id partitioning)
- Custodian workers (automated curation)
- Production backends (Memgraph, Qdrant, Redis)
- Dagster pipelines
- Scale and performance tuning

## Manifesto Structure

Location: `primitives/docs/manifesto.md` + landing page

Audience: AI engineers and technical founders/CTOs

Key changes from review:
- Hook in first paragraph, not section 2
- Define EAG in first 3 sentences
- Concrete hello-world: claim in, fact out, query back

Outline (~5-6 pages, 15 min read):

1. **The Hook** (opening paragraph)
   - "The difference between a filing cabinet and an analyst."
   - "Memory products store what agents saw. Engrammic stores what agents figured out, and whether it held up."
   - Define EAG: Epistemic Augmented Generation - a paradigm where agent knowledge is curated, not just stored.

2. **The Problem** (1 page)
   - RAG was built for chatbots, not agent teams
   - Memory systems store what agents saw, not what they figured out
   - No curation means context window garbage

3. **The Four Layers** (1 page)
   - Memory: experiences that fade (Gaussian decay)
   - Knowledge: facts that persist until contradicted
   - Wisdom: beliefs that revise on evidence shift
   - Intelligence: ephemeral reasoning (session-scoped)

4. **EAG in Practice** (2 pages)
   - How claims become facts (R1/R2 promotion)
   - How facts get superseded
   - Code snippets from primitives

5. **Getting Started** (1 page)
   - Install: `pip install delta-prime-primitives delta-prime-engine`
   - Run: `python -m engine`
   - Hello world walkthrough:
     - Agent writes a claim via MCP
     - Manual promotion to fact
     - Query it back
   - Link to examples/

6. **When You Need More** (half page)
   - What commercial tier adds (custodian, multi-tenancy, scale)
   - Waitlist CTA (not "contact us")

## Launch Sequence

### Prep Work

Code:
- Build engine/ repo (SQLite store, basic MCP server)
- Ensure primitives README links to manifesto
- Ensure engine README links to manifesto

Docs:
- Write manifesto
- CONTRIBUTING.md in both repos
- CODE_OF_CONDUCT.md
- Issue templates (bug report, feature request)
- "Why Apache 2.0" note in engine README

Landing page:
- Manifesto rendered
- Get started CTA
- Waitlist for commercial tier

Distribution prep:
- Draft HN Show HN post (title + 2-sentence framing)
- Identify low-competition posting day
- Designate who posts

### Launch Day

- Push both repos public simultaneously
- Manifesto goes live on landing page
- HN Show HN post linking to manifesto
- Twitter/LinkedIn posts
- README links manifesto, manifesto links repo

### Post-Launch

- Monitor GitHub issues, engage early adopters
- Iterate on docs based on confusion points
- Collect waitlist signups for commercial tier

## Commercial Conversion

### Funnel

1. Free tier: primitives + engine (local, single-tenant)
2. Waitlist: "early access" framing for production users
3. Post-raise: free cloud tier (usage-gated, no credit card)
4. Commercial: context-service access, managed hosting, support SLA

### Conversion Triggers

- Production deployment needs
- Multi-tenant requirements
- Automated curation (custodian)
- Scale requirements

### What Commercial Customers Get

- Access to context-service
- Managed hosting option (post-raise)
- Support SLA
- Priority feature requests

## Timing Consideration

Open question: release before or after Antler close?

Arguments for before:
- Credibility signal during raise
- Shows execution ability
- Partner conversations can reference it

Arguments for after:
- Avoids negotiation leverage loss ("your IP is public")
- More time to polish
- Can point to traction first

Current decision: flexible, but lean toward after first design partner traction (Silt talks). Revisit after partner conversations progress.

## Open Items

- [ ] Finalize manifesto draft
- [ ] Build engine/ repo MVP
- [ ] Landing page design
- [ ] HN post framing
- [ ] Waitlist infrastructure

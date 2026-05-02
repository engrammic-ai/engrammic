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
- License: BSL 1.1 (free for non-production, converts to MIT after 3 years)
- Depends on: primitives
- Contains:
  - `engine/store/` - SQLite-backed single-tenant store
  - `engine/mcp/` - Basic MCP server (read/write tools)
  - `engine/__main__.py` - Run with `python -m engine`
  - `docs/manifesto.md` - The practitioner manifesto
  - `examples/` - Quickstart code

**context-service** remains private (full production system).

## Licensing Boundary

Open (MIT via primitives):
- Epistemology math (confidence, promotion rules, contradiction detection)
- Scoring formulas (Gaussian decay)
- Schema definitions (node types, edge types)
- Protocol interfaces

Source-available (BSL via engine):
- Single-tenant SQLite engine
- Basic MCP server surface
- Manual promotion (no custodian)

Commercial (context-service):
- Multi-tenancy (silo_id partitioning)
- Custodian workers (automated claim-to-fact promotion, supersession)
- Production backends (Memgraph, Qdrant, Redis)
- Dagster pipelines
- Scale and performance tuning

## Manifesto Structure

Location: `engine/docs/manifesto.md` + landing page

Audience: AI engineers and technical founders/CTOs

Outline (~5-6 pages, 15 min read):

1. **The Problem** (1 page)
   - RAG was built for chatbots, not agent teams
   - Memory systems store what agents saw, not what they figured out
   - No curation means context window garbage

2. **The Shift** (1 page)
   - Hook: "The difference between a filing cabinet and an analyst"
   - Explanation: "Memory products store what agents saw. Delta Prime stores what agents figured out, and whether it held up."
   - Four layers: Memory, Knowledge, Wisdom, Intelligence

3. **EAG in Practice** (2 pages)
   - How claims become facts (R1/R2 promotion)
   - How facts get superseded
   - Code snippets from primitives

4. **Getting Started** (1 page)
   - Install primitives + engine
   - Run the MCP server
   - Try the tools
   - Link to examples/

5. **When You Need More** (half page)
   - What commercial tier adds
   - Contact / waitlist CTA

## Launch Sequence

**Prep work:**
- Build engine/ repo (SQLite store, basic MCP server)
- Write manifesto
- Landing page with manifesto + get started CTA

**Launch day:**
- Push both repos public simultaneously
- Manifesto goes live on landing page
- HN / Twitter / LinkedIn post linking to manifesto
- README links manifesto, manifesto links repo

**Post-launch:**
- Monitor GitHub issues, engage early adopters
- Iterate on docs based on confusion points
- Collect production interest leads for commercial tier

## Commercial Conversion

Triggers for commercial outreach:
- Production deployment
- Multi-tenant needs
- Automated curation (custodian)
- Scale requirements

What commercial customers get:
- Access to context-service
- Managed hosting option (later)
- Support SLA

No self-serve pricing initially. Contact for production use.

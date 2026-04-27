# 2026-04-27: Notion Wiki + Working Surfaces Bootstrap

## Summary

Bootstrapped the delta-prime Notion teamspace from near-empty (one investor CSV) to a usable
shared brain for the three cofounders. Authored 12 wiki content pages, created 3 new
working-surface databases, retagged the existing Product Roadmap to fit a 3-person team, and
patched stale tool/perf references in `CLAUDE.md`. No code changes to the service itself.

## Wiki content pages

All 12 published in the existing `Wiki` database. Tone: human, no buzzwords; non-technical
cofounders are the primary readers.

- **What is delta-prime** — orientation page; the "if you read one thing" page. Cognitive
  substrate framing, four kinds of knowing, anti-claims (not RAG/KG/LLM/search).
- **Positioning** — dual-track stance (front-door = "memory/context infrastructure for AI
  agents"; deeper = "cognitive substrate"). Per-room talking points; sentences-not-to-use.
- **Who it's for (ICP)** — primary AI-native startups + mid-market in production; pain
  triggers (long-task failure, multi-agent drift, context economics, build-it-ourselves
  regret); disqualifier list; sanity-check checklist.
- **What we're building (v1)** — alpha scope. IN: MCP surface, four layers, meta-memory,
  extraction, custodian, clustering, SPLADE, Dagster, minimal dashboard, WorkOS, basic
  billing, migration tooling. OUT: on-prem, multi-region, advanced RBAC, public SDK, polished
  UX, OSS service release. Done-criteria tied to Knowzilla + Silt running real workflows.
- **Architecture (plain English)** — agent's-eye view of the MCP tool surface (one verb per
  layer: `remember`/`assert`/`commit`/`reason`/`reflect`); component-level walkthrough;
  EAG vs CITE explanation; two-repo split (`primitives` open / `context-service` closed).
- **Glossary** — paradigm, four kinds of knowing, claim→fact lifecycle, system pieces,
  industry adjacents (RAG/KG/vector DB/LLM/compaction/agent).
- **Competitive landscape** — ~10 cofounder-ready summaries (NeoCognition promoted to top
  Direct after web research surfaced their April 21, 2026 stealth exit with $40M); live
  competitor tracker table with verified sources via WebSearch.
- **Brand / Visual Identity** — placeholder; Jane owns.
- **Pitch materials** — index page; Vic owns.
- **How we work** — cadence (weekly minimum, async-first), conversation in Telegram, work
  in Notion + GitHub (Plane/Linear later), decision style (in-area solo, cross-area group).
- **Roles & ownership** — Engineering = founder; Design = Jane; BD/GTM = Vic; fundraising
  co-owned by founder + Vic.
- **Cofounder profiles** — placeholder; cofounders fill themselves.

## Working-surface databases

Three new databases created (parent currently Wiki, user moving to a new Operations page):

- **Decision Log** — Decision/Date/Decided by/Area/Status/Why/Links. Captures the why so
  decisions don't get re-litigated.
- **Meeting Notes** — Meeting/Date/Type/Attendees/Tags. Template seed: Agenda /
  Discussion / Decisions / Action items.
- **Spec Handoff** — Feature/Status/Owner(design)/Owner(eng)/Priority/Linked PR. Template
  seed: Goal / Design / What's being built / Open questions / Decisions. The Jane↔founder
  collaboration channel.

## Existing-database changes

- **Product Roadmap** — `Team` options replaced (`AI/Platform/Security/Mobile` →
  `Engineering/Design/GTM`); `Quarter` options replaced (`Q1..Q4` → `Now/Next/Later`)
  to fit rolling seed-stage planning.

## Schema updates

- **Wiki database** — `Tags` multi-select expanded with new options:
  `Start Here / Product / GTM / Operations / Tech` (existing `Onboarding` and `Design`
  preserved). Per-page retagging is a manual step in the Notion UI — wiki databases
  expose a hard MCP limit: *"You do not have the tools to update custom property values."*

## CLAUDE.md patches

Stale references replaced with current MCP surface:

- Added `## MCP tool surface` section enumerating reads (`context_get`, `context_query`,
  `context_graph`, `context_history`, `context_provenance`), writes by layer
  (`context_remember` / `context_assert` / `context_commit` / `context_reason` /
  `context_reflect`), `context_link`, and silo tooling.
- Performance-targets table updated: `context_lookup` → `context_query`,
  `context_store` → single-layer writes, `context_store_chain` → `context_reason (chained)`.

## Notion API gotchas captured

- **Wiki databases require `title` (not the schema's title-column name like `Page`) when
  setting page titles via MCP.** Passing the schema name silently no-ops; pages publish
  with default title "Introduction" or "New Page". Saved to memory.
- **Wiki databases reject custom-property updates entirely** via the MCP integration. Tag
  application has to be done in the UI.
- **No teamspace-parent option** when creating top-level pages programmatically; Operations
  page had to be created manually in the UI.
- **No move-database operation**; once a DB has a parent, it stays there unless trashed
  and recreated. Manual UI move is the workaround.

## Process notes

- Per-page Q&A workflow worked well for the 7 "defining" pages (What is, Positioning, ICP,
  v1, Architecture, Glossary, Competitive). Light-Q&A batching worked for the 5 procedural
  pages.
- Web-verified the competitor table via a sub-agent with explicit WebSearch instructions
  after a first attempt revealed the agent had silently fallen back to training-data only.
- Skipped writing a separate design-doc artifact under `docs/superpowers/specs/` —
  the published pages themselves are the spec for this work, and a parallel filesystem doc
  would have been redundant.

## Manual steps remaining for the user

1. Move the 3 new databases under the Operations page.
2. Apply tags to the 12 wiki pages per the retag list (~30 sec in UI).
3. Convert the 3 `[Template]` seed entries to real templates ("Turn into template" →
   set as default) in Decision Log, Meeting Notes, Spec Handoff.
4. Fill the Cofounder Profiles page — needs founder + Jane + Vic input.
5. Knowzilla and Silt one-liners on the ICP page (placeholder).

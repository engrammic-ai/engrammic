# Docs overhaul design spec (workstream B)

Date: 2026-06-04
Status: Design spec, ready for review. Implementation gated on user approval.
Companion: context/brainstorm/2026-06-04-enforcement-harness-docs.md (full analysis + roast + IA research).
Depends on: workstream A (enforcement architecture) only at the seam pages listed below. Everything else is
independent and can ship now.

## Goal

Make ../web/docs (Fumadocs/Next.js) trustworthy and on-message: fix the content that breaks our own rules and
current positioning, fix the factual bugs, and restructure the IA along Diataxis so a new user, a builder, and a
self-hoster each have a clear path. A self-hoster who cannot find a knob is the same as the knob not existing, so
docs quality is part of "out of the box effective," not adjacent to it.

## Non-goals

- Documenting enforcement features that workstream A has not decided yet (see The Seam).
- Rewriting the marketing site (web/engrammic-site), the blog, or join.engrammic.ai.
- Building the auto-generators in this spec; we specify the contract, the implementation plan builds them.

## Target IA (root meta.json order)

get-started, concepts, guides, integrations, reference, self-hosting, building, changelog.

Rationale (Diataxis: never mix tutorials / how-to / reference / explanation): memory products lead with Concepts
earlier than generic SaaS (Zep leads with it; mem0/Cognee/Supermemory place it second) because "what is a trust
layer and why" is load-bearing before the API. So Concepts is elevated, and "why" stops being buried last.

1. get-started: 30-second what+why, Quickstart (<5 min, one-click via join.engrammic.ai), Verify, First memory.
2. concepts: the problem (repositioned), the four layers, provenance & evidence, trust & confidence [SEAM],
   engagement markers.
3. guides (how-to): use memory well, common patterns, multi-agent, resolving markers, debugging, troubleshooting.
4. integrations / harnesses: Claude Code, Cursor, VS Code, Codex, Gemini, others, point a harness at self-hosted,
   hooks [SEAM].
5. reference: MCP tool surface (auto-generated), SDK, skills (auto-generated), configuration, enforcement knobs
   [SEAM], errors & limits.
6. self-hosting (promoted to top-level, a primary buyer path): quickstart, compose, telemetry, config.
7. building: embedding Engrammic into your own agents.
8. changelog.

## Page-by-page migration (13 current content pages)

| Current page | Disposition | Destination / notes |
|---|---|---|
| index.mdx | SPLIT | get-started/index (30-sec what+why) + get-started/quickstart + get-started/first-memory. Fix dead /docs/guides/patterns card link. |
| why.mdx | REWRITE + MOVE | concepts/index + concepts/the-problem. Drop the "epistemic memory" lede; reposition to "memory that does not rot, does not hallucinate, and can show its work." Retire the "why" slug (redirect). |
| guides/harness-integration.mdx | SPLIT + RETIRE | Per-harness setup -> integrations/{claude-code,cursor,codex,gemini,others}. The instruction snippet is no longer hand-written here; it renders from the single canonical source (below). Retire slug (redirect to integrations). |
| guides/eag-guide.mdx | MOVE + RENAME | guides/use-memory-well. |
| guides/multi-agent.mdx | KEEP (light edit) | guides/multi-agent. |
| guides/engagement.mdx | REWRITE | guides/resolving-markers. Remove accept()/reject() calls (no handlers exist, verified). Gate-default behavior is a [SEAM] subsection. |
| guides/troubleshooting.mdx | SPLIT | guides/troubleshooting (general) + self-hosting troubleshooting content moves under self-hosting. |
| reference/tools.mdx | REPLACE (auto-gen) | Generated from config/mcp_tools.yaml + param schemas. Fixes existing drift (omits dismiss, tick). |
| reference/sdk.mdx | KEEP as honest stub | Relabel "Coming Soon" to "Planned" with a clear status; reconcile with building. |
| reference/skills.mdx | REPLACE (auto-gen) | Generated from the installer's skills manifest (the yaml has zero skills). |
| reference/configuration.mdx | REWRITE | It is the stale draft (verified): DATABASE_URL/REDIS_URL/SECRET_KEY came from the unrelated beacon_service; canonical is POSTGRES_HOST / ENGRAMMIC_LICENSE_KEY / image engrammic-api:latest (settings.py). Remove the fabricated config.yaml + sage.* knobs (no such file is loaded; only mcp_tools.yaml and mcp_presets.yaml use CONFIG_PATH). |
| reference/building.mdx | MOVE | building/index (top-level). |
| reference/self-hosting.mdx | MOVE / PROMOTE | self-hosting/ (top-level section; split compose + env + telemetry). |

New pages added (~24): the get-started trio; concepts/{the-problem, four-layers, provenance-and-evidence,
trust-and-confidence[SEAM], engagement-markers}; guides/{common-patterns, debugging}; integrations/{index,
claude-code, cursor, vscode, codex, gemini, others, point-at-self-hosted, hooks[SEAM]}; reference/{enforcement-
knobs[SEAM], errors-and-limits}; self-hosting/{quickstart, compose, telemetry, config}; building/index; changelog.

## Content and tone fixes (apply everywhere)

- Remove every em-dash. Hard rule. Pervasive today (index.mdx:10,12,14,16; why.mdx:10,21,27,29,31,33,37,39-42,44).
- Kill the AI-slop closers, e.g. why.mdx:44 "Your agent doesn't just remember, it knows."
- Drop the "epistemic memory" lede sitewide; lead with the repositioned line. "Epistemic" can appear later as the
  technical term, never as the hook.
- Tone bar: human, no buzzwords, no AI-slop. This spec and every generated page follow it (no em-dashes here either).
- The triplicated Minimal/Standard/Full instruction blocks collapse to one canonical block plus "add these rows
  for more."

## Correctness bugs (all verified against code by the research pass)

- configuration.mdx is the stale draft; reconcile to the self-hosting.mdx canonical setup. (settings.py.)
- The documented config.yaml (sage.custodian_interval, etc.) is fabricated; no such file is loaded.
- accept()/reject() are not in the tool surface (no handlers); engagement docs must not tell agents to call them.
- Dead link: index.mdx:31 -> /docs/guides/patterns (no such page).
- tools.mdx has already drifted (omits dismiss and tick); the auto-generator removes this whole class of bug.

## Structural upgrades

1. Two doc generators (build step), so reference never drifts from the surface again:
   - tools reference <- config/mcp_tools.yaml for names/descriptions, plus param/return schemas from the
     FastMCP/Pydantic registry (the yaml lacks param schemas). Fallback if the registry is not generator-friendly:
     scope params to the SDK page. (Open question 3.)
   - skills reference <- the installer's shipped skills manifest (the yaml has zero skills).
2. Ship llms.txt + llms-full.txt (llmstxt.org). Every memory competitor ships it; we do not. On-brand for an
   AI-memory product. Adopters include Anthropic, Stripe, Cloudflare.
3. Fast-follow (not blocking): a docs MCP server (Zep ships one) since we are MCP-native, plus "Ask AI" search.

## Single canonical instruction source (structural fix)

The "Memory (Engrammic MCP)" snippet lives in >=3 hand-maintained places today (project CLAUDE.md, the docs
harness page, installer output) and drifts. Define ONE Markdown partial as the source of truth, rendered into:
(a) the docs instruction snippet, (b) the installer's per-harness output, (c) CLAUDE.md. The MCP server
`mcp_instructions` field is reconciled as a related-but-separate artifact: either derived from the same source or
kept as a terse standalone block (Open question 2, left to the plan).

## The seam (workstream A boundary), drawn at page-slot level

These slots are reserved now but their content is "pending Spec A; do not finalize until A is decided." Everything
else proceeds independently.

- concepts/trust-and-confidence (the trust-gated-injection story).
- integrations/hooks (the hook suite) and the hooks subsection on each integrations/{harness} page.
- reference/enforcement-knobs (engagement modes/thresholds, tick interval, profiles, write-gate posture).
- guides/resolving-markers: the gate-default-behavior subsection only.

## Acceptance criteria

- Zero em-dashes sitewide; no page leads with "epistemic memory"; the AI-slop closers are gone.
- No factual contradictions; the five verified bugs are fixed or removed.
- Root and per-section meta.json reflect the target IA; all internal links resolve (no 404s).
- tools and skills pages are generated from source, not hand-maintained.
- llms.txt + llms-full.txt exist and are linked.
- Every seam slot carries the pending-Spec-A note and contains no guessed enforcement content.

## Phasing

- Phase 1 (independent, ship now): tone + correctness fixes, IA skeleton (meta.json + page moves/redirects), the
  two generators, llms.txt. This is the embarrassingly parallel set (one agent per page or fix).
- Phase 2 (after Spec A): fill the seam slots.

## Open questions (for the implementation plan)

1. Skills inventory disagreement: the initial `ls skills/` showed ~24 engrammic-* dirs (incl. engrammic-observe);
   the research pass reported only 4 in tree. The auto-generator from the installer manifest makes the docs moot,
   but the source-of-truth skills set must be confirmed before generating.
2. Does mcp_instructions derive from the canonical instruction file, or stay a separate terse block?
3. Does the FastMCP registry expose param/return schemas in a generator-friendly form?
4. Which release history seeds the new changelog?

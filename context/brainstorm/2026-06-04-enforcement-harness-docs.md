# Enforcement layer, harness integration, and docs

Date: 2026-06-04
Status: Brainstorm / considerations (not a final spec). Source material for one or more design specs.
Topic: How do we make Engrammic "out of the box effective" beyond just installing the MCP? Covers the
enforcement layer (inject / gate / instruct), harness integration, self-hosted, and the docs at ../web/docs.

## Framing

Strategy is already set (wisdom node a1d6eabb, 2026-05-29): do NOT build our own harness. Become an active
context layer "as far as harness hooks allow," via inject / gate / instruct, depth-first on Claude Code as the
wedge, harness-agnostic as the distribution principle. "Enforcement layer" = how far we push inject/gate/instruct
through mechanisms the ecosystem already exposes.

## Finding 1: the 4-tier hierarchy of forcing functions (by how little harness cooperation each needs)

Sourced from web research (primary docs cited). Earlier assumption that "hooks are basically Claude-Code-only"
was WRONG as of mid-2026.

1. **Tool descriptions** - the only truly universal, zero-setup lever. Every MCP client sends tool name+description
   to the model; that is how function calling works. This is our real lowest common denominator. Invest hardest
   here: encode "recall-first," "persist proactively," and the supersession rule directly into the
   recall/remember/learn/believe descriptions. (Anthropic, "Writing effective tools for AI agents": tool
   descriptions are a primary forcing function, drove SOTA on SWE-bench Verified.)
2. **MCP server `instructions` field** - ships WITH the server (so self-hosters get it free), but rendering is
   client-optional: Claude Code yes, Codex yes (truncates at first 512 chars), Cline no, Gemini/Cursor/Windsurf
   unverified. Keep the most critical guidance in the first 512 chars. Treat as a bonus, not a guarantee.
   (MCP lifecycle spec 2025-06-18.)
3. **Rules files** (CLAUDE.md / AGENTS.md / .cursor/rules / GEMINI.md / .clinerules / .windsurfrules) - universal
   INSTRUCT, but require install and are "context, not enforced configuration" (Anthropic's own words about
   CLAUDE.md). AGENTS.md is the converging cross-harness standard.
4. **Hooks** - the deterministic INJECT/GATE layer. NO LONGER Claude-Code-only: all six harnesses surveyed
   (Claude Code, Cursor, Codex, Gemini, Windsurf, Cline) now ship hook systems.
   - GATE (block tool call + feed reason to model): converged across all six. This is the robust claim.
   - INJECT (programmatic context into the model): confirmed in the four CLI-class harnesses (Claude Code, Cursor,
     Codex, Gemini); unverified in Windsurf/Cline.
   - Contract portability: Codex reuses Claude Code's exact JSON; Gemini is CC-style with its own event names;
     Cline tracks the CC spec. One hook script is largely reusable across CC + Codex.

Key Claude Code hook facts (code.claude.com/docs/en/hooks):
- SessionStart, UserPromptSubmit stdout/`additionalContext` is injected into context the model sees.
- SessionStart fires BEFORE MCP servers connect, so a session-start recall hook must hit Engrammic's HTTP endpoint
  directly (command/http hook), NOT an mcp_tool hook.
- UserPromptSubmit is the strongest per-turn inject lever (servers are connected by then).
- PreToolUse can `deny` a write + reason shown to model (prevent a bad write before it lands).
- PostToolUse can `block` + reason (validate a write, tell model to fix; cannot undo).
- Stop can `block` + reason (the closest thing to compelling proactive persistence: "you discovered X, persist it").
- `additionalContext` must be factual statements, not imperative instructions, or prompt-injection defenses surface
  it to the user.
- Cleanest distribution: package as a Claude Code PLUGIN (MCP + hooks + skill in one marketplace install); the
  installer covers the other harnesses.

Primary sources: code.claude.com/docs/en/hooks, /memory, /skills, /plugins; cursor.com/docs/hooks;
developers.openai.com/codex/hooks; geminicli.com/docs/hooks; docs.windsurf.com/.../hooks; docs.cline.bot/.../hooks;
modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle; anthropic.com/engineering/writing-tools-for-agents.

## Finding 2: the competitor bar, and the calibrated wedge

(Web research; READMEs primary, some doc hosts blocked - see provenance caveats in session.)

- **Auto-extraction (server-side LLM turns turns into structured memory) is TABLE STAKES.** mem0, Zep, Graphiti,
  Cognee, Memobase, LangMem all do it. A product that only stores raw text (txtai) reads as "infrastructure."
- **Frictionless drop-in (no explicit add()/search()) is an EMERGING PREMIUM, not the norm.** Most still require
  explicit add()/search() + stitching. True auto-both exists cleanly in only two: Memobase's `openai_memory`
  client patch (add a user_id) and Supermemory's Memory Router (swap the base URL). The frontier is collapsing
  integration to "change one line."
- **Temporal/contradiction handling is ALSO commodity.** Zep and Graphiti invalidate contradicting facts on a
  bi-temporal model; Cognee does ontology dedup. CALIBRATION: do NOT pitch "we detect contradictions / supersede
  stale facts" as the wedge - a knowledgeable buyer will catch the overlap.

**The defensible wedge** (the shared failure mode every competitor inherits because extraction is commodity): they
all flatten the extractor's output into ONE undifferentiated equal-trust tier and inject whatever it guessed, with
no trust gate. Three specific gaps:
1. No trust typing (raw observation vs evidenced claim vs committed belief). A one-turn hallucination is stored
   with the same authority as a verified fact. = Engrammic's Memory -> Knowledge -> Wisdom.
2. Provenance is ingestion-time ("when did I learn this"), not evidence-of-truth ("what proves it / who said it /
   can I verify it").
3. No confidence-gated injection: they will confidently inject a low-confidence or superseded memory.

Wedge stated for the pitch: as auto-capture commoditizes, the unsolved problem moves downstream to TRUSTING what
was captured. Win by attaching trust type + evidence + confidence AT CAPTURE, and by REFUSING to auto-inject
unverified / low-confidence / superseded memory. Competitors optimize capture volume and recency; the open lane is
capture trustworthiness + a trust-gated recall/injection path.

## Finding 3: architecture direction

- **Portable spine = server-side trust-gated injection + a server-side gate.** Because the gate and the
  tool-response/`instructions` injection live in the MCP server, they travel to every client. This is also the
  differentiator (trust-gated recall) AND the out-of-the-box value, in one move.
- **Hooks = per-harness amplifier**, deepest on Claude Code (the wedge): session-start recall inject (http hook),
  per-turn recall primer (UserPromptSubmit), Stop-hook persistence nudge, PreToolUse write validator.
- **Tool-description hardening** is the universal baseline that needs no install.
- **Posture recommendation (resolves the "honestly idk"):** default to ambient-helpful INJECT with a trust gate on
  what gets injected (refuse to inject unwarranted memory), plus soft nudges on writes. Make HARD write-gating
  (evidence-required reject, contradiction hard-block) a documented one-flag opt-in (per silo / deployment).
  Self-hosted ships soft-by-default. This merges "ambient" and "guarded" but moves the gate to the READ/inject
  path, which is lower-friction and the actual differentiator.

## Finding 4: docs audit (../web/docs, Fumadocs, 16 pages)

Roughly 70% solid, 30% disqualifying because it breaks stated rules / current positioning.

Brand/tone (violates standing rules):
- Em-dashes pervasive: index.mdx:10,12,14,16; why.mdx:10,21,27,29,31,33,37,39-42,44. (No-em-dash rule.)
- why.mdx:44 "Your agent doesn't just remember, it knows." - textbook AI-slop closer. Cut.
- Leads with "epistemic memory" (index.mdx:6, why.mdx title + H2). Contradicts the 2026-06-03 strategy pivot:
  stop selling "epistemic memory," sell "memory that does not rot, does not hallucinate, and can show its work."

Correctness bugs:
- configuration.mdx vs self-hosting.mdx contradict each other: DATABASE_URL/REDIS_URL/SECRET_KEY + image
  context-service:latest vs POSTGRES_HOST/ENGRAMMIC_LICENSE_KEY + image engrammic-api:latest. Two conflicting
  setups for the same product. One is a stale draft.
- configuration.mdx:80-95 documents a config.yaml (sage.custodian_interval, CONFIG_PATH) - verify it exists; SAGE
  is being replaced by the reactive brain architecture, so those knobs may be doubly dead.
- configuration.mdx:99 points to a "full configuration reference in the self-hosting guide" that does not exist.
- index.mdx:31 "Common Patterns" links to /docs/guides/patterns - no such page. 404 on the landing page.
- engagement.mdx:62-66 tells the agent to call accept()/reject() - not agent-facing verbs per CLAUDE.md, not in
  mcp_tools.yaml's 15 tools. Reconcile.
- skills.mdx is incomplete (lists 20 of ~26; omits engage, quick-card, review, accept/reject) and name-drifted
  (repo skills/ dir uses engrammic-observe; docs+installed use engrammic-remember).

Gaps (the out-of-the-box ones):
- harness-integration.mdx is misnamed: titled for all harnesses, body is only "paste this markdown into
  CLAUDE.md/AGENTS.md." Zero mention of hooks, engagement, inject/gate. Documents only the weakest lever. Also
  triplicated (Minimal/Standard/Full are three near-identical 30-line blobs).
- No reference for enforcement knobs (engagement modes/thresholds, ENGRAMMIC_TICK_INTERVAL, session-id, profiles).
  Self-hosters = "builders who need reference" have nothing to tune by.
- No "point a harness at your self-hosted endpoint" story.
- No hooks page, no installer/CLI page. sdk.mdx and building.mdx:128 are both "Coming Soon"; sdk.mdx is a 21-line
  stub in the nav.

IA problems:
- Only two buckets (guides, reference) + floating index/why. Diataxis types are mixed: building.mdx and
  self-hosting.mdx are tutorials/how-tos misfiled under reference; "why" (explanation) is buried last.
- No quickstart distinct from index; no concepts section; no integrations section.

Structural fix (single source of truth): the "Memory (Engrammic MCP)" instruction snippet now lives in >=3
hand-maintained places (project CLAUDE.md, harness-integration.mdx, installer output). Generate all copies from
ONE canonical source -> MCP server `instructions` + docs snippet + installer per-harness output. Kills the drift
class, not one instance.

Meta-point: for a self-hoster or builder, undocumented enforcement knobs == non-existent ones. Docs quality is
part of "out of the box effective," not adjacent to it.

## Restructured IA (Diataxis-flavored; CONFIRMED by comparables research 2026-06-04)

Diataxis (diataxis.fr) = separate tutorials / how-to / reference / explanation, never mix. Widely adopted
(Canonical/Ubuntu, Cloudflare, Gatsby, Django, NumPy). Gold-standard shape: Get Started -> Guides -> Reference,
Concepts woven near top, Integrations + Self-hosting as siblings, Changelog near end. KEY: memory products lead
with Concepts EARLIER than generic SaaS (Zep leads with it; mem0/Cognee/Supermemory place it 2nd) because "what is
a memory/trust layer and why" is load-bearing before the API. This backs pulling Concepts forward + killing the
buried "why".

1. Get Started: 30-sec what+why + Quickstart (<5 min, one-click via join.engrammic.ai), Verify, First memory.
   Fold why.mdx's hook up here.
2. Concepts (elevated, load-bearing): the problem repositioned (no "epistemic" lede), the four layers, provenance
   & evidence, trust/confidence (the differentiator), what engagement markers mean. Absorbs why.mdx.
3. Guides (how-to): use memory well, recall-first, storing with evidence, resolving markers, multi-agent, debug.
4. Integrations / Harnesses (new top-level): Claude Code (plugin), Cursor, VS Code, Codex/Gemini/others; +
   point a harness at self-hosted. Where the per-harness inject/gate/instruct + hooks story lives. Non-optional
   for a drop-in MCP product.
5. Reference: MCP tool surface, SDK, skills, configuration (single source), enforcement knobs, errors/limits.
6. Self-hosting (promote to top-level, a primary buyer path like mem0's open-source/): quickstart, compose,
   telemetry, config. Existing source material may be at context-service/docs/self-hosted/.
7. Building with Engrammic: embedding into your own agents.
8. Changelog (new).

Three citation-backed upgrades to bake in:
- Auto-generate the tool reference from config/mcp_tools.yaml (already the source of truth). Kills the
  tools.mdx/skills.mdx drift permanently; docs stay in lockstep with the surface. (Mintlify-style OpenAPI auto-gen
  analog.)
- Ship llms.txt + llms-full.txt (llmstxt.org). EVERY memory competitor has it (mem0, Zep, Cognee, Supermemory);
  we do not. Table stakes for the category and on-brand for an AI-memory product. Adopters incl. Anthropic, Stripe,
  Cloudflare.
- Consider a docs MCP server (Zep ships one at help.getzep.com/docs-mcp-server). We are MCP-native, so serving our
  own docs over MCP is dogfooding + thematically perfect. Plus "Ask AI" agentic search.

Comparables-research caveat: WebFetch/curl were sandboxed, so exact sidebar ordering is inferred from URL paths +
search snippets; section existence is high-confidence. Sources: diataxis.fr; docs.mem0.ai; help.getzep.com;
docs.letta.com; docs.cognee.ai; supermemory.ai/docs; modelcontextprotocol.io; Stripe/Supabase/Clerk/Vercel docs;
llmstxt.org; mintlify.com/docs.

## Decomposition (this is 2-3 projects, not one)

A. Enforcement architecture - the inject/gate/instruct spine (server-side trust-gated injection + portable gate +
   tool-description hardening + hooks amplifier). Biggest, most novel.
B. Docs overhaul - content fixes (tone, positioning, correctness bugs) + IA restructure. Self-contained,
   lowest-risk, what the user keeps circling. Fixing it forces us to articulate the concepts A will implement.
C. Installer / distribution - per-harness hook provisioning + one canonical instruction source + Claude Code
   plugin packaging. Bridges A and B.

Recommended sequence: B first (ships value fast, de-risks A by forcing concept articulation; the tone/positioning/
correctness/IA fixes are needed regardless of A). Then A (the meaty design). Then C (mostly mechanical once A is
decided). Document A's new features in the docs after A lands.

## Pending decisions / open questions

- Which workstream to spec first (recommend B).
- Posture default confirmed? (recommend ambient-helpful inject + trust-gated injection, hard write-gate opt-in.)
- Comparables doc-IA research still running (will refine the provisional IA above with citations).
- Correct Engrammic node 378c04a2 (overstates Gemini contract + MCP-instructions support) via supersession.

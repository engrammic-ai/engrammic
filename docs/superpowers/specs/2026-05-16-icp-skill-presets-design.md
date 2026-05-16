# ICP Skill Presets - Design

Date: 2026-05-16
Status: Approved for planning
Branch: feat/icp-skill-presets

## Problem

Engrammic ships a single, generic agent onboarding experience. Every tenant
sees the same `mcp_instructions` string and the same 13 `engrammic:*` verb
guides. Different ICPs (coding/dev agents, vertical B2B/ops agents) use the
memory system in materially different ways and would benefit from onboarding
guidance and default behaviors tuned to their workflow. We want named ICP
"presets" that bind per tenant and shape onboarding plus defaults, without
forking the server or coupling to any one agent harness.

## Conceptual model: two orthogonal axes

These are deliberately separate mechanisms. The spec keeps them separate.

**Axis 1 - MCP tool profile (the verb surface).** Lives in `mcp_tools.yaml`
(`standard`, `reasoning`). Governs which MCP verbs are exposed. Resolved at
server boot, server-global. This design does not touch it. If an ICP needs a
different verb surface, that stays a tool-profile concern configured
independently. Presets do not gate verbs.

**Axis 2 - Skill preset (onboarding plus workflow guidance).** Lives in
`mcp_presets.yaml`, resolved per silo at request time, delivered via the
`patterns` tool. Governs how an agent is taught to use whatever verbs it has,
plus a small set of param defaults. This is what this design builds.

They compose, never substitute. A silo always has both a tool profile (what it
can call) and a skill preset (how it is coached and tuned). A preset may
document an assumed tool profile in its onboarding text, but cannot change the
exposed verb set.

**Skills are tiered:**

- **Base skills** - the universal `engrammic:*` verb guides. Ship with every
  install. Always visible.
- **ICP overlay skills** - `coding:*`, `b2b-ops:*`, and future bundles.
  Shipped on top for specific demos and customer use cases. Additive, ranked
  first, never replace the base tier.

Adding an ICP is "ship an overlay skill bundle plus a preset that points at
it" - no change to the base tier, no change to the verb surface.

## Architecture

A preset is a named ICP profile resolved per request from the caller's silo.
Three layers:

- **Definition** - `src/context_service/config/mcp_presets.yaml`, git
  versioned. Each preset declares `skill_namespace`, an `onboarding_skill`
  name, and `param_overrides`.
- **Binding** - a nullable `preset` column on the existing Postgres
  `silo_config` table. Selects which preset a silo uses. Null falls back to a
  global default preset from settings.
- **Resolution** - extends the existing `SiloConfig.resolve(settings)`
  pattern. Preset `param_overrides` slot in as a layer between global settings
  and per-silo explicit overrides. Precedence:
  `global settings < preset overrides < per-silo explicit override`.

No new server instance, no boot-time coupling for the per-silo parts, no
hard dependency on a client-side skills directory for ICP specialization.

## Components and data flow

1. **`PresetRegistry`** - loads and validates `mcp_presets.yaml`, mirroring how
   `registry.py` loads `mcp_tools.yaml`. Exposes `get_preset(name) -> Preset`.
   Malformed yaml fails fast at boot, same as `mcp_tools.yaml`.
2. **Silo to preset lookup** - reads `silo_config.preset` (cached), falling
   back to `settings.default_mcp_preset`.
3. **`patterns` tool change** - when the caller passes no explicit `profile`
   arg, resolve the silo's preset and use its `skill_namespace`. Merge order:
   ICP-namespace skills first, then `engrammic:*` base guides, then any
   per-silo user skills. Explicit `profile=` still overrides as today (escape
   hatch).
4. **Onboarding pointer** - the global `mcp_instructions` in `mcp_tools.yaml`
   gains one line: "At session start, call
   `patterns(action='get', name='onboarding')` for your workflow guide." The
   preset's `onboarding_skill` is what `name='onboarding'` resolves to within
   that namespace, so per-ICP onboarding text is delivered without touching
   boot-time instructions.
5. **Param resolution** - tools with hardcoded defaults (`recall` `top_k`,
   `depth`) refactored to read resolved settings. Ship one param wired end to
   end (`default_recall_top_k`) to prove the path. Full param taxonomy is
   deferred.
6. **Skill bundles** - two new builtin namespaces shipped in `skills/`:
   `coding:*` and `b2b-ops:*`, each with at minimum an `onboarding` skill.
   Loaded exactly like today's `engrammic:*` builtins (in memory, silo `*`).

Flow: agent connects, reads the pointer in instructions, calls
`patterns(get, onboarding)`, server resolves silo to preset to namespace,
returns the ICP onboarding skill, agent works with ICP defaults applied to
`recall` and other param-driven tools.

## Skill content and format

- **SKILL.md open standard.** As of December 2025, `agentskills.io` is a
  cross-harness standard adopted by 32+ tools (Codex, Cursor, Windsurf, Gemini
  CLI, VS Code). The portable core is `name` plus `description` plus a markdown
  body. Shipped skill bodies use SKILL.md format with portable core frontmatter
  only; no Claude-specific extensions in shipped bundles. `patterns(get)`
  returns content any conforming harness can use natively.
- **Authoring rules** (from the standard's best practices): `description` is
  the activation trigger - task verbs, "use when..." phrasing, anti-patterns;
  body under ~500 lines / 5k tokens; progressive disclosure with detail moved
  to `references/`. The existing `patterns` list/get split already matches
  this.
- **Vehicle choice.** Delivering skills via an MCP tool with a list-then-get
  pattern is a validated production approach (for example SkillPort). The MCP
  prompts primitive is explicitly rejected here: it is user-controlled and
  thinly adopted outside Claude clients. The existing `patterns` tool needs no
  protocol change.

## Delivery channels and cold-start

Two complementary channels, not competing:

| Aspect | `patterns` over MCP (dynamic) | Filesystem bundle (static bootstrap) |
|---|---|---|
| Reaches | Any client connected to Engrammic MCP | Any harness, no MCP needed |
| Per-silo / per-ICP | Yes, binding resolved server-side | No, same files for everyone |
| Canonical path | n/a | `.agents/skills/` (portable) plus `~/.claude/skills/` |

ICP/preset binding is inherently per tenant, so ICP overlay bundles are
server and `patterns` delivered only. A static filesystem cannot vary by
silo. The base `engrammic:*` tier ships both ways. The repo README install
guidance updates to target the portable `.agents/skills/` path, not only
`~/.claude/skills/`.

Cold-start: the global `mcp_instructions` pointer line is the bridge for
connected-but-unaware clients. For non-MCP harnesses, the filesystem base tier
carries generic guidance; ICP specialization is simply unavailable without the
MCP connection, which is acceptable because ICP presets are a connected-tenant
feature by nature.

## Error handling

- Unknown or missing preset name: fall back to the default preset, log
  `invalid_mcp_preset`, mirroring the existing `invalid_mcp_profile` fallback.
- `mcp_presets.yaml` malformed at boot: fail fast as a config error, same as
  `mcp_tools.yaml`.
- Silo with null binding: default preset, no error.
- Explicit `profile=` arg always wins over preset-resolved namespace.

## Testing

- Preset resolution precedence: `settings < preset overrides < silo override`.
- `patterns` merge ordering: ICP namespace first, `engrammic:*` still visible,
  per-silo user skills appended.
- Explicit `profile=` still overrides preset resolution.
- Fallback paths: unknown preset name, null silo binding, missing
  `mcp_presets.yaml` entry.
- The one wired param (`default_recall_top_k`) measurably changes `recall`
  behavior when set via preset.
- Shipped ICP skill bundles parse as valid SKILL.md (portable core
  frontmatter present, body within size budget).

## Scope boundaries

In scope: preset definition file, per-silo binding column and lookup,
`patterns` namespace resolution and merge change, onboarding pointer line, one
param wired end to end, two ICP skill bundles (`coding:*`, `b2b-ops:*`), README
install path update.

Out of scope: changing the MCP verb surface or tool profiles; full param
taxonomy beyond the one proof param; an admin UI for editing presets;
filesystem delivery of ICP overlay bundles.

## Decisions locked

- Approach C: yaml definitions plus DB overrides.
- Namespace mode: ICP plus engrammic, additive, ICP ranked first.
- Tool profile is orthogonal and explicitly out of scope.
- Skill bundles ship in SKILL.md open-standard format.
- Dual-channel delivery; `patterns` is the per-silo vehicle, filesystem is
  base-tier bootstrap.

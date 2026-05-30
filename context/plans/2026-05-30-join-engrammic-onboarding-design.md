# join.engrammic.ai Onboarding Page Design

> **Type:** design spec (brainstorm output). Implementation plan to follow via
> superpowers:writing-plans. Lives here (`context/plans/`) to sit beside its hard
> dependency, `2026-05-30-self-serve-org-provisioning.md`.
>
> **Repo note:** the code lives in the sibling `../web` repo (new `web/join` app +
> edits to `web/docs`), with one cross-plan edit in this repo
> (`api/routes/oauth.py` success-page CTA). The spec lives here for planning
> continuity; the work spans both repos.

## Goal

A standalone, nice-looking page at `join.engrammic.ai` that does one job well:
get a new user from "I want this" to "my agent has memory," then hand off to the
docs. It replaces the install section of the docs quickstart as the single place
install lives.

## Why a separate app

`web/` is not a workspace monorepo. It is four independent Next apps (`docs`,
`engrammic-site`, `blogs`, `showcase`), each with its own `deploy-*.yml` and Cloud
Run service. `join` is a fifth, built the same way, so it deploys and scales on its
own and can look like the marketing site rather than the docs theme.

## Stack

Match `engrammic-site` so the visual language is consistent: Next 16, Tailwind v4,
shadcn components, framer-motion, lucide icons. Not Fumadocs (that is the docs
theme). New `.github/workflows/deploy-join.yml` mirroring `deploy-docs.yml` (push to
`main` under `join/**` -> Cloud Run). New domain mapping `join.engrammic.ai`.

## Pages

Two pages, nothing more.

### `/` (the hero)

A two-column split, the centerpiece of the whole page.

- **Left, "Add to your editor":** a grid of six popular tiles, in this order:
  VS Code, Cursor, Claude Code, Codex, Gemini CLI, Windsurf. Clicking a tile:
  - VS Code and Cursor fire their one-click deep link (the `vscode.dev/redirect`
    and `cursor://` URLs the installer already builds).
  - Every other tile slides open an inline panel showing the config file path and
    a copy-paste snippet for that tool.
  - Below the grid: a quiet link, "Couldn't find yours? Browse all 21 ->",
    pointing at `/catalog`.
- **Right, "Or install everywhere":** the `curl -fsSL https://get.engrammic.ai | sh`
  box (plus the Windows `irm ... | iex` variant), a copy button, and one line of
  reassurance: "auto-detects your tools and sets up memory and skills." This column
  gets the visual weight because it is the complete path (see Install matrix).
- **Below the split:** a short verify beat ("ask your agent: what MCP tools do you
  have?") and a prominent "Read the docs ->" handoff.

### `/catalog`

A searchbar plus all 21 harnesses as cards. Each card shows the config path, the
copy-paste snippet, and a one-click button where one exists. Same reveal and
deep-link mechanic as the hero tiles, just exhaustive. This is where the long tail
lives so the hero stays uncluttered.

## Install matrix (the skills answer)

The two install paths are deliberately not equivalent, and the page says so plainly
rather than pretending a deep link does everything:

- **curl install = complete.** The installer registers the MCP server AND installs
  skills, auto-detected across every tool it finds. This is the recommended path.
- **per-editor tile = MCP connection only.** A deep link or manual config registers
  the server but cannot install skills. After connecting, the tile's panel shows an
  optional final beat, "Enable proactive memory": the `AGENTS.md` / `CLAUDE.md`
  snippet to paste (the same block the docs quickstart already carries), or "run the
  installer to do this automatically."

So skills are baked into the curl path and surface as an opt-in step on the tile
path. No path silently half-installs without saying so.

## Harness data and drift

The Rust `engrammic harnesses --json` command is the true source of harness facts.
`docs` already has `src/lib/harnesses.ts` (151 lines) plus `check-harnesses.mjs`, a
guard that compares it against the Rust manifest.

`join` gets its own `src/lib/harnesses.ts`, a presentation-richer superset that adds
`popular: boolean`, a logo reference, and catalog ordering. The same drift-guard
script runs in join's CI against the Rust manifest. Two copies, but neither can
silently disagree with the installer, because CI fails on drift in either consumer.

We are not converting `web/` to a workspace just for this. (If shared harness data
ever becomes painful, the future move is a pnpm workspace with an
`@engrammic/harnesses` package; out of scope now.)

## Analytics

No web app has analytics today. Two separate concerns:

- **Reordering tiles from click data:** not now. Hardcode the six popular tiles by
  judgment; revisit the list by hand once there are real numbers. No data-driven
  reordering.
- **Capturing clicks for later:** add a one-line `track(event)` helper with event
  names defined now (`tile_click`, `deeplink_fired`, `copy_config`, `curl_copy`,
  `catalog_search`). It is a no-op until a provider is wired. Dropping in
  Plausible or PostHog later is then one change, and the events already fire.

Standing up the actual analytics provider is a separate follow-up, not part of this
build.

## docs quickstart changes

Once `join` owns install, `web/docs/content/docs/guides/quickstart.mdx` stops
duplicating the harness tabs. It slims to a one-line "Install at join.engrammic.ai"
pointer at the top, then keeps only the post-install content: verify, first use, the
proactive-memory snippet, and the link to the harness-integration deep dive. The
`HarnessTabs` and `VSCodeInstallButton` components built earlier move to `join` (as
the catalog's guts) or are removed from docs. Net: install lives in exactly one
place.

## Routing and the success-page re-scope

Decided: the post-signup AuthKit success page CTA changes to point at
`join.engrammic.ai` instead of `docs.engrammic.ai/quickstart`. The funnel becomes:

```
QR / link -> AuthKit signup -> success page -> join (install) -> docs
```

This is a deliberate change to the `2026-05-30-self-serve-org-provisioning.md` plan,
whose point 6 currently declares the success-page CTA out of scope and unchanged. It
must be updated: the CTA target in `api/routes/oauth.py` (around line 118) moves from
quickstart to join. Without this change the funnel would route signup ->
gutted-quickstart -> join, a dead hop. Flagging it explicitly because it spans two
plans and two repos.

## Hard dependency: self-serve org provisioning

Every install path ends in an MCP connect that triggers OAuth. For a brand-new
no-org user, `verify_session` (`auth/workos_client.py:61-63`) raises
`"missing organization_id"`. This affects the curl path too, not just inline signup,
and it does not self-heal (single-org auto-scoping has nothing to scope when there
are zero orgs). So `2026-05-30-self-serve-org-provisioning.md` is a hard gate for all
first-time users and must ship before (or with) this page, or new users cannot
complete first connect regardless of how they installed.

## Signup branch (deferred)

Whether `join` shows any auth UI is deferred. The install, catalog, and skills design
above is identical either way.

- **Pure install:** `join` has no auth UI; signup happens inline during the agent's
  first MCP connect via AuthKit.
- **Signup-aware:** `join` carries an optional "sign in" that opens the same AuthKit
  before the install hero.

Both depend on org provisioning for a brand-new user to actually connect. Resolve
this branch when we know whether org provisioning ships alongside.

## How the MCP OAuth flow works (reference)

For why inline signup round-trips back to the MCP client:

1. Agent connects with no token. `MCPOAuthChallengeMiddleware` returns 401 with a
   `WWW-Authenticate` header pointing at `/.well-known/oauth-protected-resource`
   (`mcp/auth.py:195-207`).
2. The MCP client does OAuth discovery and dynamic client registration, then opens a
   browser for the authorization-code flow.
3. That browser page is WorkOS AuthKit's hosted UI, which supports self-serve signup,
   not just login.
4. AuthKit redirects back with the auth code; the client exchanges it for a token,
   stores it, and reconnects with `Bearer`. The token returns to the same client that
   triggered the flow.

## Build order

1. Ship self-serve org provisioning (hard dependency; separate plan, already written).
2. Build `web/join`: app scaffold, `harnesses.ts` + drift guard, hero, catalog,
   install matrix, stubbed `track()`.
3. Add `deploy-join.yml` and the `join.engrammic.ai` domain mapping.
4. Slim `web/docs` quickstart to the post-install content and the join pointer.
5. Re-point the success-page CTA in `api/routes/oauth.py` and update the self-serve
   plan's point 6.

## Out of scope

- Data-driven tile reordering.
- Standing up an analytics provider (only the no-op `track()` stub is in scope).
- Converting `web/` to a workspace.
- The signup-vs-pure-install branch (deferred above).

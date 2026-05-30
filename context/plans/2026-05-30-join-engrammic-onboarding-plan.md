# join.engrammic.ai Onboarding Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `join.engrammic.ai` page (new `web/join` Next app) that takes a new user from "I want this" to "my agent has memory" via a two-column install hero plus a searchable catalog, then hands off to the docs, and make it the single place install lives.

**Architecture:** A fifth independent Next app under `web/` (siblings: docs, engrammic-site, blogs, showcase), deployed to its own Cloud Run service. UI uses shadcn primitives (matching `engrammic-site`) plus Cult UI components for polish, layered on framer-motion. All harness facts come from a local `harnesses.ts` superset of the docs one, kept honest against the Rust installer via the same drift guard. Pure logic (deep-link builders, catalog search, popular-set selection, analytics stub) is extracted into testable modules; visual components stay thin and are verified by build plus manual review.

**Tech Stack:** Next 16 / React 19 / Tailwind v4 / shadcn (base-ui backend) / Cult UI (cult-ui.com, via shadcn registry) / framer-motion / lucide-react / vitest (new, for pure logic) / pnpm (matches docs). Cult UI components are added with `pnpm dlx shadcn@latest add https://cult-ui.com/r/<name>.json`; the hero panel additionally needs `@paper-design/shaders-react`.

---

## Blocking prerequisite (not a task here)

Every install path ends in an MCP connect that triggers OAuth. For a brand-new
no-org user, `verify_session` (`context-service/src/context_service/auth/workos_client.py:61-63`)
raises `"missing organization_id"`, and it does not self-heal. So
`context/plans/2026-05-30-self-serve-org-provisioning.md` must ship before this page
is announced, or first-time users cannot complete first connect regardless of how
they installed. This plan does not implement org provisioning; it assumes it lands
first.

## File structure

New app `web/join/`:

- `package.json` — app manifest, scripts (`dev`, `build`, `start`, `lint`, `test`, `check:harnesses`).
- `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `components.json`, `.gitignore`, `Dockerfile` — scaffold mirroring `engrammic-site` / `docs`.
- `src/app/layout.tsx`, `src/app/globals.css`, `src/app/page.tsx` — root layout + home (hero).
- `src/app/catalog/page.tsx` — catalog page.
- `src/lib/harnesses.ts` — harness SSOT (superset of docs: adds `popular`, ordering).
- `src/lib/installer-harnesses.json` — golden fixture (copied from docs).
- `src/lib/analytics.ts` — typed `track()` no-op stub.
- `src/lib/catalog.ts` — pure `filterHarnesses` search.
- `src/components/install-hero.tsx` — client: two-column hero.
- `src/components/harness-tile.tsx` — client: one editor tile + inline config reveal.
- `src/components/curl-box.tsx` — client: curl/irm install box.
- `src/components/config-panel.tsx` — config path + snippet + copy + proactive-memory note.
- `src/components/copy-button.tsx` — client: copy-to-clipboard button.
- `src/components/catalog.tsx` — client: searchbar + all harness cards.
- `scripts/check-harnesses.mjs` — drift guard (copied from docs).
- `vitest.config.ts`, `src/lib/*.test.ts` — pure-logic tests.

Edits elsewhere:

- `web/.github/workflows/deploy-join.yml` — new deploy workflow.
- `web/docs/content/docs/guides/quickstart.mdx` — slim to post-install + join pointer.
- `context-service/src/context_service/api/routes/oauth.py:118` — success-page CTA → join.
- `context-service/context/plans/2026-05-30-self-serve-org-provisioning.md` — update point 6.

---

## Task 1: Scaffold the join app

**Files:**
- Create: `web/join/package.json`
- Create: `web/join/next.config.ts`
- Create: `web/join/tsconfig.json`
- Create: `web/join/postcss.config.mjs`
- Create: `web/join/components.json`
- Create: `web/join/.gitignore`
- Create: `web/join/Dockerfile`
- Create: `web/join/src/app/globals.css`
- Create: `web/join/src/app/layout.tsx`
- Create: `web/join/src/app/page.tsx`
- Create: `web/join/src/lib/utils.ts`

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "join",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "test": "vitest run",
    "check:harnesses": "node scripts/check-harnesses.mjs"
  },
  "dependencies": {
    "@base-ui/react": "^1.5.0",
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "framer-motion": "^12.40.0",
    "lucide-react": "^1.16.0",
    "next": "16.2.6",
    "react": "19.2.4",
    "react-dom": "19.2.4",
    "tailwind-merge": "^3.6.0",
    "tw-animate-css": "^1.4.0"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4",
    "@types/node": "^20",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "eslint": "^9",
    "eslint-config-next": "16.2.6",
    "shadcn": "^4.8.0",
    "tailwindcss": "^4",
    "typescript": "^5",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 2: Copy scaffold files from `engrammic-site`**

Copy these verbatim from `web/engrammic-site/` (they are app-agnostic), then we will not touch them further:

```bash
cd web
cp engrammic-site/tsconfig.json join/tsconfig.json
cp engrammic-site/postcss.config.mjs join/postcss.config.mjs
cp engrammic-site/next.config.ts join/next.config.ts
cp engrammic-site/components.json join/components.json
cp engrammic-site/.gitignore join/.gitignore
cp engrammic-site/src/lib/utils.ts join/src/lib/utils.ts
cp engrammic-site/src/app/globals.css join/src/app/globals.css
```

- [ ] **Step 3: Create `Dockerfile`** (mirror `web/docs/Dockerfile`)

```bash
cp web/docs/Dockerfile web/join/Dockerfile
```

`docs` uses pnpm, so the copied Dockerfile is already pnpm-based and needs no package-manager edit. Open it and confirm the `WORKDIR`, exposed port (Next default 3000), build step (`pnpm install` / `pnpm build`), and start command match a standalone Next 16 build. Adjust only if `docs/Dockerfile` hardcodes a docs-specific path.

- [ ] **Step 4: Create `src/app/layout.tsx`**

```tsx
import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Get Engrammic',
  description: 'Add persistent memory to your AI coding agent in two minutes.',
  metadataBase: new URL('https://join.engrammic.ai'),
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
```

- [ ] **Step 5: Create placeholder `src/app/page.tsx`**

```tsx
export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <h1 className="text-2xl font-semibold">join.engrammic.ai</h1>
    </main>
  );
}
```

- [ ] **Step 6: Install and build**

Run:
```bash
cd web/join && pnpm install && pnpm build
```
Expected: build succeeds, `.next/` produced, no type errors.

- [ ] **Step 7: Commit**

```bash
cd web && git checkout -b feat/join-onboarding-page
git add join
git commit -m "feat(join): scaffold join.engrammic.ai Next app"
```

---

## Task 2: Set up vitest

**Files:**
- Create: `web/join/vitest.config.ts`
- Create: `web/join/src/lib/smoke.test.ts`

- [ ] **Step 1: Write a failing smoke test**

```ts
// src/lib/smoke.test.ts
import { describe, it, expect } from 'vitest';

describe('vitest', () => {
  it('runs', () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 2: Create `vitest.config.ts`**

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
```

- [ ] **Step 3: Run the test**

Run: `cd web/join && pnpm test`
Expected: PASS (1 test).

- [ ] **Step 4: Delete the smoke test and commit**

```bash
cd web/join && rm src/lib/smoke.test.ts
git add vitest.config.ts package.json
git commit -m "test(join): add vitest for pure-logic tests"
```

---

## Task 3: Harness data SSOT

**Files:**
- Create: `web/join/src/lib/harnesses.ts`
- Test: `web/join/src/lib/harnesses.test.ts`

- [ ] **Step 1: Create `harnesses.ts`**

Copy `web/docs/src/lib/harnesses.ts` verbatim, then append the `popular` flag and
ordering exports below. The copied file already defines `ENDPOINT`, the `Harness`
interface, all snippet builders, `VSCODE_INSTALL_URL`, `CURSOR_INSTALL_URL` (rename
the docs `const CURSOR_INSTALL_URL` to `export const CURSOR_INSTALL_URL`), the
`harnesses` array, and `shippedHarnesses` / `plannedHarnesses`.

Add to the `Harness` interface (after `deepLink?`):

```ts
  /** Shown as a tile in the hero. The long tail lives only in the catalog. */
  popular?: boolean;
```

Append at the end of the file:

```ts
// The six tiles shown in the hero, in display order. Everything else is catalog-only.
export const POPULAR_IDS = ['vscode', 'cursor', 'claude', 'codex', 'gemini', 'windsurf'] as const;

export const popularHarnesses: Harness[] = POPULAR_IDS.map((id) => {
  const h = harnesses.find((x) => x.id === id);
  if (!h) throw new Error(`POPULAR_IDS references unknown harness '${id}'`);
  return h;
});
```

- [ ] **Step 2: Write the test**

```ts
// src/lib/harnesses.test.ts
import { describe, it, expect } from 'vitest';
import {
  ENDPOINT,
  harnesses,
  popularHarnesses,
  POPULAR_IDS,
  VSCODE_INSTALL_URL,
  CURSOR_INSTALL_URL,
} from './harnesses';

describe('harnesses data', () => {
  it('has 21 harnesses with unique ids', () => {
    expect(harnesses).toHaveLength(21);
    expect(new Set(harnesses.map((h) => h.id)).size).toBe(21);
  });

  it('exposes exactly the six popular tiles, in order', () => {
    expect(popularHarnesses.map((h) => h.id)).toEqual([...POPULAR_IDS]);
  });

  it('VS Code deep link decodes to the http config for the endpoint', () => {
    const config = new URL(VSCODE_INSTALL_URL).searchParams.get('config');
    expect(config).not.toBeNull();
    expect(JSON.parse(config as string)).toEqual({ type: 'http', url: ENDPOINT });
  });

  it('Cursor deep link decodes to the http config for the endpoint', () => {
    const config = new URL(CURSOR_INSTALL_URL).searchParams.get('config');
    expect(JSON.parse(config as string)).toEqual({ type: 'http', url: ENDPOINT });
  });

  it('only VS Code and Cursor carry deep links', () => {
    const withLinks = harnesses.filter((h) => h.deepLink).map((h) => h.id).sort();
    expect(withLinks).toEqual(['cursor', 'vscode']);
  });
});
```

- [ ] **Step 3: Run the test**

Run: `cd web/join && pnpm test harnesses`
Expected: PASS (5 tests). If the 21-count fails, the copied array drifted; re-copy from docs.

- [ ] **Step 4: Commit**

```bash
cd web/join && git add src/lib/harnesses.ts src/lib/harnesses.test.ts
git commit -m "feat(join): harness data SSOT with popular tiles"
```

---

## Task 4: Drift guard

**Files:**
- Create: `web/join/src/lib/installer-harnesses.json`
- Create: `web/join/scripts/check-harnesses.mjs`

- [ ] **Step 1: Copy the fixture and guard from docs**

```bash
cd web
cp docs/src/lib/installer-harnesses.json join/src/lib/installer-harnesses.json
cp docs/scripts/check-harnesses.mjs join/scripts/check-harnesses.mjs
```

The guard imports `../src/lib/harnesses.ts` relative to `scripts/`, which resolves
correctly in `join` as well. No edit needed.

- [ ] **Step 2: Run the guard**

Run: `cd web/join && pnpm check:harnesses`
Expected: `OK: 21 harnesses in sync with the installer.`

- [ ] **Step 3: Negative-check the guard (sanity)**

Temporarily add a fake harness id to `harnesses.ts`, run `pnpm check:harnesses`,
confirm it exits non-zero with a drift message, then revert.

- [ ] **Step 4: Commit**

```bash
cd web/join && git add src/lib/installer-harnesses.json scripts/check-harnesses.mjs
git commit -m "feat(join): drift guard against the installer manifest"
```

---

## Task 5: Analytics stub

**Files:**
- Create: `web/join/src/lib/analytics.ts`
- Test: `web/join/src/lib/analytics.test.ts`

- [ ] **Step 1: Write the test**

```ts
// src/lib/analytics.test.ts
import { describe, it, expect } from 'vitest';
import { track } from './analytics';

describe('track', () => {
  it('is a safe no-op for every event (server context)', () => {
    expect(() => track({ name: 'tile_click', harness: 'codex' })).not.toThrow();
    expect(() => track({ name: 'deeplink_fired', harness: 'vscode' })).not.toThrow();
    expect(() => track({ name: 'copy_config', harness: 'zed' })).not.toThrow();
    expect(() => track({ name: 'curl_copy', os: 'unix' })).not.toThrow();
    expect(() => track({ name: 'catalog_search', query: 'goose' })).not.toThrow();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web/join && pnpm test analytics`
Expected: FAIL with cannot find module `./analytics`.

- [ ] **Step 3: Create `analytics.ts`**

```ts
// Analytics stub. Defined now so call sites exist; a no-op until a provider
// (Plausible/PostHog) is wired. Adding the provider later is one change here.
export type TrackEvent =
  | { name: 'tile_click'; harness: string }
  | { name: 'deeplink_fired'; harness: string }
  | { name: 'copy_config'; harness: string }
  | { name: 'curl_copy'; os: 'unix' | 'windows' }
  | { name: 'catalog_search'; query: string };

export function track(event: TrackEvent): void {
  if (typeof window === 'undefined') return;
  // Future: window.plausible?.(event.name, { props: event });
  void event;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web/join && pnpm test analytics`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd web/join && git add src/lib/analytics.ts src/lib/analytics.test.ts
git commit -m "feat(join): typed analytics track() stub"
```

---

## Task 6: Catalog search logic

**Files:**
- Create: `web/join/src/lib/catalog.ts`
- Test: `web/join/src/lib/catalog.test.ts`

- [ ] **Step 1: Write the test**

```ts
// src/lib/catalog.test.ts
import { describe, it, expect } from 'vitest';
import { filterHarnesses } from './catalog';
import { harnesses } from './harnesses';

describe('filterHarnesses', () => {
  it('returns all harnesses for an empty query', () => {
    expect(filterHarnesses(harnesses, '')).toHaveLength(harnesses.length);
    expect(filterHarnesses(harnesses, '   ')).toHaveLength(harnesses.length);
  });

  it('matches on name, case-insensitively', () => {
    const r = filterHarnesses(harnesses, 'goose');
    expect(r.map((h) => h.id)).toEqual(['goose']);
  });

  it('matches on id', () => {
    const r = filterHarnesses(harnesses, 'vscode');
    expect(r.map((h) => h.id)).toContain('vscode');
  });

  it('returns empty for no match', () => {
    expect(filterHarnesses(harnesses, 'zzznope')).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web/join && pnpm test catalog`
Expected: FAIL, cannot find module `./catalog`.

- [ ] **Step 3: Create `catalog.ts`**

```ts
import type { Harness } from './harnesses';

export function filterHarnesses(all: Harness[], query: string): Harness[] {
  const q = query.trim().toLowerCase();
  if (!q) return all;
  return all.filter(
    (h) => h.name.toLowerCase().includes(q) || h.id.toLowerCase().includes(q),
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web/join && pnpm test catalog`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd web/join && git add src/lib/catalog.ts src/lib/catalog.test.ts
git commit -m "feat(join): catalog search filter"
```

---

## Task 7: Shared UI primitives (copy button + config panel)

**Files:**
- Create: `web/join/src/components/copy-button.tsx`
- Create: `web/join/src/components/config-panel.tsx`

- [ ] **Step 1: Create `copy-button.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

export function CopyButton({ text, onCopied }: { text: string; onCopied?: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    onCopied?.();
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy to clipboard"
      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
```

- [ ] **Step 2: Create `config-panel.tsx`**

This is the inline panel a non-deep-link tile reveals: path, snippet, copy, and the
honest "skills are separate" proactive-memory note.

```tsx
'use client';

import type { Harness } from '@/lib/harnesses';
import { CopyButton } from './copy-button';
import { track } from '@/lib/analytics';

export function ConfigPanel({ harness }: { harness: Harness }) {
  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/40 p-4 text-left">
      <p className="font-mono text-xs text-muted-foreground">{harness.configPath}</p>
      <div className="mt-2 flex items-start justify-between gap-3">
        <pre className="overflow-x-auto rounded-md bg-background p-3 text-xs leading-relaxed">
          <code>{harness.snippet}</code>
        </pre>
        <CopyButton
          text={harness.snippet}
          onCopied={() => track({ name: 'copy_config', harness: harness.id })}
        />
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        This connects the MCP server only. For proactive memory (skills), run the
        installer, or paste the snippet from the{' '}
        <a className="underline" href="https://docs.engrammic.ai/docs/guides/quickstart">
          docs
        </a>{' '}
        into your <code>AGENTS.md</code> / <code>CLAUDE.md</code>.
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web/join && pnpm exec tsc --noEmit`
Expected: no errors. (The `@/` alias is configured by the copied `tsconfig.json`.)

- [ ] **Step 4: Commit**

```bash
cd web/join && git add src/components/copy-button.tsx src/components/config-panel.tsx
git commit -m "feat(join): copy button and inline config panel"
```

---

## Task 8: Harness tile

**Files:**
- Create: `web/join/src/components/harness-tile.tsx`

- [ ] **Step 1: Create `harness-tile.tsx`**

A tile that either fires a deep link (VS Code/Cursor) or toggles the inline
`ConfigPanel`. Logo falls back to a letter monogram so the build never blocks on
missing brand SVGs.

```tsx
'use client';

import { useState } from 'react';
import type { Harness } from '@/lib/harnesses';
import { ConfigPanel } from './config-panel';
import { track } from '@/lib/analytics';

export function HarnessTile({ harness }: { harness: Harness }) {
  const [open, setOpen] = useState(false);

  function onClick() {
    track({ name: 'tile_click', harness: harness.id });
    if (harness.deepLink) {
      track({ name: 'deeplink_fired', harness: harness.id });
      window.location.href = harness.deepLink;
      return;
    }
    setOpen((v) => !v);
  }

  return (
    <div>
      <button
        type="button"
        onClick={onClick}
        aria-expanded={harness.deepLink ? undefined : open}
        className="flex w-full items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left transition-colors hover:border-foreground/30 hover:bg-muted/50"
      >
        <span className="flex size-8 items-center justify-center rounded-md bg-muted text-sm font-semibold">
          {harness.name.charAt(0)}
        </span>
        <span className="flex-1 text-sm font-medium">{harness.name}</span>
        <span className="text-xs text-muted-foreground">
          {harness.deepLink ? 'One-click ->' : open ? 'Hide' : 'Config'}
        </span>
      </button>
      {open && !harness.deepLink ? <ConfigPanel harness={harness} /> : null}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web/join && pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd web/join && git add src/components/harness-tile.tsx
git commit -m "feat(join): editor tile with deep-link or inline config"
```

---

## Task 9: Curl install box

**Files:**
- Create: `web/join/src/components/curl-box.tsx`

- [ ] **Step 1: Create `curl-box.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { CopyButton } from './copy-button';
import { track } from '@/lib/analytics';

const UNIX = 'curl -fsSL https://get.engrammic.ai | sh';
const WIN = 'irm https://get.engrammic.ai/install.ps1 | iex';

export function CurlBox() {
  const [os, setOs] = useState<'unix' | 'windows'>('unix');
  const cmd = os === 'unix' ? UNIX : WIN;

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-3 flex gap-2">
        {(['unix', 'windows'] as const).map((o) => (
          <button
            key={o}
            type="button"
            onClick={() => setOs(o)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              os === o ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted'
            }`}
          >
            {o === 'unix' ? 'macOS / Linux' : 'Windows'}
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-3 rounded-md bg-background p-3">
        <code className="overflow-x-auto font-mono text-sm">{cmd}</code>
        <CopyButton text={cmd} onCopied={() => track({ name: 'curl_copy', os })} />
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        Auto-detects your installed tools and sets up memory <strong>and</strong> skills.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck and commit**

```bash
cd web/join && pnpm exec tsc --noEmit && git add src/components/curl-box.tsx
git commit -m "feat(join): curl install box with OS toggle"
```

---

## Task 10: Install hero + home page

**Files:**
- Create: `web/join/src/components/install-hero.tsx`
- Modify: `web/join/src/app/page.tsx`

- [ ] **Step 1: Create `install-hero.tsx`**

```tsx
import Link from 'next/link';
import { popularHarnesses } from '@/lib/harnesses';
import { HarnessTile } from './harness-tile';
import { CurlBox } from './curl-box';

export function InstallHero() {
  return (
    <section className="mx-auto grid max-w-5xl gap-10 px-6 py-20 md:grid-cols-2">
      <div>
        <h2 className="text-lg font-semibold">Add to your editor</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          One click for VS Code and Cursor; copy-paste config for the rest.
        </p>
        <div className="mt-5 grid gap-2.5">
          {popularHarnesses.map((h) => (
            <HarnessTile key={h.id} harness={h} />
          ))}
        </div>
        <Link
          href="/catalog"
          className="mt-4 inline-block text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Couldn&apos;t find yours? Browse all 21 -&gt;
        </Link>
      </div>
      <div>
        <h2 className="text-lg font-semibold">Or install everywhere</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          One command, every tool you have.
        </p>
        <div className="mt-5">
          <CurlBox />
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Replace `page.tsx`**

```tsx
import Link from 'next/link';
import { InstallHero } from '@/components/install-hero';

export default function Home() {
  return (
    <main>
      <header className="mx-auto max-w-5xl px-6 pt-20 text-center">
        <h1 className="text-4xl font-semibold tracking-tight">Give your agent memory</h1>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground">
          Engrammic adds persistent, epistemic memory to your AI coding agent. Install
          in under two minutes.
        </p>
      </header>

      <InstallHero />

      <section className="mx-auto max-w-2xl px-6 pb-10 text-center">
        <h2 className="text-lg font-semibold">Verify it works</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Restart your tool, then ask your agent:{' '}
          <span className="font-medium text-foreground">
            &ldquo;What MCP tools do you have?&rdquo;
          </span>{' '}
          You should see <code>remember</code>, <code>recall</code>, <code>learn</code>,
          and more.
        </p>
      </section>

      <section className="mx-auto max-w-2xl px-6 pb-24 text-center">
        <Link
          href="https://docs.engrammic.ai/docs/guides/quickstart"
          className="inline-flex items-center rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          Read the docs -&gt;
        </Link>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Build and run the dev server**

Run: `cd web/join && pnpm build && pnpm dev`
Expected: build succeeds. Open `http://localhost:3000`:
- two-column hero renders with six tiles + curl box,
- clicking a non-deep-link tile (e.g. Codex) reveals the config panel with the TOML snippet,
- copy buttons work,
- "Browse all 21" links to `/catalog` (404 until Task 11, expected),
- "Read the docs" links out.

- [ ] **Step 4: Commit**

```bash
cd web/join && git add src/components/install-hero.tsx src/app/page.tsx
git commit -m "feat(join): install hero and home page"
```

---

## Task 11: Catalog page

**Files:**
- Create: `web/join/src/components/catalog.tsx`
- Create: `web/join/src/app/catalog/page.tsx`

- [ ] **Step 1: Create `catalog.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { harnesses } from '@/lib/harnesses';
import { filterHarnesses } from '@/lib/catalog';
import { ConfigPanel } from './config-panel';
import { track } from '@/lib/analytics';

export function Catalog() {
  const [query, setQuery] = useState('');
  const results = filterHarnesses(harnesses, query);

  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold">All supported tools</h1>
      <input
        type="search"
        placeholder="Search 21 tools..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          track({ name: 'catalog_search', query: e.target.value });
        }}
        className="mt-5 w-full rounded-lg border border-border bg-card px-4 py-2.5 text-sm outline-none focus:border-foreground/40"
      />
      <div className="mt-6 grid gap-3">
        {results.map((h) => (
          <div key={h.id} className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{h.name}</span>
              {h.deepLink ? (
                <a
                  href={h.deepLink}
                  onClick={() => track({ name: 'deeplink_fired', harness: h.id })}
                  className="rounded-md bg-foreground px-2.5 py-1 text-xs font-medium text-background"
                >
                  One-click install
                </a>
              ) : null}
            </div>
            <ConfigPanel harness={h} />
          </div>
        ))}
        {results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tool matches that search.</p>
        ) : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `catalog/page.tsx`**

```tsx
import { Catalog } from '@/components/catalog';

export const metadata = { title: 'All tools - Get Engrammic' };

export default function CatalogPage() {
  return (
    <main>
      <Catalog />
    </main>
  );
}
```

- [ ] **Step 3: Build and verify**

Run: `cd web/join && pnpm build && pnpm dev`
Expected: `/catalog` lists all 21 tools; typing "goose" narrows to Goose; VS Code and
Cursor cards show a one-click button; others show config only.

- [ ] **Step 4: Commit**

```bash
cd web/join && git add src/components/catalog.tsx src/app/catalog/page.tsx
git commit -m "feat(join): searchable catalog page"
```

---

## Task 12: Cult UI polish pass (enhancement)

**Files:**
- Modify: `web/join/src/components/curl-box.tsx`
- Modify: `web/join/src/components/install-hero.tsx`

This task is purely visual; the page already works without it. Pull specific Cult UI
components via the shadcn registry (commands verified against cult-ui.com docs) and
swap them in where they elevate. If a registry add fails, skip that swap; the plain
shadcn version stays. Component names: `hero-color-panel`, `texture-card`,
`texture-button` (confirm current paths at cult-ui.com/docs if any 404s).

- [ ] **Step 1: Add the Cult UI components**

Run (from `web/join`):
```bash
pnpm dlx shadcn@latest add https://cult-ui.com/r/texture-card.json
pnpm dlx shadcn@latest add https://cult-ui.com/r/texture-button.json
pnpm dlx shadcn@latest add https://cult-ui.com/r/hero-color-panel.json
```
The hero panel needs an extra dependency (the shadcn add may prompt for it; if not,
install it explicitly):
```bash
pnpm add @paper-design/shaders-react
```
These write to `src/components/ui/texture-card.tsx`, `.../texture-button.tsx`, and
`.../hero-color-panel.tsx`. Do not block the task on a single component that 404s.

- [ ] **Step 2: Wrap the curl box in a texture card and use the texture button for the CTA**

In `install-hero.tsx`, import `{ TextureCard }` from `@/components/ui/texture-card`
and wrap the right-column `<CurlBox />` in it. In `page.tsx`, replace the "Read the
docs" `<Link>` with the Cult UI `TextureButton` rendered as a link (`asChild` if the
component supports it, else wrap the `<Link href=...>` so the button styles apply).
Keep the existing `href` and every `track()` call intact.

- [ ] **Step 3 (optional): Use the hero color panel for the page header**

If `hero-color-panel` installed cleanly, replace the plain `<header>` in `page.tsx`
with the `HeroColorPanels*` composition (`HeroColorPanelsRoot` >
`HeroColorPanelsContainer` > `HeroColorPanelsContent` > `HeroColorPanelsHeading` /
`HeroColorPanelsDescription`), imported from `@/components/ui/hero-color-panel`,
keeping the same headline and subhead copy. Skip this step if the shader dependency or
component caused build issues; the plain header is an acceptable fallback.

- [ ] **Step 4: Build and eyeball**

Run: `cd web/join && pnpm build && pnpm dev`
Expected: build succeeds; hero reads more polished; all interactions still work
(tiles, copy, search, CTAs).

- [ ] **Step 5: Commit**

```bash
cd web/join && git add -A
git commit -m "feat(join): Cult UI polish on hero, curl card, and CTA"
```

---

## Task 13: Deploy workflow

**Files:**
- Create: `web/.github/workflows/deploy-join.yml`

- [ ] **Step 1: Create `deploy-join.yml`** (mirror `deploy-docs.yml`)

```yaml
name: Deploy Join

on:
  push:
    branches: [main]
    paths:
      - 'join/**'
  workflow_dispatch:

env:
  REGION: europe-north1
  PROJECT_ID: engrammic
  SERVICE_NAME: engrammic-join

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Deploy to Cloud Run
        working-directory: join
        run: |
          gcloud run deploy ${{ env.SERVICE_NAME }} \
            --source . \
            --region ${{ env.REGION }} \
            --project ${{ env.PROJECT_ID }} \
            --allow-unauthenticated \
            --max-instances 3 \
            --cpu-boost \
            --clear-base-image
```

- [ ] **Step 2: Validate the YAML**

Run: `cd web && python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy-join.yml')); print('valid')"`
Expected: `valid`.

- [ ] **Step 3: Manual infra note (not automatable here)**

After first deploy lands on `main`, map the domain (one-time, GCP Console or CLI):
```bash
gcloud run domain-mappings create --service engrammic-join \
  --domain join.engrammic.ai --region europe-north1 --project engrammic
```
Then add the DNS record GCP returns. Record this in the PR description.

- [ ] **Step 4: Commit**

```bash
cd web && git add .github/workflows/deploy-join.yml
git commit -m "ci(join): deploy join.engrammic.ai to Cloud Run"
```

---

## Task 14: Slim the docs quickstart

**Files:**
- Modify: `web/docs/content/docs/guides/quickstart.mdx`

- [ ] **Step 1: Replace the Install step with a join pointer**

In `quickstart.mdx`, replace the entire first `<Step>` (the "Install" step: the
macOS/Windows `<Tabs>`, the `<VSCodeInstallButton />`, the CLI install block, the
`<Callout>`, and the `<HarnessTabs />` "Manual Config" section, lines ~10-50) with:

```mdx
<Step>

## Install

Install Engrammic and connect your editor at{' '}
<a href="https://join.engrammic.ai">join.engrammic.ai</a> — one click for VS Code and
Cursor, a copy-paste config for every other tool, or one command that sets up all your
installed tools at once.

Once your tool is connected, come back here to verify and start using it.

</Step>
```

Keep the remaining `<Step>` blocks (Verify, First Use, Enable Proactive Memory) as-is.

- [ ] **Step 2: Remove now-unused imports/components**

If `quickstart.mdx` no longer references `HarnessTabs` or `VSCodeInstallButton`, that
is fine (they are global MDX components, not imports here). Leave
`web/docs/src/components/harness-tabs.tsx` and its `mdx.tsx` registration in place for
now (other pages or the catalog migration may use them); removing them is out of scope.

- [ ] **Step 3: Build docs and run its drift guard**

Run:
```bash
cd web/docs && pnpm build && pnpm check:harnesses
```
Expected: build succeeds; `OK: 21 harnesses in sync with the installer.`

- [ ] **Step 4: Commit**

```bash
cd web/docs && git add content/docs/guides/quickstart.mdx
git commit -m "docs(quickstart): defer install to join.engrammic.ai"
```

---

## Task 15: Re-point the success-page CTA

**Files:**
- Modify: `context-service/src/context_service/api/routes/oauth.py:118`
- Modify: `context-service/context/plans/2026-05-30-self-serve-org-provisioning.md`

Note: this is in the `context-service` repo, on a separate branch from the `web` work.

- [ ] **Step 1: Confirm no test pins the old URL**

Run: `cd context-service && grep -rn "guides/quickstart\|Continue to onboarding" src tests`
Expected: only the one hit in `oauth.py:118` (no test references it). If a test
appears, update it in this task.

- [ ] **Step 2: Edit the CTA**

In `oauth.py`, change line 118 from:
```python
        <a href="https://docs.engrammic.ai/docs/guides/quickstart" class="cta">Continue to onboarding guide</a>
```
to:
```python
        <a href="https://join.engrammic.ai" class="cta">Get started</a>
```

- [ ] **Step 3: Update the self-serve plan's point 6**

In `2026-05-30-self-serve-org-provisioning.md`, point 6 currently says the success
page CTA -> quickstart is out of scope and must not change. Replace that sentence with
a note that the CTA now targets `join.engrammic.ai` per the join onboarding plan, and
the change is implemented there.

- [ ] **Step 4: Run the checks**

Run: `cd context-service && just check`
Expected: ruff + mypy pass (this is an HTML-string edit; no logic change).

- [ ] **Step 5: Commit**

```bash
cd context-service && git checkout -b feat/join-success-cta
git add src/context_service/api/routes/oauth.py context/plans/2026-05-30-self-serve-org-provisioning.md
git commit -m "feat(oauth): point post-signup CTA at join.engrammic.ai"
```

---

## Final verification

- [ ] `cd web/join && pnpm test` — all pure-logic tests pass (run as `pnpm test`).
- [ ] `cd web/join && pnpm check:harnesses` — in sync with the installer.
- [ ] `cd web/join && pnpm build` — production build succeeds.
- [ ] `cd web/join && pnpm dev` — hero + catalog render; tiles deep-link or reveal
  config; copy works; search filters; docs CTA links out.
- [ ] `cd web/docs && pnpm build && pnpm check:harnesses` — docs build green, no drift.
- [ ] `cd context-service && just check` — green.
- [ ] Manual: open `VSCODE_INSTALL_URL` in a browser with VS Code installed; confirm it
  opens the add-MCP prompt for `engrammic` (the one real-click test for the deep link).
- [ ] Manual (post-deploy): `join.engrammic.ai` resolves and serves the page.

## Notes on testing philosophy

This is a marketing-grade page. The genuinely testable units (harness data integrity,
deep-link encoding, catalog search, analytics shape, installer drift) are covered by
vitest + the drift guard. The visual components are intentionally thin wrappers around
that logic and are verified by `next build` + manual review rather than brittle
snapshot/DOM tests, which would cost more than they protect here.

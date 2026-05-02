# Open-Source Strategy — Master Plan

Goal: Ship primitives + engine as open-source with manifesto and launch prep.

Spec: [context/specs/2026-05-02-open-source-strategy.md](../specs/2026-05-02-open-source-strategy.md)

## Workstreams

Three parallel workstreams, can progress independently:

| # | Workstream | Sub-plan | Owner | Status |
|---|------------|----------|-------|--------|
| 1 | Engine repo | [oss-engine.md](./oss-engine.md) | - | pending |
| 2 | Manifesto | [oss-manifesto.md](./oss-manifesto.md) | - | pending |
| 3 | Launch prep | [oss-launch-prep.md](./oss-launch-prep.md) | - | pending |

## Dependencies

```
primitives/ (exists) ─┬─► engine/ repo (W1)
                      │
                      └─► manifesto in primitives/docs/ (W2)

W1 + W2 ─► launch prep (W3) ─► launch day
```

W1 and W2 can run in parallel. W3 depends on both being mostly complete.

## Workstream Summaries

### W1: Engine Repo

Build `delta-prime/engine/` — a single-tenant SQLite-backed engine with basic MCP server.

Milestones:
1. Repo scaffold + Apache 2.0 license
2. SQLite store implementing primitives protocols
3. Basic MCP server (read/write tools)
4. CLI entry point (`python -m engine`)
5. Examples + quickstart

### W2: Manifesto

Write `primitives/docs/manifesto.md` — practitioner manifesto (~5-6 pages).

Milestones:
1. Outline validation
2. Draft sections 1-3 (hook, problem, layers)
3. Draft sections 4-5 (EAG in practice, getting started)
4. Draft section 6 (when you need more)
5. Review pass for tone (no AI slop, no buzzwords)

### W3: Launch Prep

Docs, landing page, distribution prep.

Milestones:
1. Repo hygiene (CONTRIBUTING.md, CODE_OF_CONDUCT, issue templates)
2. README updates (both repos)
3. Landing page with manifesto + waitlist
4. HN Show HN post draft
5. Social posts (Twitter/LinkedIn)

## Timing

Decision: lean toward after Silt design partner traction. Revisit after partner talks progress.

Sequence when ready:
1. W1 + W2 complete
2. W3 complete
3. Final review
4. Launch day

## Done Criteria

- [ ] engine/ repo exists with working MCP server
- [ ] manifesto in primitives/docs/, reviewed for tone
- [ ] both repos have CONTRIBUTING.md, CODE_OF_CONDUCT, issue templates
- [ ] landing page live with waitlist
- [ ] HN post drafted and approved
- [ ] all repos pushed public simultaneously

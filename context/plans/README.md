# Implementation Plans

Active implementation plans for context-service. Each plan lives in its own file named `<phase>-<description>.md`.

## Active plans

### v1-α — close paradigm gaps
- [v1a-claim-fact-promotion.md](./v1a-claim-fact-promotion.md) — wire `:Claim` → `:Fact` promotion via `primitives.eag.epistemology`; keep `:Finding` semantics intact.
- [v1a-edge-migration.md](./v1a-edge-migration.md) — migrate legacy `BELONGS_TO` edges to `MEMBER_OF`; drop dual-read; close stale audit TODOs.
- [v1a-validator-phase-b-finish.md](./v1a-validator-phase-b-finish.md) — split rejection metric into three counters; consolidate quality score in `BusinessRuleValidator`.
- [v1a-auth-toggle.md](./v1a-auth-toggle.md) — wire WorkOS auth behind an `AUTH_ENABLED` toggle; dev bypass with prod-guard.

### Background / design
- [eag-integration-audit.md](./eag-integration-audit.md) — port-day audit; some TODOs are addressed by v1-α plans above.
- [validator-refactor.md](./validator-refactor.md) — full 4-phase design; Phase A+B finishing in v1-α, C+D deferred.
- [meta-memory-roadmap.md](./meta-memory-roadmap.md) — phases 1–3 effectively shipped via `context_provenance`/`context_history`; phase 4 (reflection storage model) still notional.

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria

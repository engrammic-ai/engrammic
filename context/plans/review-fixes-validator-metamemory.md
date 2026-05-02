# Review Fixes: validator-cd + meta-memory-2-4

**Status:** COMPLETE — all findings resolved, both branches merge-ready.
**Date:** 2026-05-02
**Reviewer:** Sonnet adversarial review agent (post-implementation hostile review)
**Fixed:** 2026-05-02 via subagent-driven execution

---

## Branch: `phase-validator-cd`

**Commit:** `7b6e19c` — fix: validator-cd issues (C1-C3/H1-H2/L1 from review)
**Review:** APPROVED

### CRITICAL — FIXED

- **C1** — `list[Any]` changed to `list[Claim]` / `list[ProposedEdge]` with TYPE_CHECKING import
- **C2** — Removed `"citation"` from docstring (only `"business"` is ever set)
- **C3** — Bare asserts replaced with `if...raise RuntimeError`

### HIGH — FIXED

- **H1** — Enum recovery test already existed (`test_custodian_enum_recovery.py`)
- **H2** — `business: Any | None` changed to `BusinessRuleResult | None`

### LOW — FIXED

- **L1** — `claims_rejected >= 0` tightened to `== 1`

---

## Branch: `phase-meta-memory-2-4`

**Commits:**
- `7012562` — fix: critical meta-memory bugs (C4/C5/C6 from review)
- `ea8acbb` — fix: sort belief timeline chronologically after DESC query (C5 regression)
- `f442ea2` — fix: HIGH meta-memory issues (H3/H4/H5/H6 from review)
- `40a9607` — fix: LOW meta-memory issues (L3/L4 from review)

**Review:** APPROVED (after C5 regression fix)

### CRITICAL — FIXED

- **C4** — Already correct (`as_of.isoformat()` was in place)
- **C5** — Directed pattern + silo filter + DESC ordering + Python sort for chronological order
- **C6** — Added `_format_timestamp()` wrapper for response datetimes

### HIGH — FIXED

- **H3** — Already in codebase (MetaMemoryLabel mapped to AUDIT)
- **H4** — Docstring updated + TODO(v1.1) for semantic filtering
- **H5** — Added `first_belief` and `last_change` to summary
- **H6** — Promoted to `ContextService.belief_history()` method

### LOW — FIXED

- **L3** — `test_branching_supersession` already existed
- **L4** — `as_of` docstring updated to describe time-travel functionality

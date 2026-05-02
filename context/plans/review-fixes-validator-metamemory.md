# Review Fixes: validator-cd + meta-memory-2-4

**Status:** Blocked — review findings outstanding. Neither branch is merge-ready.
**Date:** 2026-05-02
**Reviewer:** Sonnet adversarial review agent (post-implementation hostile review)

Resume with: `superpowers:writing-plans` or `gsd` to create a fix plan, then execute.

---

## Branch: `phase-validator-cd`

### CRITICAL

**C1 — `pipeline.py:18-21` — `list[Any]` erases type safety**
`CitationStageResult.surviving_claims` and `.surviving_edges` are `list[Any]`. Should be `list[Claim]` and `list[ProposedEdge]` (use `TYPE_CHECKING` import to avoid circular import — same pattern as `FindingOutput`). Downstream `write_path.py` passes these into `_serialize_claims(claims: list[Claim])` — currently unchecked by mypy.

**C2 — `pipeline.py:26-34` — `"citation"` in `failed_at` is a lie**
Docstring documents `failed_at="citation"` as a valid value but no code path ever sets it. Only `"business"` is ever written. Either remove `"citation"` from the docstring/literal or implement the short-circuit. (Note: pre-refactor behavior is preserved — business validator handles all-claims-rejected — but the docstring creates a false API contract.)

**C3 — `write_path.py:240,262` — bare `assert` in production transaction path**
Two `assert` statements unwrap `pipeline_result.citation` and `pipeline_result.business`. Eliminated by `-O`, and raises uncaught `AssertionError` inside a Memgraph transaction. Replace with explicit `if ... is None: raise RuntimeError(...)` or restructure return type so fields are non-optional on success.

### HIGH

**H1 — No regression test for deleted `output_recovery.py` behavior**
The deletion assumes `model_validator(mode='before')` on the custodian output models handles the same Gemini failure modes (uppercase enum variants). No test verifies this. Add a test: construct `FastPassObservation` (or relevant output model) from a dict with uppercase enum strings, verify `model_validate` succeeds.

**H2 — `pipeline.py:35` — `business: Any` loses static checking**
`PipelineResult.business` typed `Any | None`. Should be `BusinessRuleResult | None`. `BusinessRuleResult` is not in a circular-import position — already imported at module level in `write_path.py`.

### LOW

**L1 — `test_validation_pipeline.py` — non-specific assertion**
`assert result.citation.claims_rejected >= 0` should be `== 1` (one claim mocked as rejected).

---

## Branch: `phase-meta-memory-2-4`

### CRITICAL

**C4 — `services/context.py:1052` — `datetime` vs ISO string comparison in Memgraph**
`temporal_query()` passes `as_of` as a raw Python `datetime` object. All write paths store `valid_from`/`valid_to` as ISO 8601 strings. Memgraph comparison will silently return no results or throw a type error at runtime.
Fix: `"as_of": as_of.isoformat()` in the params dict.

**C5 — `db/queries.py:587-599` — silo isolation gap + wrong LIMIT direction**
Two bugs:
1. Undirected `(start)-[:SUPERSEDES*0..20]-(related)` can traverse into foreign-silo nodes. Fix: use directed `->` and add silo filter on all traversed nodes, not just `related`.
2. `ORDER BY n.valid_from ASC` + `LIMIT $limit` drops the *newest* beliefs when chain > limit. Fix: `ORDER BY n.valid_from DESC LIMIT $limit` then reverse in Python, or fetch all and slice in `build_belief_timeline`.

**C6 — `services/context.py:1060-1072` — raw datetimes in MCP response**
`temporal_query()` returns raw datetimes in result dicts. These are not JSON-serializable — will raise `TypeError` when FastMCP serializes the response.
Fix: apply `_format_ts()` (already defined at line ~875 in same file) to `valid_from`, `valid_to`, `created_at` in each result dict.

### HIGH

**H3 — `primitives/labels.py:103+` — `MetaMemoryLabel` missing from `_LABEL_TO_LAYER`**
`layer_for_label("MetaObservation")` returns `None`. Add a loop for `MetaMemoryLabel` in the `_LABEL_TO_LAYER` population block. Requires deciding on a `PersistenceLayer` value (add `META_MEMORY = "meta_memory"` or map to `AUDIT`).
File: `../primitives/src/primitives/schema/labels.py`

**H4 — `services/context.py:1039` — `query` param silently ignored in temporal path**
`temporal_query()` ignores the search query and returns a full recency-sorted scan. This is a plan deviation — the Phase 2 spec shows semantic filtering. At minimum add a `# TODO` and document in the response that results are recency-ordered, not relevance-ranked. Tracked for v1.1 with the `context_snapshot` tool.

**H5 — `belief_history.py:43-57` — response missing `first_belief` and `last_change`**
Phase 3 spec defines a `summary` object with `total_versions`, `first_belief`, `last_change`, `confidence_trend`. Implementation drops `first_belief` and `last_change`. Add them: `first_belief = timeline[0].valid_from.isoformat() if timeline else None`, `last_change = timeline[-1].valid_from.isoformat() if timeline else None`.

**H6 — `belief_history.py:33` — direct `_memgraph` access bypasses protocols contract**
`get_belief_history(memgraph=ctx_svc._memgraph)` violates CLAUDE.md rule 8. Promote `get_belief_history` to a method on `ContextService` (like `temporal_query`), and call `ctx_svc.belief_history(...)` from the tool.

### LOW

**L3 — `test_belief_history.py` — branching supersession test missing**
Plan required `test_branching_supersession` (A superseded by both B and C). Not implemented.

**L4 — `context_query.py:178` — stale docstring**
`as_of` parameter description still says "not yet implemented at store level". Update it.

---

## Resume instructions

1. Check out each branch
2. Run `superpowers:writing-plans` with this file as the spec
3. Fix in order: CRITICALs first (C4/C5/C6 on meta-memory will cause runtime failures on any live data), then HIGHs
4. Re-run `just test && just check` on each branch
5. Run review agent again before merge

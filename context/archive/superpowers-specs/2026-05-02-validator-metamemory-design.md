# Design: Validator Phase C/D + Meta-Memory Phases 2-4

**Date:** 2026-05-02
**Status:** Approved — ready for implementation planning
**Tracks:** Custodian validator cleanup + Meta-Memory epistemic history

---

## Motivation

Three drivers: technical debt (validator), design partner demos (time-travel + belief history), differentiation story (meta-memory as moat). Sequenced so structural cleanup lands first and unblocks faster iteration on the feature work.

---

## Scope

Five work items in order:

| # | Item | Branch | Effort |
|---|------|--------|--------|
| 1 | Phase C cleanup — delete dead `output_recovery.py` code | `phase-validator-cd` | ~30 min |
| 2 | Phase D — `run_validation()` + `PipelineResult` | `phase-validator-cd` | ~half day |
| 3 | Meta-Memory Phase 4 finish — primitives schema formalization | `phase-meta-memory-2-4` | ~2 hrs |
| 4 | Meta-Memory Phase 2 — `as_of` on `context_lookup` | `phase-meta-memory-2-4` | ~1 day |
| 5 | Meta-Memory Phase 3 — `context_belief_history` tool | `phase-meta-memory-2-4` | ~1.5 days |

Items 1-2 are one branch. Items 3-5 are a second branch (can run in parallel once #1 is done).

---

## Item 1: Phase C cleanup

`output_recovery.py` is all dead code. `patch_agent_output_validators` became a no-op when enum-case fixups were moved to `model_validator(mode='before')` on the custodian output types. The recovery helpers (`recover_output`, `_recover_inner`, `_remap_dict`, `_make_recovering_validate_python`, `_make_recovering_validate_json`, `_in_recovery`) are unreachable.

**Changes:**
- Delete `src/context_service/custodian/output_recovery.py`
- Remove 3 lines in `agents.py`: the import + 3 `patch_agent_output_validators(...)` call sites

**Done criteria:** `just check` green, no references to `output_recovery` remain.

---

## Item 2: Phase D — ValidationPipeline (Option B)

**Decision rationale:** Protocol + injectable stages (Option A) is correct at N=5+ stages with divergent async patterns. At N=2 known validators for a small team, it adds complexity without benefit. The adversarial reviewer made the correct call: ordering becomes a runtime convention rather than enforced call sequence, mock complexity outweighs the testability gain, and a clean function gives the same structured return type.

**New `PipelineResult` dataclass** in `custodian/pipeline.py`:

```python
@dataclass
class StageResult:
    passed: bool
    failed_at: str | None = None
    rejection_reason: str | None = None
    offending_ids: list[str] = field(default_factory=list)
    surviving_claims: list[Any] | None = None
    surviving_edges: list[Any] | None = None

@dataclass
class PipelineResult:
    passed: bool
    failed_at: str | None = None       # "citation" | "business" | None
    citation: StageResult | None = None
    business: StageResult | None = None
```

**New `run_validation()` function** in `custodian/pipeline.py`:

`CitationValidator` exposes `validate_finding(finding, ...)` (line 163 of `validators.py`).
`BusinessRuleValidator` exposes `evaluate(...)` (line 56 of `business_rules.py`).
Read both files before writing this function — match their actual signatures.

```python
async def run_validation(
    finding: FindingOutput,
    citation_validator: CitationValidator,
    business_validator: BusinessRuleValidator,
    # pass through whatever args the existing methods require
) -> PipelineResult:
    citation_result = await citation_validator.validate_finding(finding, ...)
    if not citation_result.passed:
        return PipelineResult(passed=False, failed_at="citation", citation=citation_result)
    business_result = business_validator.evaluate(finding, ...)
    if not business_result.passed:
        return PipelineResult(passed=False, failed_at="business", citation=citation_result, business=business_result)
    return PipelineResult(passed=True, citation=citation_result, business=business_result)
```

**`write_path.py` change:** Replace inline validator calls with `run_validation(...)`. Return or act on `PipelineResult`.

**Migration path to Option A:** When a third stage is needed, add a named param to `run_validation` and a line in the function body. If N reaches 5+, migrate to Protocol + injectable stages at that point.

**Done criteria:** `just check` green, `write_path.py` delegates to `run_validation`, unit tests cover pass / citation-fail / business-fail paths without live Memgraph.

---

## Item 3: Meta-Memory Phase 4 schema finish

Tools `context_reflect` and `context_get_reflections` are live. Missing: schema formalization in `primitives`.

**Changes:**
- Add `MetaObservation` to `primitives.schema.labels` (new `MetaMemoryLabel` enum or append to existing)
- Add `ABOUT` to `CITEEdgeType` in primitives
- Add Memgraph indexes on `:MetaObservation(id)`, `:MetaObservation(silo_id)` in `db/indexes.py`
- Add `ObservationType` StrEnum to `custodian/models.py` or a new `models/meta_memory.py`

**Done criteria:** `just check` green, reflection round-trip integration test passes (create + retrieve by node), silo isolation respected.

---

## Item 4: Meta-Memory Phase 2 — Time-travel (`as_of` on `context_lookup`)

**Decision rationale:** Extending `context_query` (Option A) has a correctness bug — Qdrant stores present-tense embeddings so temporal filtering in Memgraph + vector ranking in Qdrant produces split-brain results. `context_lookup` is Memgraph-only, making the temporal filter clean and unambiguous. `context_snapshot` (Option C) is the right long-term target but is more surface area; ship `context_lookup` extension now, plan `context_snapshot` for v1.1.

**`context_lookup` extension:**

```python
async def context_lookup(
    silo_id: str,
    query: str,
    as_of: datetime | None = None,   # new param
    limit: int = 10,
) -> LookupResult: ...
```

**Cypher change** (applied when `as_of` is set):
```cypher
WHERE n.silo_id = $silo_id
  AND n.valid_from <= $as_of
  AND (n.valid_to IS NULL OR n.valid_to > $as_of)
```

**Response:** Include `as_of` in response and a `"historical_query": true` flag when set, so agents know they're reading a point-in-time snapshot.

**Edge cases:**
- `as_of` in future: return current state + warning
- `as_of` before any data: return empty + note
- `null valid_to`: treated as still valid (infinity)
- `superseded_by` pointer included in each result node

**Done criteria:** `context_lookup` accepts `as_of`, temporal filter applied correctly, 4 test cases (before/after supersession, boundary, future date), `just check` green.

---

## Item 5: Meta-Memory Phase 3 — Belief History

**New MCP tool:** `context_belief_history(subject: str, limit: int = 20) -> BeliefHistory`

**Subject identification strategy:** Start with supersession chains (follow SUPERSEDES edges from a seed node). Semantic grouping (embedding similarity) deferred — adds complexity without clear ROI for v1-β.

**Cypher:**
```cypher
MATCH path = (n:Fact)-[:SUPERSEDES*0..10]-(related:Fact)
WHERE n.id = $start_id AND n.silo_id = $silo_id
WITH collect(DISTINCT related) + [n] AS all_nodes
UNWIND all_nodes AS node
RETURN DISTINCT node
ORDER BY node.valid_from ASC
```

**Response schema:**
```python
@dataclass
class BeliefState:
    node_id: str
    content: str
    confidence: float
    valid_from: datetime
    valid_to: datetime | None
    status: Literal["current", "superseded"]
    superseded_by: str | None

@dataclass
class BeliefHistory:
    subject: str
    timeline: list[BeliefState]
    total_versions: int
    confidence_trend: Literal["increasing", "decreasing", "stable", "volatile"]
```

**Confidence trend:** Compare first and last confidence in chain; "volatile" if max-min delta > 0.2 with non-monotonic movement.

**Edge cases:** Single fact (no history) returns single-item timeline. Branching supersession returns all branches. Cycle guard via visited set.

**New code:** `mcp/tools/belief_history.py`, `engine/history.py`, query `GET_SUPERSESSION_CHAIN` in `db/queries.py`.

**Done criteria:** Tool registered in MCP server, linear chain test + single-fact test + branching test pass, `just check` green.

---

## Cross-cutting constraints

- All code via `uv run`, mypy strict, ruff `E,F,I,UP,B,SIM,ARG` — `just check` must pass before merge
- No commits to `main` — use the two branches above
- Multi-tenancy: every new query takes `silo_id` and filters by it
- `primitives` changes coordinate with `../primitives` editable source — changes land immediately

---

## What this does not cover

- `context_snapshot` dedicated tool (v1.1 target after `context_lookup` as_of ships)
- ValidationPipeline Protocol + injectable stages (revisit when N > 2 stages)
- Semantic subject grouping for belief history (deferred — embedding similarity adds cost)
- Meta-Memory Phase 2 vector path (needs versioned embeddings in Qdrant, separate project)

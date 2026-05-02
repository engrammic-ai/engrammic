# Custodian Validator Refactor — Design Doc

**Status:** Phase A+B complete (2026-04-28). Phase C+D deferred — see below.
**Date:** 2026-04-26  
**Scope:** Research and architecture only; no implementation changes.

---

## 1. Current State

### What Exists

The custodian validation surface spans five files with overlapping responsibilities:

| File | Role | Lines |
|------|------|-------|
| `validators.py` | Citation checks (existence, silo membership, tool-seen set) | ~380 |
| `quality.py` | Quality score formula (coverage-weighted, pure function) | ~54 |
| `models.py` | Structural Pydantic validation (`extra="forbid"`, field validators, model validators) | ~262 |
| `output_recovery.py` | LLM mis-shape recovery — wraps pydantic-ai's `PluggableSchemaValidator` in-place | ~229 |
| `promotion.py` | Business rule: draft → published status transition, quality threshold gate | ~296 |

### What Works Well

- **`CitationValidator`** is cleanly separated from I/O: it takes a `MemgraphClient`, runs one batched Cypher query for the whole finding, and evaluates the rest in pure Python. The `validate_finding` batching optimization (single DB round-trip for all claims + edges) is correct and should be preserved.
- **`models.py` `extra="forbid"`** is a good first line of defence; hallucinated extra fields are caught at deserialization before any business logic runs.
- **`output_recovery.py`** re-entrancy guard via `ContextVar` is the right mechanism; it cleanly prevents infinite recursion through pydantic-ai's `PluggableSchemaValidator` monkey-patch.
- **`quality.py`** is a pure function with no side effects. Simple, testable, correct.

### What Is Messy

**1. Duplicate confidence + schema checks.**  
`ProposedEdge.validate_all` in `models.py` enforces `confidence >= 0.7` and 9-vocab schema membership at construction time. `CitationValidator._pre_check_edge` repeats those exact same checks at validation time with the comment "defensively re-runs the schema + confidence checks." This is belt-and-suspenders by necessity (the validator has to handle edges built outside the model), but there is no explicit contract stating which path is authoritative. The duplication is invisible to a reader.

**2. `CitationRejectionReason` carries non-citation reasons.**  
`SCHEMA_VIOLATION` and `LOW_CONFIDENCE` are not citation rejection reasons — they are structural/business-rule failures. Embedding them in `CitationRejectionReason` blurs the layer boundary and means the metric label `custodian_claim_rejections` fires for non-citation events.

**3. `output_recovery.py` is a monkey-patch on a pydantic-ai internal.**  
`patch_agent_output_validators` mutates `agent._output_toolset.processors[*].validator` in-place, reaching into pydantic-ai's private API. The `_remap_dict` heuristic (enum case fixup only) is documented as observation-driven but has no test coverage for the "no scalar-to-list coercion" policy. If pydantic-ai changes `PluggableSchemaValidator`'s attribute layout, the patch silently no-ops.

**4. Promotion business rules are split across two files.**  
`promotion.py` owns the draft → published transition and quality threshold filtering, but `write_path.py` owns the all-claims-rejected skip policy and scores findings via `quality_score`. The promotion eligibility logic is therefore spread: threshold checked in `plan_promotion`, score computed in `write_visit`, and the skip-if-zero-claims guard lives between them with no shared abstraction.

**5. No formal pipeline stage contract.**  
Validation currently happens at three implicit stages: deserialization (Pydantic), pre-write (CitationValidator), and post-write (promotion). There is no named abstraction — no `ValidationStage`, `ValidatorPipeline`, or equivalent — so adding a new check requires deciding ad-hoc where it belongs, and there is no way to run the full pipeline in tests without wiring up a live Memgraph client.

---

## 2. External Patterns

### 2.1 Guardrails AI — Layered Guard Architecture

Guardrails decomposes validation into discrete **Guards** (composable validators) applied in a defined order. The canonical pipeline is:

```
Input Screen → Dialog Control → LLM Generate → Output Validate → Business Rules
```

Each guard has: an `on_fail` policy (no-op / filter / fix / raise), a latency budget, and is independently swappable. The key insight for us: **output validation and business rules are separate guards even when they share data**, so a schema violation does not trigger a business-rule metric.

**What to borrow:** the explicit layer contract + `on_fail` enum per stage.

### 2.2 Instructor — Re-ask Loop on Pydantic Failure

Instructor wraps the LLM client; when `model_validate` raises `ValidationError`, it serialises the error as feedback and re-sends it to the LLM (configurable `max_retries`). This is the "self-correcting" pattern: the LLM author of the bad output is the best agent to fix it, not a deterministic remapper.

Instructor also distinguishes **semantic validation** (field-level `@field_validator` that returns a detailed `Literal` error reason that the LLM can interpret) from structural validation (schema shape). Both trigger the re-ask loop.

**What to borrow:** the re-ask loop as a principled alternative to `output_recovery.py`'s monkey-patch approach. The monkey-patch is a pragmatic workaround; re-ask via pydantic-ai's `result_retries` setting is the framework-native solution.

### 2.3 LangGraph — Retry Node with Error Context

LangGraph's self-correcting pattern wraps extraction in a graph node that catches `ValidationError`, injects the error detail into state, and routes to a correction node before looping back. The conditional edge (`valid → continue`, `invalid → correct`) makes the retry explicit and observable in traces.

The key distinction from Instructor: LangGraph's correction node can call tools (look up additional context), while Instructor's re-ask is prompt-only. For our case (citation existence requires a DB lookup), the graph-node approach maps better — the "correction" step would be telling the Custodian which node IDs it hallucinated.

**What to borrow:** the explicit routing-with-reason pattern; a rejected claim should carry a structured reason that could be fed back to the agent in a future retry design.

### 2.4 CrewAI — Task Guardrails as `(bool, result | error_msg)` Callbacks

CrewAI task guardrails are functions returning `(True, result)` or `(False, "error message")`. They run after an agent completes a task, before the output is passed downstream. The error message is returned to the agent for a corrected retry (`guardrail_max_retries`).

The pattern is lightweight but explicit: guardrails are attached to tasks (not to the LLM call), so they compose across heterogeneous backends.

**What to borrow:** the `(accepted: bool, reason: str | None)` return shape as a uniform interface for all validator stages.

### 2.5 AutoGen — Evaluator-Optimizer Separation of Concerns

AutoGen's `AgentEval` pattern uses three discrete agents: `CriticAgent` (generates evaluation criteria), `QuantifierAgent` (scores against criteria), `VerifierAgent` (confirms correctness). The key principle: **critique generation, scoring, and verification are separate roles** — a single monolith "validator" inevitably conflates them.

Applied to the custodian: quality scoring (`quality.py`) and citation validation (`validators.py`) are already separate by accident; the refactor should make that separation intentional and extend it to recovery and business rules.

**What to borrow:** explicit role separation + the insight that scoring (quantification) is distinct from accept/reject (verification).

---

## 3. Proposed Architecture

### 3.1 Four-Layer Pipeline

```
Stage 0: Structural    — Pydantic schema + extra="forbid" (already in models.py, no change)
Stage 1: Recovery      — mis-shape repair before citation checks
Stage 2: Citation      — existence + silo + tool-seen (CitationValidator, refactored)
Stage 3: Business      — confidence gate, quality gate, promotion threshold
```

Each stage has a uniform interface:

```python
class ValidationStage(Protocol):
    async def validate(self, finding: FindingOutput, ctx: ValidationContext) -> StageResult: ...

@dataclass
class StageResult:
    accepted: bool
    rejection_reason: str | None = None
    offending_ids: list[str] = field(default_factory=list)
    detail: str | None = None
    # Surviving claims/edges after filter (stages may filter without rejecting whole finding)
    surviving_claims: list[Claim] | None = None
    surviving_edges: list[ProposedEdge] | None = None
```

`ValidationContext` carries: `silo_id`, `seen_node_ids`, `cluster_size`, `org_id`.

The pipeline runner collects per-stage results and emits a single `PipelineResult` with pass/fail, per-stage metrics labels, and the final surviving claims/edges for `write_path.py` to commit.

### 3.2 Stage Boundary Clarifications

**Stage 0 (Structural — stays in models.py):**  
- `extra="forbid"` on all Pydantic models  
- `must_have_primary` on `Claim`  
- `validate_all` on `ProposedEdge` (confidence + 9-vocab schema)  
- `validate_scope` on `FindingOutput`  

Stage 0 fires at deserialization and has no DB dependency. No change needed.

**Stage 1 (Recovery — replaces output_recovery.py monkey-patch):**  
Two options:
- A: Keep the `PluggableSchemaValidator` patch but document the private API dependency explicitly and add a smoke-test that detects when the patch has silently no-opped.
- B (preferred): Migrate to pydantic-ai's `result_retries` parameter, which is the framework-native re-ask mechanism. The `_remap_dict` enum-case fixup can be a pydantic `model_validator(mode='before')` that runs before the first validation attempt, eliminating the need for recovery entirely in most cases.

Option B removes the private-API dependency and makes the recovery path observable in pydantic-ai's run traces.

**Stage 2 (Citation — refactor CitationValidator):**  
- Extract `CitationRejectionReason.SCHEMA_VIOLATION` and `CitationRejectionReason.LOW_CONFIDENCE` into a separate `StructuralRejectionReason` enum (or move them to Stage 0). The `citationRejectionReason` enum should only contain citation-specific reasons: `HALLUCINATED_NODE_ID`, `INVALID_CITATION`, `CROSS_TENANT`, `CROSS_SILO`.
- `_pre_check_edge` should be removed or become a defensive no-op that only fires when edges arrive from a path that skipped model validation. Document this contract explicitly.
- The batched `validate_finding` method and the single-Cypher-round-trip optimization stay unchanged.

**Stage 3 (Business Rules — new explicit layer):**  
Currently split between `write_path.py` (all-claims-rejected skip + quality scoring) and `promotion.py` (quality threshold gate). Consolidate into a `BusinessRuleValidator` that:
- checks all-claims-rejected (skip guard)
- computes and gates on quality score  
- checks promotion eligibility threshold  

`write_path.py` calls `CitationValidator` and `BusinessRuleValidator` in sequence; it does not embed business logic.

### 3.3 Rejection Reason Taxonomy (revised)

```
StructuralRejectionReason     — Stage 0 (Pydantic, no DB)
  SCHEMA_VIOLATION
  LOW_CONFIDENCE
  MISSING_PRIMARY_CITATION
  SCOPE_MISMATCH

CitationRejectionReason       — Stage 2 (needs DB)
  HALLUCINATED_NODE_ID
  INVALID_CITATION
  CROSS_TENANT
  CROSS_SILO

BusinessRuleRejectionReason   — Stage 3 (pure, needs quality_score)
  ALL_CLAIMS_REJECTED
  BELOW_QUALITY_THRESHOLD
  BELOW_PROMOTION_THRESHOLD
```

Each reason enum maps to a specific Prometheus label prefix: `custodian_structural_rejections`, `custodian_citation_rejections`, `custodian_business_rejections`. This removes the current metric pollution where schema violations fire the `custodian_claim_rejections` counter.

### 3.4 Component Map (post-refactor)

```
models.py            — Stage 0 structural validators (no change in structure, minor enum moves)
recovery.py          — Stage 1: model_validator(mode='before') enum fixup only; remove monkey-patch
validators.py        — Stage 2: CitationValidator (batched DB lookup, citation-only reasons)
business_rules.py    — Stage 3: BusinessRuleValidator (quality score, skip guard, promotion gate)
quality.py           — Pure function, no change; called from BusinessRuleValidator
pipeline.py          — NEW: ValidationPipeline assembles stages, runs in order, emits PipelineResult
write_path.py        — Delegates entirely to ValidationPipeline; removes inline business logic
```

---

## 4. Migration Path

### Phase A — Enum cleanup (no behavior change, lowest risk)

Status: ✓ Complete (2026-04-26 in port commit, refined 2026-04-28).

1. Add `StructuralRejectionReason` enum in `models.py`.
2. Move `SCHEMA_VIOLATION` and `LOW_CONFIDENCE` from `CitationRejectionReason` to `StructuralRejectionReason`.
3. Update `_pre_check_edge` to use `StructuralRejectionReason`; update metric labels.
4. All existing tests pass with updated metric label assertions.

### Phase B — Business rule isolation

Status: ✓ Complete (2026-04-28 via phase-validator-b-finish).

1. Create `business_rules.py` with `BusinessRuleValidator`.
2. Move all-claims-rejected skip logic from `write_path.py` into `BusinessRuleValidator`.
3. Move quality threshold gate from `promotion.py` into `BusinessRuleValidator` (keep `promotion.py` for the DB writes, remove threshold logic).
4. `write_path.py` calls `BusinessRuleValidator` explicitly.

### Phase C — Recovery migration (highest risk, do last)

Status: Deferred — output_recovery.py monkey-patch is working in production; pydantic-ai private-API migration carries real risk and no current pain.
1. Add a `model_validator(mode='before')` to the affected output types that applies the enum-case fixup from `_remap_dict`. This is pure Pydantic with no private-API access.
2. Add a smoke-test: construct a pydantic-ai Agent with the custodian output type, intentionally send a malformed enum variant, verify it recovers.
3. If pydantic-ai `result_retries` is viable (requires benchmarking latency impact), remove `patch_agent_output_validators` entirely. If not, keep the monkey-patch but add the no-op detection test.

### Phase D — `ValidationPipeline` (optional, for testability)

Status: Deferred — testability gain is real but no concrete pain point yet; revisit when adding a fourth validation stage.

1. Create `pipeline.py` with a `ValidationPipeline` class.
2. Each stage is injected (enables unit testing without DB). 
3. `write_path.py` takes a `ValidationPipeline` instead of a raw `CitationValidator`.

Phase D is the highest-leverage change for testability but also the largest refactor surface. Do only after A + B are stable.

---

## 5. Open Questions

**Q1: Should `_pre_check_edge` be removed or kept as a defensive layer?**  
Currently the code comment says "defensively re-runs checks" for edges arriving outside the model validation path. It is unclear whether such a path actually exists in production. If edges always arrive from `ProposedEdge.model_validate`, Stage 0 already covers confidence + schema and `_pre_check_edge` is dead code. If there is a path that bypasses model validation (e.g., raw dict from a future streaming parser), `_pre_check_edge` is load-bearing. Audit the call graph before removing.

**Q2: Is the `output_recovery.py` monkey-patch still triggering in practice?**  
The log line `custodian.{label}: recovered malformed output via output_recovery` should be observable in Grafana/Loki. If the recovery rate is near zero post-Gemini-mode changes, Phase C's migration risk drops significantly and Option B (remove monkey-patch) becomes straightforward. Check the logs before committing to a recovery strategy.

**Q3: Should `quality.py`'s formula weights be config-driven?**  
The current weights (density 0.25, coverage 0.30, relational 0.15, primary_ratio 0.20, summary_density 0.10) are hardcoded. If the Custodian's output distribution changes significantly post-EAG migration, retuning requires a code change. Moving weights to `CustodianSettings` would allow A/B testing without a deploy. Low priority for the refactor but worth noting.

**Q4: What is the interaction between `ConsensusPromotion` and `BusinessRuleValidator`?**  
`consensus_promotion.py` creates `:Finding` nodes directly from `:Commitment` nodes, bypassing the `WritePath` and therefore all validators. This is intentional (EAG-path findings have a different provenance), but it means the quality score and business-rule gates never fire for consensus-promoted findings. The refactor should explicitly document this bypass rather than accidentally closing it.

---

## 6. Decision Record

| Decision | Chosen | Rejected | Reason |
|----------|--------|----------|--------|
| Recovery mechanism | Deferred to post-v1-α | Keep monkey-patch as-is | Private-API dependency; pydantic-ai layout can change silently |
| Rejection enum split | Three separate enums (Structural / Citation / Business) | Extend existing `CitationRejectionReason` | Metric label pollution; layer boundary violation |
| Pipeline abstraction | Deferred to post-v1-α | Ad-hoc calls in `write_path.py` | Testability: unit tests need injectable stages without live Memgraph |
| `_pre_check_edge` fate | Audit first (Q1); remove if dead, document if live | Remove immediately | Unknown if code path that bypasses model validation exists |
| Quality weights | Stay hardcoded for now | Move to `CustodianSettings` | Low priority; premature if weights haven't needed tuning post-ship |

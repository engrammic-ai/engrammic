# Defensibility Sprint (Thu Jun 11 - Mon Jun 15)

Status: ACTIVE
Deadline: Monday 2026-06-15 (Claude Code availability window)
Source analysis: `context/brainstorm/2026-06-11-defensibility-and-avenues.md`
Engrammic: durable memories tagged `sprint-jun11`, commitment `0cbcf15c-6e85-4d90-964e-95744cef34ee`

## Decision

Stay the course on epistemic memory. No pivot to harness engineering, token/compression infra, or standalone guardrails. Adjacent moves (knowledge-ops KB audits, vertical regulated agents) are post-round expansions, not pivots.

Rationale in one line: the mechanics are copyable in 4-6 weeks, so defensibility comes from proof (benchmark + referee seat), data gravity (audited corpora), and a landed lighthouse customer (Verda) - none of which a pivot accelerates.

## The central bet (read this first)

The entire package rests on one unmeasured empirical claim: that once the read-path leak is fixed, Engrammic actually WINS the epistemic slices (supersession, contradiction, abstention) against mem0/Zep/RAG. Everything else - benchmark, audit credibility, Verda demo, pitch - is execution on top of that bet. If the in-house numbers do not show the win, stop and reassess before publishing anything (this is the first kill criterion below, promoted per the 2026-06-11 Opus audit).

## Priority order (if time runs short)

read-path fix > retrieval floor > epistemic-slice benchmark > tokens metric > audit tool scaffold > pitch fixes

Honest Monday floor (Opus audit): step 1 complete + step 3 scaffolded. Step 1 alone is realistically 1.5-2 focused days (7-task TDD plan against mypy strict, plus mandatory patching of existing tests). Step 2 is the unbounded item and the historical drift risk (it ate the last named week) - hard-cap it at 1 day; if the floor is not cleared in that day, ship the benchmark with a floor-honest disclaimer instead of continuing to chase it. Steps 1-3 ALL complete by Monday is the stretch case, not the plan.

Research grounding for steps 1-3: `context/review/2026-06-11-retrieval-fusion-compression-research.md` (score-fusion methods; compression/efficiency frontier numbers; borrow list incl. adaptive-k, confidence-gated content tiering, tokens-per-correct-answer instrumentation, token-budget sweep, empty LongMemEval-V2 leaderboard).

## Steps

### 1. Make epistemics load-bearing at read time (do first, ~days 1-2) - DONE

Implementation plan: `context/plans/2026-06-11-step1-read-path-epistemic-fusion.md` (Opus-reviewed: EXECUTE WITH EDITS, edits applied).

**Completed 2026-06-11:** EpistemicFusionConfig, pure fusion module, floor basis change, superseded_by field, context_query wiring, env docs. Branch: `feat/read-path-epistemic-fusion`.

PREREQUISITE (half-day, hard-capped): `context/plans/2026-06-11-epistemic-hygiene-prefix.md` Tier 1 - fixes the falsy-zero confidence bug (`or 1.0` maps confidence 0.0 to full trust at services/context.py:806/816/854/1491) that would feed fusion corrupted values, plus formula_version stamping. Tier 2 of that plan is parallel-safe subagent work; Tier 3 is the post-benchmark convergence backlog from the architecture critique - it does NOT enter this sprint.

The moat audit found the read-path leak: confidence, corroboration, and staleness multipliers are computed in recall scoring, then the reranker score overwrites them (`context_query.py:210-213`). Unresolved contradictions are returned ranked normally. Evidence enforcement defaults off.

- Fuse rerank score with epistemic multipliers instead of replacing them
- Demote or filter unresolved contradictions in recall results
- Surface supersession/provenance metadata in recall output
- Populate `ConfidenceBreakdown` (currently always None)
- Add a hard evidence-enforcement mode (`enforce=True` path actually rejects)

This is moat repair, benchmark prerequisite, and Verda demo prerequisite in one.

### 2. Retrieval-accuracy floor (timeboxed, parallel)

Get LongMemEval above the basic-RAG baseline (42.8%) so the published harness is not self-incriminating. Then STOP. The Jun 3 court verdict explicitly said not to compete on retrieval accuracy; the two active 2026-06-09 LongMemEval plans were drifting there.

### 3. Epistemic-slice benchmark (the Antler artifact, ~days 2-4)

Repoint the harness at the slices the moat doc specified:

- knowledge_update / supersession
- contradiction_resolution
- abstention

Engrammic vs mem0 vs RAG vs no-memory. One harness, one judge, published configs/prompts/variance (preempts the misconfigured-baseline rebuttal).

Add the tokens-vs-accuracy efficiency frontier column (accuracy per input-token consumed). Positioning discipline (Opus audit HIGH-1): the claim is "competitive accuracy ON THE EPISTEMIC SLICES, far fewer tokens" - NEVER absolute accuracy parity with mem0 (they self-report 93.4 while we are currently below the 42.8 RAG floor; an unscoped parity claim is falsifiable by our own benchmark the moment it runs). Scope the token-frontier chart to the epistemic slices, not the retrieval baselines - a retrieval-baseline frontier chart is the exact drift step 2 warns against, as a pitch slide.

Public framing: "we published a reproducible epistemic-slice harness with one judge and open configs" - NOT "we are the neutral referee." The referee seat is aspirational; an unknown two-person team's harness is itself vendor-discountable until others reproduce it (the same evidence that shows the seat is empty - mem0 at 93.4 self-reported vs 49.0 in Hindsight's runs - shows referees get dismissed too).

### 4. Memory Health Audit tool (Verda entry, scaffold by Monday)

The "agent memory linter": read-only ingestion adapters (mem0 export JSON, markdown memory dirs) over existing custodian machinery (extraction, citation validation, contradiction detection) plus a report renderer. Output: junk rate, contradiction pairs, staleness distribution, duplication clusters, hallucination-amplification chains, top-N "your agent answers this wrong because of this memory" examples.

- Public run: a mem0-issue-#4573-class corpus (97.8% junk, one hallucination amplified into 808 entries)
- Private run: Verda's mem0 store, as the sales entry

Verda guard: never open with a recall bake-off. The audit goes first; the shadow-run conversation happens after the rot is undeniable and the step 1 fix is live. Vic books the Verda audit conversation now.

Sequencing precision (Opus audit HIGH-2): "step 1 fix is live" does NOT mean general recall rewards epistemics - the step-1 plan covers only the semantic-query depth-0 path; RRF fusion_mode and graph-depth recall get no epistemic fusion until the fast-follow ships. A post-audit bake-off is therefore only safe on semantic-query epistemic slices. Do not let a Verda eval wander into fusion_mode/graph territory before the fast-follow lands.

### 5. Pitch fixes (one afternoon)

- Slide 8 leads with adjudication / evidence-gated belief formation (the current temporal-provenance uniqueness claim is falsified by Zep)
- Add Zep/Graphiti AND Hindsight/Vectorize to the competitive matrix (Hindsight is the real 3-6 month fast-follower)
- Purge any August-2026 EU AI Act framing: the Digital Omnibus (May 7, 2026) moved high-risk obligations to Dec 2, 2027. MiFID II/SEC record-keeping is the honest finance hook
- Restate margins per the Jun 3 verdict
- Candidate line: "The Token Company compresses syntax; Engrammic compresses epistemics"

## Kill/watch criteria

- Read-path fix fails to show the epistemic slices winning even in-house: THE central bet fails; the "more than retrieval" claim is unproven at product level; stop before publishing, revisit thinking-vs-retrieval conclusions
- Hindsight adopts epistemic/provenance framing or ships evidence-linked beliefs: accelerate benchmark publication
- Verda insists on a recall bake-off before an audit: negotiate the audit first or accept the loss risk knowingly
- Provider-native memory (Anthropic context editing + memory tool, already claiming 84% token reduction) ships epistemic features or makes the token-efficiency pitch table-stakes: re-anchor positioning on cross-provider auditability, drop the token lead
- Our published harness number gets dismissed as vendor noise despite open configs (the court's finding-#2 failure mode recurring against us): pivot proof weight from the public number to private side-by-sides on prospect data (the audit motion)

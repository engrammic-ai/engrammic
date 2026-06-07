# Recall Read-Path Fix (Phase 1)

> Pairs with the user-owned somnus client plan `somnus/docs/superpowers/plans/2026-06-07-fix-engrammic-recall-formatting.md`. The server returning real content (this plan) is a precondition for that client-side formatter fix to have anything to format.

## Context

A LoCoMo/LongMemEval probe shows Engrammic recall makes the agent *worse* than no memory: `with_engrammic` 19-33% vs `without_engrammic` 57% vs `with_rag` 75% (n=21, somnus harness). Recall "finds something but not the right content." An Opus diagnosis plus two code-verification passes traced this to a **depth=0 vector read-path regression**, not the retrieval architecture (PPR is not on this path). Two independently-required defects compound; fixing one without the other barely moves the number (which is why the recent `be783b1` "lower thresholds" looked inert).

This plan fixes the read path only. SPLADE failure (degrades cleanly to dense), query-expansion failure (Gemini route config), full tier/heat/signals removal, and write-time summaries are explicit follow-ups.

Corrected facts (verified against `src/context_service/`): `heat_ranking_enabled` defaults False (settings.py:1476) so the heat multiplier is inert; `freshness_weight=0.3` but freshness ~1.0 for fresh data, so `relevance_score` is effectively raw cosine; reranking is on by default (settings.py:156).

## Root cause (confirmed)

1. **Threshold runs on raw cosine; the rerank score is discarded.** `query()` sets `QueryResult.relevance_score = cosine x freshness` (context.py:1516-1519). `_apply_reranking` (context_query.py:112-186) reorders results but never writes `RerankResult.score` back, in both the fresh branch (line 185) and the cache-hit branch (lines 138-148). `raw_result_dicts` (context_query.py:418-433) reads the still-cosine `relevance_score`; `apply_threshold_filter` (quality.py:49-82) compares it to per-layer floors (KNOWLEDGE/WISDOM=0.35, MEMORY/INTELLIGENCE=0.25). A passage the reranker ranks #1 with cosine 0.34 is dropped. Live: 8 of 10 filtered.

2. **Content truncated to 200-char summaries.** The public `recall` tool and `_recall_impl` (recall.py:37-82, 264-275) never accept/pass `include_content`, so `_context_recall` gets `None`. On `None`, `_apply_tier_content_policy` (context_recall.py:90-122) keeps content only for HOT/WARM and strips COLD to `content[:200]` (`_project_node_without_content`, line 61). Nodes are created `tier:'COLD'` with no summary (context.py:252), and the benchmark runs cold (no SAGE promotion), so every hit becomes a 200-char stub, often cut mid-word.

3. **(Latent, non-gating) Tier never reaches search results.** `QueryResult` has no `tier` field (models.py:69-83); `raw_result_dicts` and `context_get`'s `node_dict` omit the top-level tier, so the tier policy always sees COLD. Real correctness bug long-term, but because benchmark nodes are genuinely COLD it does not change the benchmark; bundled as cleanup.

## The trap that gates the threshold fix

`reranker.rerank()` swallows its own exceptions and returns synthetic descending scores `1.0 - i*0.01` (reranker.py:68-73). So `_apply_reranking`'s try/except rarely fires and `fallback_used` stays False. If we write scores back without fixing this, a silent Vertex failure writes 1.0/0.99/... into `relevance_score`, passes any floor, and reports `retrieval_quality="high"` - trading a recall bug for a false-confidence bug. **Make reranker failure observable first.**

## Tasks (subagent-driven, sequential; tests folded into each task via TDD)

### Task 1 - Make reranker failure observable (prerequisite, isolated)
- `reranking/reranker.py:35-73`: remove the silent synthetic-score fallback (lines 68-73); let `rerank()` raise on the Vertex/litellm error. `_apply_reranking` already catches and sets `fallback_used=True` (context_query.py:172-178). Verify no other caller: `rg -n "\.rerank\(" src/`.
- Tests: `tests/reranking/test_reranker.py` updated for the raise contract.

### Task 2 - Rerank score write-back + threshold on the rerank score (the core fix)
- `mcp/tools/context_query.py:112-186` `_apply_reranking`: write `r.relevance_score = rr.score` for each result, in BOTH the fresh branch (after line 163, from `reranked`) and the cache-hit branch (lines 138-148, from `cached_scores`). Do NOT write back when `fallback_used` (leave cosine). Thread a `reranked_applied` boolean out (`settings.reranking.enabled and not fallback_used and len(results) > 1 and model present`).
- `reranking/quality.py`: add `RERANK_SCORE_FLOOR = 0.05` next to `LAYER_THRESHOLDS`. Add `rerank_floor: float | None = None` to `apply_threshold_filter` (49-82); when set, compare every scored result to `rerank_floor`, ignore per-layer/overrides, still honor `bypass`, `min_threshold`, and `score is None` passthrough.
- `mcp/tools/context_query.py:437-450`: pass `rerank_floor=RERANK_SCORE_FLOOR` when `reranked_applied`, else keep per-layer cosine behavior.
- **Floor must be non-zero**: LoCoMo cat-5 is adversarial (abstention is correct; somnus scores it via ABSTENTION_PROMPT). A zero floor makes recall always return weak nodes and the LLM hallucinates, killing the "none" signal. 0.05 starting value, tuned in Validation.
- Tests: `tests/mcp/tools/test_context_query_reranking.py` assert post-rerank `relevance_score` equals the mocked reranker score (fresh + cache-hit), plus a degraded case (rerank raises) asserting cosine retained + per-layer floors applied + `retrieval_quality` capped. `tests/reranking/test_quality.py`: fix the 3 floor-drift failures (`test_defaults_present`, `test_filters_below_knowledge_threshold` use <0.35, `test_unknown_layer_uses_memory_threshold` use <0.25) and add a `rerank_floor=0.05` case.

### Task 3 - Full content by default (benchmark-gating)
- `mcp/tools/recall.py`: add `include_content: bool | None = True` to `_recall_impl` (37-48) and the public `recall` tool (264-275, document it); pass through to `_context_recall` (72-82) and the inner `_recall_impl` call (299-310, keyword arg to avoid positional drift). Verify size-metric references resolve (recall.py:336).
- Rationale: the somnus client sends only `{query, top_k}` (silo.py:405-415) and cannot opt in, so only a server **default** of `True` fixes the benchmark. `True` (not `None`) guarantees content regardless of tier; `include_content=False` still strips (summaries become an explicit opt-in later).
- Tests: assert `_recall_impl(query=...)` with no `include_content` returns full `content`; explicit `False` still strips.

### Task 4 - Tier propagation cleanup (bundled, non-gating)
- `services/models.py:69-83`: add `tier: str | None = None` to `QueryResult`.
- `services/context.py:1535-1548`: set `tier=props.get("tier")` (props carries it, context.py:659).
- `mcp/tools/context_query.py:418-433`: add `"tier": r.tier` to `raw_result_dicts`.
- `mcp/tools/context_get.py:133-146`: add top-level `"tier": props.get("tier")` to `node_dict`.
- Tests: search-path `tier="HOT"` + `include_content=None` -> content retained.

Final gate: `uv run pytest tests/reranking tests/mcp/tools/test_context_query_reranking.py tests/mcp/test_context_recall.py tests/integration/test_context_recall_content.py -q` and `just check`.

## Verification (two-step, on the somnus probe)

Harness: `somnus bench run <benchmark> --mode <arm> -n 20` (sibling repo `/home/novusedge/Projects/delta-prime/somnus`). Fixed slice including adversarial questions, fresh silos / `bypass_cache` (result cache, context_query.py:337-372, can serve pre-fix dicts). Set `expand_hard_queries=False` for validation so a Gemini route error cannot masquerade as a threshold/content miss. Attribute on the server-truth metric (`structuredContent.results[].content` length via somnus `_parse_recall_result`), not the formatted prompt string (the formatter is the user-owned fix).

1. **Isolating run (upper-bound):** temporarily forward `include_content=True, min_threshold=0.0, bypass_cache=True` from the somnus client. Confirms both defects are the cause and bounds recoverable accuracy (expect a large jump toward the 75% `with_rag` ceiling on answerable questions).
2. **Calibrated run (the fix), flip one at a time:** (a) content-only, (b) threshold-only, (c) both. Then sweep `RERANK_SCORE_FLOOR` in {0.02, 0.05, 0.1, 0.2}: pick the highest floor that preserves adversarial abstention while capturing >=~90% of the bypass ceiling on answerable questions.

## Regression risks
- **False "high" on Vertex outage** - highest risk; mitigated by Task 1 (failure signal) so write-back is skipped and per-layer cosine floors + quality cap apply on fallback.
- **Adversarial recall regression** - mitigated by the non-zero rerank floor + the abstention sweep.
- **Non-rerank deployments** (`reranking.enabled=False`, no model, single result) - keep per-layer cosine floors; the `reranked_applied` gate ensures `rerank_floor=None` there.
- **Payload/cost increase** - `include_content=True` ships full text (intended); note for cost dashboards (`record_context_recall_size`).
- **Result-cache poisoning** - run validation with `bypass_cache`/fresh silos.

## Out of scope (follow-up plans)
- SPLADE/hybrid reliability (clean dense fallback today).
- Query-expansion Gemini route fix (`_maybe_expand_query` re-raises, uncaught).
- Full tier/heat/signals removal: the dormant heat multiplier (context.py:1521-1528), the tier content policy, the stored `tier`/`heat_score` field (DB migration), the signals diffusion jobs.
- Store real LLM summaries at write time + tier promotion.

## Critical files
- `src/context_service/reranking/reranker.py` (failure contract)
- `src/context_service/mcp/tools/context_query.py` (write-back + floor selection)
- `src/context_service/reranking/quality.py` (rerank_floor)
- `src/context_service/mcp/tools/recall.py` (include_content default)
- `src/context_service/services/context.py` + `services/models.py` + `mcp/tools/context_get.py` (tier propagation)

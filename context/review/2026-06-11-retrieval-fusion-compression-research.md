# Research: Score Fusion + Retrieval/Compression for the Read Path and Benchmark

Date: 2026-06-11
Method: two web-grounded research passes run during step-1 planning (see `context/plans/2026-06-11-step1-read-path-epistemic-fusion.md` and `context/plans/2026-06-11-defensibility-sprint.md`). Pass 1: how to fuse cross-encoder rerank scores with epistemic metadata. Pass 2: retrieval-side compression, memory-as-compression efficiency frontiers, and what is borrowable for the read path and the tokens-per-correct-answer benchmark column.

## Part 1: Score fusion (informs sprint step 1, incorporated into the plan)

### Findings

- Cross-encoder scores are logits with query-dependent scale; not comparable across queries (sentence-transformers #1262). RRF is for fusing retriever lists, not for per-document priors; once a reranker has scored candidates, modulate its score rather than discarding it for ranks.
- The dampened multiplicative form `final = rerank * ((1-w) + w*signal)` is the production-validated pattern: Elastic explicitly recommends multiplicative boosts for query-independent quality/recency priors because they are scale-invariant (function_score boost_mode defaults to multiply); CrAM (AAAI 2025, arXiv 2406.11497) down-weights LLM attention multiplicatively by min-max-normalized credibility, +20% against misinformation.
- Never use a bare `* confidence` multiplier: a 0.1-confidence node would be annihilated regardless of relevance (inverse of the reranker-overwrite bug).
- Credibility-aware retrieval literature (CONFACT/IJCAI 2025, RA-RAG) mostly applies reliability at use/aggregation time, not by hiding documents from retrieval. Conflict-RAG work (MADAM-RAG arXiv 2504.13079, ArbGraph arXiv 2604.18362) prefers surfacing conflicts to the generator over suppression. Engrammic's demote (fusion) + withhold (trust gate) + conflict_status in payload is stricter than the literature but coherent for an epistemic product.
- Freshness: arXiv 2509.19376 uses convex blend alpha=0.7 with 14d half-life; key lesson is that weights below ~0.1 are decorative — exactly the failure class of applying freshness pre-rerank and letting the reranker overwrite it (Engrammic's current state).
- Abstention thresholds should key on evidence relevance, fixed on validation data (arXiv 2509.01476, Google sufficient-context). Floors and adaptive tau must judge the raw (pre-fusion) rerank score; fused scores are for ordering only — otherwise tau shifts with whichever document happens to be high-confidence.
- Pitfalls: no multiplier may reach 0; don't double-apply freshness; keep heat out of post-rerank fusion (popularity feedback loop); log every fusion component (multiplicative chains are undebuggable from the final number).

### Decisions taken (in the step-1 plan)

- v1 fusion: confidence (W=0.3, knowledge/wisdom layers only, missing=1.0) and conflict penalty (0.5 for unresolved). Thresholds (floor, tau, quality buckets) on pre-fusion basis via `score_key`/`rerank_score`.
- Deferred, benchmark-gated: per-query min-max normalization of rerank scores; post-rerank freshness with per-layer half-life (memory ~14d, knowledge ~90d, wisdom none); credibility (W~0.15) and capped corroboration (W~0.1) multipliers.
- Tuning order on the benchmark: confidence_weight first, then conflict_penalty sweep {0.3, 0.5, 0.7}; ablate each signal to w=0 and require metric movement.

## Part 2: Retrieval + compression (informs sprint steps 2-3 and positioning)

### Landscape numbers (flag vendor vs measured)

- Syntax-level prompt compression caps out at 2-5x: LLMLingua-2 (arXiv 2403.12968) is the deterministic workhorse (BERT-size token classifier, no LLM in the loop, 2-5x, 3-6x faster than v1). LongLLMLingua: 4x with +17.1% accuracy on multi-doc QA (compression as distractor removal). Embedding-space extreme compression (xRAG one-token, COCOM) failed independent re-benchmarking (survey arXiv 2409.13385) and requires model surgery — permanently out of scope for a provider-agnostic MCP service.
- Fact-level distillation delivers 10-70x: Zep (arXiv 2501.13956, vendor-authored with published methodology) reports 115k -> 1.6k avg context tokens (~70x); the +18.5% accuracy figure is RELATIVE and gpt-4o-SPECIFIC (71.2 vs 60.2 on LongMemEval) - always carry both qualifiers when citing (Opus verification 2026-06-11). ENGRAM (arXiv 2511.12960, peer-submitted, NOT us despite the name) beats full-context by 15 points at ~1% of tokens with typed memory + plain dense retrieval, no graph. mem0 self-reports 93.4 LongMemEval @ ~6.8k tokens/query.
- Structure per se does not win: SmartSearch (arXiv 2603.15599) shows index-free retrieval + good reranking (88.4%) beats graph systems; GraphRAG-Bench (arXiv 2506.02404) shows graph often loses to vanilla RAG and can blow up (Legal dataset: 180k tokens from dense traversal). The token win comes from write-time fact extraction, not read-time graph traversal. Graph earns its keep on multi-hop/temporal and provenance.
- Hindsight (arXiv 2512.12818): 91.4% LongMemEval (Gemini-3 Pro); their runs score mem0 at 49.0 vs mem0's self-reported 93.4 — the benchmark-number anarchy is extreme; neither is neutral. (Reinforces the referee-seat opportunity.)
- LongMemEval-V2 (our actual target) leaderboard is EMPTY; baselines AgentRunbook-R 58.6% @ 26.9s, AgentRunbook-C 74.9% @ 108.3s on web-small. LAFS metric is latency-based; tokens-per-correct-answer is our own added instrumentation. Never present classic LongMemEval-S numbers as comparable to V2 web-small.
- Anthropic context editing + memory tool: 84% token reduction, +39% combined performance in their 100-turn eval — the harness-side complement, also the platform-absorption signal.

### Positioning verdict: "compresses epistemics, not syntax"

Supported, with discipline: syntax compressors cap at 2-5x and carry no provenance; fact-level distillation measures 10-70x. The claim must rest on fact extraction + adjudication (not "we have a graph"), accuracy retention must be measured not asserted (mem0 shows a 55-point multi-hop penalty from aggressive consolidation), and the safe citations are the peer-reviewed set (ENGRAM, Adaptive-k, Sufficient Context, GraphRAG-Bench, LLMLingua); Zep/mem0/Hindsight/ByteRover/OMEGA numbers are vendor self-reports on differing configs.

### Borrow list (ranked, 2-person team, sprint window)

Read path, now:
1. **Adaptive-k via score-gap cutoff** (Adaptive-k, EMNLP 2025, arXiv 2506.08479) — cut returned results at the largest gap in the post-rerank score distribution with min/max bounds. Training-free, deterministic, zero latency; plausibly halves tokens on easy queries at equal accuracy. Hours of work. NOTE: after step 1 lands, the gap detection should run on the pre-fusion (rerank_score) basis, consistent with the threshold rules.
2. **Confidence-gated content tiering** — extend the existing include_content tier policy: high-confidence Facts/Beliefs return adjudicated statement + evidence URIs only; raw content only for low-confidence Memories or on explicit expand. This is the ENGRAM/Zep facts-not-chunks mechanism in our existing schema. ~Half day; log tokens per tier.
3. Write-time notes/fact extraction for the harness — already planned (2026-06-09); the survey strongly validates it (RAG+notes 51.0 vs RAG 42.8 on web-small).

Benchmark harness, now:
4. **Tokens-per-correct-answer instrumentation** mirroring mem0's framing for comparability: single-pass, one retrieval call, report accuracy + mean retrieved-context tokens/query (tokenized with the answer model's tokenizer), derive tokens-per-correct = total tokens / correct answers, with CI. Baselines for the frontier plot: full-context, naive vector RAG fixed top-k (42.8), RAG+notes (51.0), Engrammic. The accuracy-vs-tokens frontier chart is the pitch slide.
5. **Fixed-token-budget sweep** (1k/2k/4k/8k) — "same accuracy, N-times fewer tokens" is only credible as iso-accuracy across budgets, not one cherry-picked point.
6. **LongMemEval-V2 leaderboard submission** — empty leaderboard, cheap visibility; our <250ms recall target is 100x under the AgentRunbook baselines' latency.

Defer:
- LLMLingua-2 as optional post-rerank squeeze on residual raw chunks (tiering should make it mostly redundant; revisit if budget sweeps show raw-content tiers dominating).
- Sufficiency autorater / selective abstention (ICLR 2025) — LLM call per query; post-sprint, but on-thesis ("Engrammic says when it doesn't know").
- Graph-traversal token caps — note the GraphRAG-Bench 180k blowup as a known failure mode; add a hard cap next time the graph read path is touched.
- Anything embedding-space (xRAG/COCOM).

## Source index

Fusion: Elastic multiplicative boosting / function_score; Vespa phased ranking; CrAM arXiv 2406.11497; CONFACT IJCAI 2025 (arXiv 2505.17762); RA-RAG arXiv 2410.22954; MADAM-RAG arXiv 2504.13079; ArbGraph arXiv 2604.18362; freshness-in-RAG arXiv 2509.19376; RALM abstention arXiv 2509.01476; Google sufficient-context; Cohere rerank best practices; sentence-transformers #1262.

Compression/retrieval: ENGRAM arXiv 2511.12960; Zep arXiv 2501.13956; Hindsight arXiv 2512.12818; SmartSearch arXiv 2603.15599; GraphRAG-Bench arXiv 2506.02404; Adaptive-k arXiv 2506.08479; Sufficient Context arXiv 2411.06037; LLMLingua-2 arXiv 2403.12968; compression survey arXiv 2409.13385; dynamic context cutoff arXiv 2502.01025; mem0 token-efficient-memory + 2026 benchmarks blogs (vendor); Anthropic context management; LongMemEval-V2 site; Letta memory blocks (vendor); ByteRover / OMEGA (vendor).

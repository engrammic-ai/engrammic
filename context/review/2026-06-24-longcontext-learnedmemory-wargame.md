# Long-context + learned-memory wargame — competitive read

Date: 2026-06-24

Adversarial review of six papers plus two live competitors, framed against Engrammic's
positioning. Three subagent adversaries (red team, technical skeptic, VC) attacked the
defending thesis; this is the synthesis of what survived.

## The reading set

Four arxiv papers (all read in full):

1. **Retaining by Doing** (Princeton, 2510.18874) — RL forgets less than SFT; cause is
   on-policy data, not RL machinery. In-weights continual learning is getting *less*
   destructive. Scale-capped (<=8B), LR-confounded, RLVR-only.
2. **How much do LMs memorize?** (Meta FAIR, 2505.24832) — ~3.6 bits/param capacity ceiling
   on weight storage (order-1 mean over a 2.86-4.23 spread at toy scale). Text-domain
   "memorization" is reference-model-relative, not absolute.
3. **Sparse Memory Finetuning** (Meta, 2510.15103) — parameter-isolated updates to memory-layer
   slots cut forgetting. Optimizer-confounded (SGD vs AdamW), 1.3B only, short-form QA only.
   **Names RAG as "the natural present-day solution" and declines to benchmark against it.**
4. **S5** (ICLR 2023, 2208.04933) — diagonal SSM + parallel scan; the conceptual bridge to
   Mamba. LRA average is Path-X-inflated; init-fragile. Relevant only as the long-context
   (context-window) lineage.

Two live competitors:

5. **SubQ / Subquadratic AI** — SSA, linear content-dependent sparse attention. Context-window
   substrate. See below.
6. **Engram (engram.com)** — launched 2026-06-23, $98M at ~$600M val. Learned in-weights memory
   substrate. See below.

## The through-line

There are three places to put knowledge an agent needs:

- **Weights** (papers 1-3, Engram) — hard, lossy, ~3.6 bits/param, forgetting-prone but improving.
- **Context window** (S5 -> Mamba -> SubQ) — amnesiac between sessions, no provenance, no
  truth maintenance, but cheap and getting cheaper.
- **External epistemic store** (Engrammic) — durable, attributable, contradiction-aware.

Papers 1-3 document how painful the weights path is. SubQ argues the context-window path
dissolves retrieval scaffolding. Both are pressure on Engrammic's category. Neither, on the
evidence, touches write-time truth maintenance.

## SubQ / SSA — technical verdict

Threat is real in *trend*, unproven in *this paper*:

- **Linearity is unverifiable.** Mechanism withheld ("outside the scope of this report"). They
  publish DeepSeek's selection-cost-vs-length curve (quadratic, 190x at 12M) but pointedly NOT
  their own selector's curve. Crediting "linear end-to-end" is crediting an undisclosed claim.
- **12M is single-UUID-needle** — maximally separable, the easiest possible probe. The real
  multi-task benchmark (RULER) is run only at 128K, 90x shorter than the headline length.
- **Donor conversion, no matched ablation.** Capability may be off-the-shelf YaRN + long CPT,
  not SSA (the authors admit, sec 5.3, they never ran the controlled ablation).
- **Blog self-contradicts**: 56.2x vs 52.2x prefill; 62.8x vs 64.5x FLOP. Leads with MRCR 86.2
  that the *report itself* discredits (sec 5.5). Cross-vendor table is harness noise (Opus 4.7
  scoring 46pts below 4.6).

The report is honest; the marketing is not. The DeepSeek-indexer critique is the paper's most
defensible content.

## Engram — competitive intel

- Launched from stealth 2026-06-23: $98M, ~$600M val, 13 people. General Catalyst, Kleiner,
  Sequoia, Karpathy. Microsoft (M365 testing), Notion, Harvey live.
- Product: separates reasoning/inference layer from memory layer; trains a compact per-org model
  on proprietary context; continual retrain (daily -> hourly); claims frontier quality at up to
  100x fewer tokens.
- **Naming emergency:** "Engram" now owns "AI memory layer" in tech press. "Engrammic" is one
  letter off a $600M same-category company. Decide rename while pre-revenue.

## What the wargame killed

- **"Complementary to the model"** — that is the definition of a feature, not a company. Strike it.
- **"Knowledge bigger than the window"** — a retreating front line; betting against context growth.
- **The read-path investment** — heat/PPR/fusion ranking (incl. the current `feat/heat-ppr-boost`
  branch) is the exact scaffolding SubQ argues gets dissolved. Polishing it now is optimizing the
  deck chair during the window the write-time thesis should be getting proven.

## What survives (the only defensible square)

**Vendor-neutral, auditable, write-time truth maintenance across multiple agents writing to
shared state** — "Git for multi-agent shared state" — sold as **governance/audit infrastructure**
to a regulated buyer who pays to be reconstructably-right.

- Engram can't take it: per-org learned weights are neither neutral nor auditable.
- Labs won't take it: cross-vendor + "we certify what's true" liability is off-thesis.
- SubQ can't take it: a context window, any length, is amnesiac between sessions.

Genuinely orthogonal to context length. But it becomes a company only with a number.

## The gate milestone

A third-party-reproducible BEAM/mem0-style **contradiction + update + supersession** benchmark
where Engrammic beats a >=1M-token long-context model **given the full corpus in-window** (a
truth-maintenance win the window cannot replicate), and also beats mem0/Zep. Until that ships,
the memory -> coherence reposition reads as a thesis fleeing falsification, not conviction. With
it, the reposition becomes data-driven.

## Action order

1. Treat the name as an emergency; decide rename now.
2. Freeze read-path research.
3. Ship the coherence benchmark in weeks, not quarters.
4. Reframe pitch: governance-grade system of record for multi-agent state, not "AI memory layer."

## Caveat

The multi-agent-shared-state world this depends on is not here yet. That is a timing bet, not a
wrong bet — which means speed and proof matter more than polish.

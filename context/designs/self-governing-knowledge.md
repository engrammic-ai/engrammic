# Self-Governing Knowledge: Grounding Verification + Source Sync

**Status:** design locked 2026-06-11 (discussion record:
`~/.claude-bits/engrammic/2026-06-11-self-governing-knowledge-discussion.md`)
**Scope:** hosted service (context-service). Local engine out of scope for v1.
**Out of scope:** concept formation (separate future spec), multimodal evidence
(interface accommodates it; no implementation).

## Problem

Two holes in the Knowledge layer today:

1. **Promotion never reads evidence.** Claim → Fact validation is metadata
   arithmetic: `evidence_count` counts edges (existence, not support),
   `source_tier` is self-reported by the claiming agent, `raw_confidence` is LLM
   self-assessment. Nothing answers *"does the cited evidence entail this claim?"*
   An agent asserting `source_tier="authoritative", confidence=0.9` promotes
   unchallenged through R1.

2. **"Facts persist until contradicted" fails silently.** Contradiction only
   arrives when new information is ingested. A fact whose source document quietly
   changed stays confident forever. T1 lists "source-changed" as a trigger but
   nothing detects source changes.

## Design principle: one governance loop

Every mechanism below is the same pattern applied to different events:

```
events: agent writes claim │ corroboration arrives │ source diff lands │ recall bumps doc
                                   ▼
              coalescing dirty-set (idempotent flags, like heat_dirty — never queues)
                                   ▼
              heat-ranked bounded drain (Custodian workers, existing T1/T3 model)
                                   ▼
              deterministic adjudication (cached verifier scores + pure rules)
                                   ▼
              graph converges: promote / supersede / refute / inert
```

Invariants of the loop:
- Every node state is either **terminal-and-inert** or has a **defined waking
  event**. Nothing polls beliefs; no cron sweeps the graph re-checking things.
- Compute is bounded by **distinct adjudication decisions**, not write volume
  (coalescing + caching).
- Every state change leaves an audit edge (SUPERSEDES, ValidationRecord,
  provenance).

---

## Part 1 — Grounding verification

### New invariant

**I7: no `:Fact` exists without a passing grounding verification.** Grounding
*gates* promotion: a claim that hits R1/R2 thresholds first enqueues grounding;
promotion proceeds only on an `entailed` verdict. Agent-facing write latency is
unchanged — only background promotion waits.

### Worker

New Custodian worker (signal-driven, heat-ranked, same family as T1/T3):

1. Wakes on `grounding_dirty` flags. Drains top-K by heat per cycle (bounded batch).
2. Operates **per SPO fingerprint**, not per claim node — corroborating
   restatements share one verification.
3. Assembles evidence content transiently: text of all `DERIVED_FROM` target
   passages. (This is the "ephemeral grounding context" — it lives only in the
   request payload; durable residue is the ValidationRecord + edge scores.)
4. Calls the tiered verifier (below) with one **atomic SPO claim rendering** per
   check — never compound sentences (live-tested: compound claims misclassify as
   not-checkable).
5. Writes per-pair `entailment_score` onto each `DERIVED_FROM` edge, persists a
   `ValidationRecord`, clears the flag, re-signals the promotion gate.

### Tiered verifier

**Tier 0 — Google Check Grounding API** (Vertex AI Search `:check` endpoint).
- Verified pricing: SKU `BFE9-7E43-9B31`, $0.00000075/char ($0.75/M chars);
  ~$0.004/check worst case. Covered by GCP grant. <500ms latency.
- Limits: claim ≤ 4,096 tokens; ≤ 200 facts × 10k chars per call (one call covers
  all evidence for a claim).
- Live-calibrated behavior (2026-06-11, `engrammic` project): exact/atomic
  entailment 0.98–0.99; contradiction/unsupported 0.003–0.013; heavy paraphrase
  0.475 (correctly ambiguous); opinions return `groundingCheckRequired: false`.

**Tier 1 — LLM judge** (Gemini Flash-class; frontier buys little — the ~75–78%
BAcc ceiling on LLM-AggreFact is shared by small verifiers and frontier judges).
Receives only the ambiguous band. Structured verdict: entails/neutral/contradicts
+ rationale.

**Bands (initial, to be calibrated on a labeled sample of our own claims):**
- score ≥ 0.8 → `entailed`
- score ≤ 0.2 → `not_entailed`
- between → escalate to Tier 1 (expected 10–30% of pairs)
- `groundingCheckRequired: false` → `not_checkable` — claim is not fact-eligible
  (opinion/normative; Commitment/Belief material), not an error.

**Replayability doctrine preserved:** all verifier outputs (both tiers) are cached
keyed on `(claim_fingerprint, evidence_hash, verifier_version)`. Promotion replays
from cache and never re-calls a model. Verification is extraction-side of the
extraction/Custodian seam; adjudication stays pure.

**Modality seam:** verifier interface declares `supported_modalities`. Tier 0 is
text-only; non-text evidence routes directly to a multimodal Tier 1. No v1 work.

### Claim lifecycle (state machine)

```
                       new evidence edge (write event only)
                      ┌─────────────────────────────────┐
                      ▼                                 │
:Claim ──(R1/R2 signal)──► grounding ──► not_entailed → refuted (inert, ~0.1x scoring)
  │                           │
  │                           ├──► entailed → promotes to :Fact
  │                           └──► not_checkable (inert; not fact-eligible)
  └── never signaled → plain :Claim (scored as today)
```

- **`refuted` is terminal and inert.** No worker revisits it. Revival is
  edge-triggered only: a new corroborating claim or new `DERIVED_FROM` edge resets
  status to pending and re-enqueues — and the cache means only the *new* pair is
  scored. Lifetime verification cost per claim = one check per distinct
  claim–evidence pair, regardless of how often promotion is reconsidered.
- Verifier model upgrades bump `verifier_version`; claims re-ground lazily on
  their next natural signal. No bulk sweeps.

### Backpressure

Signals are **flags, not queue entries** (`grounding_dirty`, like `heat_dirty`).
N writes to the same fingerprint coalesce to one pending check. Workers pull
bounded top-K by heat; under load, cold claims' promotion latency grows — the
explicitly chosen degradation axis. Correctness unaffected (ungated claims stay
claims). Horizontal scaling = more workers on the same set.

### Schema additions

- `:Claim.grounding_status ∈ {pending, entailed, refuted, not_checkable}` (+
  `verifier_version`, `grounded_at`)
- `DERIVED_FROM.entailment_score: float`
- `:ValidationRecord {verdict, support_score, tier, cited_node_ids, response_hash,
  verifier_version, checked_at}` linked to the claim. Compact; the audit answer to
  "why did this promote."
- Promotion rules R1/R2 gain the grounding-gate input. (R3 slot is available if we
  prefer expressing the gate as a rule.)

---

## Part 2 — Source sync

### SourceAdapter interface

```python
class SourceAdapter(Protocol):
    def fetch(self, ref: SourceRef) -> SourceContent          # full content
    def fingerprint(self, ref: SourceRef) -> str              # cheap change probe
    def diff(self, old: SourceContent, new: SourceContent) -> list[PassageChange]
```

v1 implementations: **LocalFileAdapter** (mtime + content hash),
**UrlAdapter** (etag/Last-Modified HEAD, hash fallback).

**Connectors via Nango** (Notion, Slack, Drive, Confluence…): thin
`NangoSourceAdapter` where the platform's incremental sync *replaces* `diff()` —
Nango's webhook delivers changed records; `fingerprint()` degenerates to the sync
cursor; `fetch()` pulls the changed record. OAuth, token refresh, rate limits,
pagination are bought, not built (OSS/self-hostable = lock-in escape hatch;
~$50/mo starter at our volume). Downstream of the dirty-set, the Custodian cannot
tell a Notion edit from a local file save: **one re-validation path, two
change-discovery mechanisms.**

### Trigger: poll floor + recall bump + push fast-path

- Each `:Document` carries `next_check_at`, derived from heat (hot docs ~6–24h
  floor; cold docs much slower) with hard floor and ceiling. Scheduled
  Groundskeeper-family job drains due documents: `fingerprint()` always; full
  `fetch()` + `diff()` only on mismatch. Steady-state cost ≈ HEAD requests.
- **Recall of a Fact bumps its source doc's priority in the dirty-set. Recall
  never fires its own check** — 500 recalls of a hot doc coalesce to one probe.
- Webhooks (Nango, file watchers) stamp `next_check_at = now` into the same set.
  **Push is never the sole mechanism**: Drive watch channels expire ≤1 week with
  no auto-renew; Notion webhooks miss content-block edits. The poll floor is the
  staleness guarantee; push is a latency optimization.

### Drift rule: re-ground, then downgrade

A landed diff re-extracts changed passages through the normal T1 pipeline. Then:

- New claims contradicting existing Facts → ordinary T2 supersession
  (`reason='contradiction'`). Nothing new needed.
- Facts whose supporting passage was deleted/rewritten → the diff **dirties their
  grounding flags**; the grounding worker re-runs entailment against the *new*
  source version:
  - still entailed (cosmetic edit, moved text) → no-op. Zero churn from typo fixes.
  - no longer entailed → `SUPERSEDES` with new **`reason='source_drift'`**; fact
    falls back to claim-level scoring; revivable by future evidence like any
    refuted claim.

No separate staleness machinery. A source change is just another event type into
the same loop.

### Schema additions

- `:Document` sync metadata: `source_ref`, `adapter`, `fingerprint`,
  `next_check_at`, `last_checked_at`, `sync_class`
- `SUPERSEDES.reason` gains `'source_drift'` (alongside contradiction,
  evidence_shift, author_update, evidence_erased)
- `PassageChange` provenance: changed passages record `replaces_passage_id` so
  drift supersession chains trace to the exact source delta.

---

## Costs (verified where stated)

| Item | Cost |
|---|---|
| Check Grounding API | $0.75/M chars (SKU verified via Billing Catalog API); ~$0.004/check worst case |
| Tier-1 LLM escalation | ~$0.0002–0.001/check (Flash-class), 10–30% of pairs |
| Source sync steady state | HEAD/etag probes ≈ free; Nango ~$50/mo starter |
| Pathological day (100k distinct new pair-checks) | ~$50 against $25k grant |

Self-host fallback if managed API becomes unviable: HHEM-2.1 (110M) or
MiniCheck-FT5 (770M) on Cloud Run (scale-to-zero, L4 ~$0.67/hr; CPU viable for
both) ≈ single-digit $/mo at low volume.

## Open questions

1. Band thresholds need calibration on a labeled sample of real claims
   (literature: thresholds transfer poorly across domains).
2. Confirm in billing console which characters the Check Grounding SKU counts
   (answerCandidate only vs + facts) — bounds differ ~25x, both negligible.
3. Local engine grounding story: privacy posture rules out the hosted API;
   likely ships the CPU NLI path later. Deferred.
4. Whether the grounding gate is expressed as a modification to R1/R2 or as a new
   R3 rule — implementation detail, decide at plan time.

## Positioning note

This is the "self-governing database for agent memory" claim made concrete:
storage systems (and grep-over-wikis) have no answer to "the world changed."
*Grep tells you what the files say; engrammic tells you what's still true, who
established it, and what replaced it.*

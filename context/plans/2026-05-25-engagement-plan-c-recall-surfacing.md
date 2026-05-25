# Engagement Plan C: Recall Surfacing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface engagement payloads in recall responses so agents see unresolved markers touching their query context.

**Depends on:** Plan B (SAGE prerequisites) — shipped 2026-05-25

**Spec:** `context/brainstorm/2026-05-25-engagement-surface-layers.md`

---

## Scope

### In scope for Plan C:
- Engagement detection logic: query Redis marker index by about-set
- `engagement` field in recall response (richer structure than original spec - see Architecture)
- `dismiss(marker_id, reason)` verb for Contradiction/StaleCommitment markers
- `tick` verb stub for Layer 2 hook readiness (returns engagement without recall)
- Soft surfacing only (mode: "soft", results still populated)

### Out of scope (Plan D):
- Hard checkpoint (results replaced with engagement-only payload)
- Soft-to-hard escalation based on touch count
- Session-scoped touch counters (requires header-keyed state)

### Clarifications:
- **`accept`/`reject`** already work for ProposedBelief (Plan A). Engagement surfaces them; agent uses existing verbs.
- **Contradiction/StaleCommitment resolution**: Agent uses `believe` or `learn` with `supersedes` to create new claim, then `dismiss` the marker. No `revise` extension needed - cleaner separation.

---

## Architecture

### Engagement Detection

On every recall, after fetching results:

1. Collect `about_ids` from results (nodes returned by the query)
2. Query Redis marker index: `ZUNIONSTORE` across `markers:{silo_id}:about:{about_id}` keys
3. If any pending markers found, populate `engagement` field
4. Filter to pending status only (exclude resolved/dismissed)

Latency budget: <10ms (Redis sorted-set ops are sub-ms; network bound)

### Recall Response Shape

**Note:** This is richer than the original brainstorm spec's flat structure. The per-marker detail improves agent decision-making and is an intentional spec evolution.

```python
{
    "results": [...],           # unchanged
    "hypotheses": [...],        # unchanged (when include_hypotheses=True)
    "engagement": null | {      # NEW
        "mode": "soft",         # always "soft" for Plan C
        "markers": [
            {
                "marker_id": str,
                "marker_type": "Contradiction" | "StaleCommitment" | "ProposedBelief",
                "summary": str,         # human-readable description
                "node_ids": list[str],  # affected nodes
                "detected_at": str,
                "decision_required": "accept" | "dismiss"  # accept for ProposedBelief, dismiss for others
            }
        ]
    }
}
```

### Engagement Field Rules

- `engagement` is `null` when no pending markers touch the about-set
- `mode` is always `"soft"` in Plan C (hard mode is Plan D)
- `decision_required` mapping:
  - ProposedBelief: `"accept"` (use `accept` verb to ratify, or `reject` to decline)
  - Contradiction: `"dismiss"` (resolve via `believe`/`learn` with `supersedes`, then `dismiss`)
  - StaleCommitment: `"dismiss"` (form new commitment, then `dismiss` marker)
- If marker was dismissed recently (within same session), exclude it

### dismiss Verb

New MCP tool for acknowledging markers without resolving them.

```python
dismiss(marker_id: str, reason: str) -> {"marker_id": str, "status": "dismissed"}
```

- Calls `dismiss_marker()` from `engine/markers.py` (already exists)
- Records reason for downstream threshold tuning
- **Error on ProposedBelief**: Returns error `"Use 'reject' verb for ProposedBelief markers, not 'dismiss'"` with marker details

### tick Verb

Lightweight engagement check without full recall. Layer 2 hook integration point.

```python
tick(about_hint: list[str] | None = None) -> {"engagement": ... | null}
```

- Reads precomputed marker index only (no graph traversal, no embedding)
- `about_hint` optional: node IDs to check. If omitted, returns all pending markers for silo.
- Returns same `engagement` shape as recall response
- Safe to call frequently with zero side effects
- Latency target: <5ms

---

## File Structure

```
src/context_service/
  engine/
    engagement.py                            # CREATE - engagement detection logic
  mcp/
    tools/
      recall.py                              # MODIFY - add engagement field
      dismiss.py                             # CREATE - dismiss verb
      tick.py                                # CREATE - tick verb
  config/
    mcp_tools.yaml                           # MODIFY - add dismiss and tick verbs

tests/
  engine/
    test_engagement.py                       # CREATE - engagement detection tests
  mcp/
    tools/
      test_dismiss.py                        # CREATE - dismiss tool tests
      test_tick.py                           # CREATE - tick tool tests
```

---

## Task 0: Verify Baseline

- [ ] Run `just check` and `just test` to establish baseline
- [ ] Confirm Plan B markers infrastructure exists (`engine/markers.py`)

---

## Task 1: Engagement Detection Logic

**Files:** `engine/engagement.py`

**Goal:** Query Redis marker index and return engagement payload.

- [ ] `get_engagement_for_about_set(redis, silo_id, about_ids) -> list[MarkerSummary]`
- [ ] Fetch marker_ids from Redis (`ZUNIONSTORE` or pipeline of `ZRANGE`)
- [ ] Fetch marker details from graph via `GET_MARKERS_BY_IDS`
- [ ] Filter to status="pending" only
- [ ] Build summary string for each marker type
- [ ] Determine `decision_required` based on marker type
- [ ] Tests: empty case, single marker, multiple markers, mixed types

---

## Task 2: Wire Engagement into Recall

**Files:** `mcp/tools/recall.py`

**Goal:** Populate `engagement` field in recall response.

- [ ] After fetching results, collect about_ids from result nodes
- [ ] Call `get_engagement_for_about_set()`
- [ ] If markers found, add `engagement` field to response
- [ ] If no markers, set `engagement: null`
- [ ] Latency tracking: add `engagement_ms` to metrics
- [ ] Tests: recall with no engagement, recall with soft engagement

---

## Task 3: Add dismiss Verb

**Files:** `mcp/tools/dismiss.py`, `config/mcp_tools.yaml`

**Goal:** New MCP tool for acknowledging non-ProposedBelief markers.

- [ ] Validate marker_id exists and status is pending
- [ ] Validate marker_type is not ProposedBelief (use `reject` for those)
- [ ] Call `dismiss_marker()` from `engine/markers.py`
- [ ] Return `{marker_id, status: "dismissed"}`
- [ ] Add to `mcp_tools.yaml` with description
- [ ] Register in `mcp/tools/__init__.py`
- [ ] Tests: successful dismiss, invalid marker_id, already dismissed

---

## Task 4: Add tick Verb

**Files:** `mcp/tools/tick.py`, `config/mcp_tools.yaml`

**Goal:** Lightweight engagement check for Layer 2 hook integration.

- [ ] Create `tick.py` with optional `about_hint` parameter
- [ ] Call `get_engagement_for_about_set()` (or all pending markers if no hint)
- [ ] Return `{"engagement": ...}` with same shape as recall
- [ ] Add to `mcp_tools.yaml` with description
- [ ] Register in `mcp/tools/__init__.py`
- [ ] Tests: tick with no markers, tick with markers, tick with about_hint filter

---

## Task 5: Full Sweep

- [ ] `just check` — lint + typecheck clean
- [ ] `just test` — all tests pass
- [ ] Manual smoke test: create contradicting claims, verify recall shows engagement
- [ ] Commit with summary of Plan C changes

---

## Done Criteria

Plan C is complete when:

- [x] Recall responses include `engagement` field when pending markers touch about-set
- [x] `dismiss(marker_id, reason)` verb works for Contradiction/StaleCommitment markers
- [x] `dismiss` returns clear error for ProposedBelief markers
- [x] `tick` verb returns engagement state without full recall
- [x] Engagement detection adds <10ms to recall latency
- [x] `just check` and `just test` green

**Status: SHIPPED 2026-05-25** on branch `feat/telemetry-observability`. Ready for PR.

---

## What Ships After Plan C

- **Plan D:** Hard checkpoint + soft-to-hard escalation. Session-scoped touch counters, results-replaced mode.
- **Plan E:** Skills + installer config. `engrammic-engage` skill, AGENTS.md guidance, installer updates.

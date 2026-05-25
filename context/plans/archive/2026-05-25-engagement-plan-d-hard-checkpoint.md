# Engagement Plan D: Hard Checkpoint

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Escalate soft engagement to hard checkpoint when agents repeatedly ignore surfaced markers, forcing resolution before recall results are returned.

**Depends on:** Plan C (recall surfacing) — shipped 2026-05-25

**Spec:** `context/brainstorm/2026-05-25-engagement-surface-layers.md`

---

## Scope

### In scope for Plan D:
- Session identity extraction from `x-session-id` header
- Time-decayed touch counter in Redis per (silo, session, marker)
- Soft-to-hard escalation logic (N touches without resolution)
- Hard checkpoint response shape (`results: []`, engagement only)
- Recall-scoped blocking (other tools unaffected)
- Configuration for escalation threshold and decay window

### Out of scope (Plan E):
- Hook surface (Layer 2) — `tick` on session start, post-tool triggers
- Installer config updates for `x-session-id` header injection
- `engrammic-engage` skill for teaching commit/revise/dismiss decision
- AGENTS.md guidance block distribution

### Clarifications:
- **Stateless HTTP preserved.** No sticky sessions or server-side connection state. All session identity comes from client-sent `x-session-id` header.
- **Graceful degradation.** If no `x-session-id` header, fall back to silo-scoped tracking (collapses concurrent agents but still works).
- **Recall-scoped only.** Hard engagement blocks `recall`, not other tools. Agent can still `remember`, `learn`, `link` while resolving.

---

## Architecture

### Session Identity

The server already extracts `x-session-id` from HTTP headers (`mcp/server.py:271`). Plan D:

1. Read `x-session-id` from request context (falls back to `"default"` if missing)
2. Use as part of touch counter key
3. Document header requirement in installer/config guidance (Plan E)

### Touch Counter Design

Redis sorted set per marker, scored by touch timestamp:

```
Key: touches:{silo_id}:{marker_id}
Members: {session_id}
Scores: {timestamp_ms}
```

On each recall that surfaces a marker:
1. `ZADD touches:{silo_id}:{marker_id} {now_ms} {session_id}`
2. `ZREMRANGEBYSCORE` to prune entries older than decay window (default: 30 min)
3. `ZSCORE` to get this session's touch count for this marker

Touch count = number of times this session has seen this marker within the decay window.

### Escalation Logic

```python
def should_escalate_to_hard(marker_id: str, session_id: str, silo_id: str) -> bool:
    touch_count = get_touch_count(silo_id, marker_id, session_id)
    return touch_count >= ESCALATION_THRESHOLD  # default: 3
```

Escalation is per-marker, per-session. Different sessions hitting the same marker escalate independently.

### Hard Checkpoint Response

When `mode: "hard"`:

```python
{
    "results": [],              # EMPTY - this is the enforcement mechanism
    "hypotheses": [],           # also empty
    "engagement": {
        "mode": "hard",
        "markers": [...],       # same shape as soft
        "message": "Resolution required before recall results are available. Use accept/reject for ProposedBelief markers, or dismiss for others."
    }
}
```

The empty `results` is intentional: harness-agnostic enforcement. The agent has nothing else to act on.

### Configuration

Environment variables with sensible defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGAGEMENT_ESCALATION_THRESHOLD` | `3` | Touches before soft->hard |
| `ENGAGEMENT_DECAY_WINDOW_MS` | `1800000` | 30 min decay window |
| `ENGAGEMENT_HARD_ENABLED` | `true` | Kill switch for hard mode |

### Resolution Detection

When a marker is resolved (via `accept`, `reject`, or `dismiss`):
1. Delete touch counter key `DEL touches:{silo_id}:{marker_id}`
2. Marker status already updated to resolved/dismissed by existing code

Next recall for this session sees no pending marker, returns normal results.

---

## File Structure

```
src/context_service/
  engine/
    engagement.py                            # MODIFY - add escalation logic
    touch_counter.py                         # CREATE - Redis touch tracking
  mcp/
    tools/
      recall.py                              # MODIFY - hard checkpoint response
  config/
    settings.py                              # MODIFY - add escalation config

tests/
  engine/
    test_touch_counter.py                    # CREATE - touch counter tests
    test_engagement.py                       # MODIFY - add escalation tests
  mcp/
    tools/
      test_recall.py                         # MODIFY - hard checkpoint tests
```

---

## Task 0: Verify Baseline

- [ ] Run `just check` and `just test` to establish baseline
- [ ] Confirm Plan C engagement detection works (`engine/engagement.py`)
- [ ] Confirm session header extraction exists (`mcp/server.py:271`)

---

## Task 1: Touch Counter Module

**Files:** `engine/touch_counter.py`

**Goal:** Redis-backed time-decayed touch tracking.

- [ ] `record_touch(redis, silo_id, marker_id, session_id) -> int` — returns new touch count
- [ ] `get_touch_count(redis, silo_id, marker_id, session_id) -> int`
- [ ] `clear_touches(redis, silo_id, marker_id)` — called on marker resolution
- [ ] Implement decay via `ZREMRANGEBYSCORE` on each access
- [ ] Tests: single touch, multiple touches, decay expiry, clear on resolution

---

## Task 2: Escalation Configuration

**Files:** `config/settings.py`

**Goal:** Add escalation settings with environment variable overrides.

- [ ] `ENGAGEMENT_ESCALATION_THRESHOLD: int = 3`
- [ ] `ENGAGEMENT_DECAY_WINDOW_MS: int = 1800000`
- [ ] `ENGAGEMENT_HARD_ENABLED: bool = True`
- [ ] Wire into settings dataclass/pydantic model

---

## Task 3: Escalation Logic in Engagement

**Files:** `engine/engagement.py`

**Goal:** Determine soft vs hard mode based on touch count.

- [ ] Extract `session_id` from context (default to `"default"` if missing)
- [ ] For each pending marker, call `record_touch()` and check threshold
- [ ] If any marker exceeds threshold, set `mode: "hard"`
- [ ] Add `message` field to engagement payload for hard mode
- [ ] Tests: below threshold stays soft, at threshold escalates to hard

---

## Task 4: Hard Checkpoint in Recall

**Files:** `mcp/tools/recall.py`

**Goal:** Return empty results when engagement mode is hard.

- [ ] Check `engagement.mode` after building engagement payload
- [ ] If `"hard"`: set `results = []`, `hypotheses = []`
- [ ] Preserve full engagement payload with markers
- [ ] Add latency tracking for escalation check
- [ ] Tests: hard mode returns empty results, soft mode returns normal results

---

## Task 5: Clear Touches on Resolution

**Files:** `mcp/tools/accept.py`, `mcp/tools/reject.py`, `mcp/tools/dismiss.py`

**Goal:** Reset touch counter when marker is resolved.

- [ ] After successful resolution, call `clear_touches(silo_id, marker_id)`
- [ ] Tests: verify touch counter cleared after accept/reject/dismiss

---

## Task 6: Full Sweep

- [ ] `just check` — lint + typecheck clean
- [ ] `just test` — all tests pass
- [ ] Manual smoke test: trigger 3 recalls touching same marker, verify hard mode
- [ ] Verify resolution clears hard block
- [ ] Commit with summary of Plan D changes

---

## Done Criteria

Plan D is complete when:

- [x] Touch counter tracks per-(silo, session, marker) with time decay
- [x] Recall escalates to hard mode after N touches (default: 3)
- [x] Hard mode returns `results: []` with engagement-only payload
- [x] Resolution (accept/reject/dismiss) clears touch counter
- [x] Missing `x-session-id` degrades gracefully to silo-scoped tracking
- [x] Configuration via environment variables
- [x] `just check` and `just test` green

**Status: SHIPPED 2026-05-25** on branch `feat/telemetry-observability`. Ready for PR.

---

## What Ships After Plan D

- **Plan E:** Hook surface + distribution. `tick` on session start, post-tool triggers, installer config for `x-session-id` injection, `engrammic-engage` skill, AGENTS.md guidance.

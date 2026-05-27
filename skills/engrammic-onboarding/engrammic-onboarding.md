---
name: engrammic-onboarding
description: Session start ritual for Engrammic memory. Establishes tick() discipline for proactive memory enforcement.
---

# Engrammic Onboarding

Establish memory discipline for this session using tick() engagement checks.

## Session Start

1. Call `tick()` to get initial context and pending markers
2. Review any markers returned - address contradictions or stale beliefs
3. Note your session_id from the response for subsequent calls

## During Session (Every 3-5 Turns)

Call `tick()` with context about your current work:

```
tick(
  session_id="<your session_id>",
  recent_context="<brief description of what you're working on>"
)
```

Review the response:
- **markers**: Address any contradictions or stale commitments
- **nudges**: Consider acting on suggestions:
  - `form_belief`: You have related knowledge worth synthesizing
  - `storage_gap`: You haven't stored anything recently - consider `remember()`
  - `stale_hypothesis`: A hypothesis has been open too long - `commit()` or `revise()`
- **context**: Relevant memories surfaced for your current work

## Before Ending Session

1. Call `tick()` one final time
2. Store important findings with `remember()` or `learn()`
3. Crystallize any open hypotheses with `commit()`
4. Reflect on what you learned with `reflect()` if appropriate

## Why This Matters

tick() is lightweight (< 100ms) and helps you:
- Stay aware of pending issues (contradictions, stale beliefs)
- Get reminded when you should store knowledge
- Surface relevant context without full recall
- Maintain epistemic hygiene across sessions

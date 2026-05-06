# Devlog: Cognitive Runtime Pivot

**Date**: 2026-05-07
**Author**: Agent team (schema-agent, recall-agent, tools-agent)

## Summary

Transformed Delta Prime from an epistemically-aware document store into a cognitive runtime that manages live belief state during agent reasoning.

## Key Conceptual Change

Introduced the WorkingBelief/Commitment split:

- **WorkingBelief** (new, intelligence layer): Session-scoped, mutable, ephemeral beliefs during reasoning. Attached to ReasoningSessions via PART_OF_SESSION edge. Can be updated in-place.

- **Commitment** (existing, wisdom layer): Durable stances the agent has crystallized. Supersession-tracked, Custodian-validated. Created by explicit "crystallize" action.

This separation resolves the topology issue identified in the adversarial review: the original plan assumed Commitment nodes connected to sessions, but they're durable and session-independent.

## Changes

### Schema (primitives)
- Added `WORKING_BELIEF = "WorkingBelief"` to `IntelligenceLabel`

### Database Layer
- **indexes.py**: Added WorkingBelief indexes (id, silo_id, session_id)
- **queries.py**: Added 7 new queries:
  - CREATE_WORKING_BELIEF
  - GET_WORKING_BELIEFS_FOR_SESSION
  - UPDATE_WORKING_BELIEF
  - DELETE_WORKING_BELIEF
  - DETECT_CONFLICTING_WORKING_BELIEFS
  - DETECT_CONTRADICTIONS_IN_SESSION
  - CRYSTALLIZE_TO_COMMITMENT

### MCP Tools
- **context_recall.py**: Added `include_content: bool = True` flag for demand paging
- **context_belief_state.py** (new): Query session's WorkingBeliefs + contradiction detection
- **context_update_belief.py** (new): In-place mutation of WorkingBelief
- **context_crystallize.py** (new): Promote WorkingBelief to Commitment with supersession
- **context_store.py**: Added "belief" layer, wired sync conflict detection

### Tool Surface
Now 7 tools (was 4):
- context_store, context_recall, context_link, context_admin (existing)
- context_belief_state, context_update_belief, context_crystallize (new)

### Test Fixes (pre-existing bugs)
- Fixed frozen Settings mutation pattern in test_auth_routing_s001.py, test_docs_disabled_in_prod.py
- Fixed heat score fallback treating 0.0 as falsy in services/context.py
- Added module-level import of get_mcp_auth_context in context_recall.py for test patching

## Files Modified

```
primitives/src/primitives/schema/labels.py
src/context_service/db/indexes.py
src/context_service/db/queries.py
src/context_service/mcp/server.py
src/context_service/mcp/tools/__init__.py
src/context_service/mcp/tools/context_recall.py
src/context_service/mcp/tools/context_store.py
src/context_service/mcp/tools/context_belief_state.py (new)
src/context_service/mcp/tools/context_update_belief.py (new)
src/context_service/mcp/tools/context_crystallize.py (new)
src/context_service/services/context.py
tests/mcp/test_auth_routing_s001.py
tests/test_docs_disabled_in_prod.py
tests/integration/test_context_recall_content.py (new)
```

## Verification

- `just check` passes (ruff + mypy)
- 998 tests pass, 5 skipped, 0 failures

## Related Documents

- Plan: `context/plans/cognitive-runtime-pivot.md`
- Adversarial review: `context/review/cognitive-runtime-pivot-review.md`

## Next Steps

- Integration tests for belief tools (requires live Docker stack)
- Improve MCP tool test quality (currently validates mocks, not behavior)

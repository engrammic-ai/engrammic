# Fix: Surface Invariant Violation Messages in MCP Error Boundary

**Status:** Complete
**Created:** 2026-06-08

## Context

When `learn` tool fails due to an invariant violation (e.g., `NO_MEMORY_EVIDENCE: At least one evidence ref must be from Memory layer (INV2)`), the error boundary sanitizes it to a generic "Backend error (unknown)" message. This hides actionable validation errors from agents.

**Root cause:** `mcp_error_boundary` in `error_boundary.py` catches ALL exceptions and sanitizes them identically, treating user-facing validation errors the same as internal backend failures.

**Invariant errors are intentionally user-facing** — they tell the agent what they did wrong. Backend errors (Qdrant/Memgraph/Redis timeouts) should stay sanitized.

## Fix

Modify `src/context_service/mcp/error_boundary.py` to detect `BrainError` (and subclasses like `InvariantViolation`) and surface their message.

Add handler before generic `Exception`:

```python
except BrainError as e:
    # User-facing validation error - surface the message
    logger.info(
        "mcp_validation_error",
        tool=func.__name__,
        code=e.code,
        message=e.message,
    )
    raise MCPBackendError(
        backend="validation",
        message=f"{e.code}: {e.message}",
        retriable=False,
    ) from e
```

## Files Modified

1. `src/context_service/mcp/error_boundary.py` — add `BrainError` import and handler

## Verification

1. Run `just check` (lint + typecheck)
2. Run existing tests: `just test -k error_boundary`
3. Manual test: call `learn` with only external URLs (no memory node) — should now show `NO_MEMORY_EVIDENCE: At least one evidence ref must be from Memory layer (INV2)` instead of `Backend error (unknown)`

# Task: Improve MCP Tool Test Quality

**Status**: Complete
**Priority**: Low
**Created**: 2026-05-07

## Problem

Current MCP tool tests patch almost everything and assert only that mocks were called. This validates code paths execute, but not that agents get correct behavior.

Example: `test_store_memory` verifies `_context_remember` was invoked with certain args. If routing logic changed but still called the mock, the test would pass.

## Scope

- `tests/mcp/test_context_store.py`
- `tests/mcp/test_context_recall.py`
- Related MCP tool tests

## Desired Outcome

Tests should verify observable outcomes, not mock call arguments:
- Given input X, tool returns response Y
- Given invalid input, tool returns appropriate error
- Side effects (nodes created, edges linked) are verifiable

## Approach Options

1. Use FakeGraphStore with in-memory state, verify state changes
2. Create lightweight integration tests hitting real stores
3. Reduce mock depth - mock at store boundary, not internal functions

## Context

Identified during cognitive runtime pivot. See `context/devlog/2026-05-07-cognitive-runtime-pivot.md`.

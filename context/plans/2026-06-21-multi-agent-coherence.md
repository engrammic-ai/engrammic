# Multi-Agent Coherence Implementation Plan

Date: 2026-06-21
Status: Ready
Design: `docs/superpowers/specs/2026-06-21-multi-agent-coherence-design.md`

## Goal

Enable multi-agent coordination through EAG substrate. Agents can see what others believe, conflicts are detected in real-time, accountability is built-in.

## Scope

- Identity metadata on all content nodes
- Layered identity resolution with fallbacks
- Write-time conflict detection
- Query surface for multi-agent patterns
- Event emission for harness hooks

## Branch

`feat/multi-agent-coherence`

## Phase 1: Schema additions (non-breaking)

- [ ] Add identity fields to node models (`agent_id`, `session_id`, `model_id`, `owner_id`)
- [ ] Add `tenant_id` field (may already exist as `silo_id`)
- [ ] Extend CONTRADICTS edge with `resolution_status`, `resolved_by`, `resolved_at`
- [ ] Add database indexes for agent/session queries
- [ ] Migration script for existing nodes (backfill `agent_id = "legacy"`)

## Phase 2: Identity resolution

- [ ] Create `IdentityContext` dataclass
- [ ] Implement layered fallback resolver:
  - Explicit agent_id from request
  - WorkOS auth context (user_id, session_id)
  - API key context
  - Connection fingerprint
  - Anonymous fallback
- [ ] Wire resolver into MCP request middleware
- [ ] Add `X-Agent-Id`, `X-Session-Id` header support

## Phase 3: Write-path changes

- [ ] Inject identity into all write operations (remember, learn, update)
- [ ] Add conflict detection on write (behind feature flag):
  - Qdrant similarity search for other agents
  - SPO extraction for same-subject check
  - Optional LLM verification
- [ ] Create CONTRADICTS edges with resolution metadata
- [ ] Emit `conflict.detected` events

## Phase 4: Query surface

- [ ] Extend `recall` with `agent_id`, `exclude_agents`, `include_conflicts` params
- [ ] Add `agents()` tool - list agents in silo
- [ ] Add `beliefs_by()` tool - what does agent X believe
- [ ] Add `conflicts()` tool - list conflicts, filter by agent/status
- [ ] Add `diff()` tool - compare two agents

## Phase 5: Conflict resolution tools

- [ ] Add `dismiss_conflict()` - mark as not-a-conflict
- [ ] Add `escalate_conflict()` - flag for human review
- [ ] Add `resolve_conflict()` - pick winner, optionally supersede

## Phase 6: Events and polish

- [ ] Implement event emission (node.created, conflict.detected, etc.)
- [ ] Add polling endpoint for events
- [ ] Configuration for conflict detection (thresholds, LLM toggle)
- [ ] Documentation updates

## Out of scope

- Consensus mechanisms (harness-side)
- Trust scoring / reputation (harness-side)
- SSE/WebSocket event streaming (future)
- Webhook registration (future)

## Done criteria

- [ ] Identity resolved on all writes (never null)
- [ ] Conflicts detected between agents in <100ms (fast path)
- [ ] `agents()`, `beliefs_by()`, `conflicts()`, `diff()` tools working
- [ ] Existing single-agent flows unchanged
- [ ] Tests for identity fallback chain
- [ ] Tests for conflict detection

## Dependencies

- CITE v2 schema (done)
- Qdrant semantic search (done)
- SPO extraction (done)

## Risks

- Write latency increase from conflict detection (~70ms)
- Migration complexity for existing nodes
- Identity collision if harnesses use same agent_id strings (mitigated by tenant scoping)

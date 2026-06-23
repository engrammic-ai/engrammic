# Multi-Agent Coherence Implementation Plan

Date: 2026-06-21
Status: Ready
Design: `docs/superpowers/specs/2026-06-21-multi-agent-coherence-design.md`

## Goal

Enable multi-agent coordination through EAG substrate. Agents can see what others believe, conflicts are detected in real-time, accountability is built-in. Confidence computed from signals, trust earned from track record.

## Scope

- Agent as first-class entity with trust scoring
- Identity metadata on all content nodes
- believers[] array and confidence_signals on nodes
- Confidence computed from signals, cached on write
- Trust earned from track record
- EventLog for audit and time-travel
- Write-time conflict detection
- Query surface for multi-agent patterns

## Branch

`feat/multi-agent-coherence`

## Phase 1: Schema additions (non-breaking)

- [ ] Create Agent entity table:
  ```sql
  CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    trust_score FLOAT DEFAULT 0.5,
    role TEXT,
    parent_agent_id TEXT,
    scope JSONB DEFAULT '[]',
    beliefs_validated INT DEFAULT 0,
    beliefs_contradicted INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [ ] Add identity fields to node models (`agent_id`, `session_id`, `model_id`, `owner_id`)
- [ ] Add `believers` JSONB array to nodes
- [ ] Add `confidence_signals` JSONB to nodes
- [ ] Add `cached_confidence` FLOAT to nodes
- [ ] Create belief_events table:
  ```sql
  CREATE TABLE belief_events (
    id ULID PRIMARY KEY,
    agent_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_events_agent ON belief_events(agent_id, created_at);
  CREATE INDEX idx_events_node ON belief_events(target_node_id, created_at);
  ```
- [ ] Extend CONTRADICTS edge with `resolution_status`, `resolved_by`, `resolved_at`
- [ ] Add database indexes for agent/session queries
- [ ] Migration: backfill existing nodes with `agent_id = "legacy"`, `believers = []`

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
- [ ] Auto-create Agent entity on first write (trust_score=0.5)

## Phase 3: Confidence computation

- [ ] Implement cheap signal gathering:
  - corroboration_count = len(believers)
  - contradiction_count = CONTRADICTS edges
  - validation_count = VALIDATED_BY edges
  - temporal_stability = age without supersession
- [ ] Implement expensive signals (Knowledge/Wisdom only):
  - evidence_score (heuristics on evidence URIs)
  - ncb_score (neighborhood consistency check)
- [ ] Implement `compute_confidence()` formula
- [ ] Cache confidence on write
- [ ] Invalidate on: believer added, CONTRADICTS created, VALIDATED_BY created

## Phase 4: Write-path changes

- [ ] Inject identity into all write operations (remember, learn, update)
- [ ] Log events to belief_events table on write
- [ ] Compute and cache confidence on write
- [ ] Add conflict detection on write (behind feature flag):
  - Qdrant similarity search for other agents
  - SPO extraction for same-subject check
  - Optional LLM verification
- [ ] Create CONTRADICTS edges with resolution metadata
- [ ] Emit `conflict.detected` events

## Phase 5: Query surface

- [ ] Extend `recall` with `agent_id`, `min_confidence`, `min_trust`, `include_conflicts` params
- [ ] Add `agents()` tool - list agents in silo
- [ ] Add `beliefs_by()` tool - what does agent X believe
- [ ] Add `believers()` tool - who believes this node
- [ ] Add `conflicts()` tool - list conflicts, filter by agent/status
- [ ] Add `diff()` tool - compare two agents
- [ ] Add `trust_report()` tool - agent's track record

## Phase 6: Trust scoring

- [ ] Implement `compute_trust()` formula (validated / total)
- [ ] Hook supersession to increment contradicted for original owner
- [ ] Hook VALIDATED_BY to increment validated for owner
- [ ] Background job: 30-day survival check for validated increment
- [ ] Implement `effective_weight()` for weighted queries

## Phase 7: Conflict resolution tools

- [ ] Add `dismiss_conflict()` - mark as not-a-conflict
- [ ] Add `escalate_conflict()` - flag for human review  
- [ ] Add `resolve_conflict()` - pick winner, optionally supersede

## Phase 8: Time-travel and polish

- [ ] Implement `state_as_of()` - reconstruct node state from events
- [ ] Add time-travel param to recall (`as_of`)
- [ ] Configuration for conflict detection (thresholds, LLM toggle)
- [ ] Documentation updates

## Out of scope

- Consensus mechanisms (harness builds on query surface)
- SSE/WebSocket event streaming (future)
- Webhook registration (future)
- Trust score decay (open question)

## Done criteria

- [ ] Agent entity created on first write
- [ ] Identity resolved on all writes (never null)
- [ ] Confidence computed from signals, cached
- [ ] Trust scores updated on outcomes
- [ ] Events logged for audit/time-travel
- [ ] Conflicts detected between agents in <100ms (fast path)
- [ ] All query tools working: agents, beliefs_by, believers, conflicts, diff, trust_report
- [ ] Existing single-agent flows unchanged
- [ ] Tests for identity fallback chain
- [ ] Tests for confidence computation
- [ ] Tests for trust scoring
- [ ] Tests for conflict detection

## Dependencies

- CITE v2 schema (done)
- Qdrant semantic search (done)
- SPO extraction (done)

## Risks

- Write latency increase from confidence computation + conflict detection (~100-150ms)
- Migration complexity for existing nodes
- Identity collision if harnesses use same agent_id strings (mitigated by tenant scoping)
- Trust scoring needs outcome data to be meaningful (cold start)

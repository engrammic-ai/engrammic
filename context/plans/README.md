# Implementation Plans

Active implementation plans for context-service. Completed plans are moved to `archive/`.

## Current state (2026-05-07)

**Shipped:**
- v2 Cognitive Runtime Pivot (WorkingBelief nodes, belief_state/update_belief/crystallize tools, include_content flag)
- v1.7 Auto-Tagging (tag config, cosine matching, Dagster pipelines)
- v1.6 Hybrid Storage (Postgres+Memgraph saga, consolidation, crystallization, GC)
- v1.5 Agent Identity (agent nodes, reflection filtering, chain continuity, per-silo config)
- v1.4.1 MCP QoL (consolidated to 4 tools: store, recall, link, admin; removed 4 legacy tool files)
- v1d Signals Enhancement (heat ranking, unified decay, write events)

## Active plans

| Plan | Status | Description |
|------|--------|-------------|
| [v2-architecture-fixes.md](./v2-architecture-fixes.md) | **Active** | P0-P3 fixes + ProposedBelief flow (3 batches) |
| [2026-05-06-mcp-client-scaffold.md](./2026-05-06-mcp-client-scaffold.md) | Paused | MCP marketplace client repo scaffold |

Next candidates:
- Clustering algorithm evaluation (spike)

## Spikes / drafts

| Plan | Status | Description |
|------|--------|-------------|
| [clustering-algo-eval.md](./clustering-algo-eval.md) | Spike | Evaluate LPA/HDBSCAN as Leiden replacements |
| [dagger-test-pipeline.md](./dagger-test-pipeline.md) | Draft | Dagger-based test pipeline |

## OSS track

| Plan | Description |
|------|-------------|
| [oss-master.md](./oss-master.md) | Master plan for open-source launch |
| [oss-engine.md](./oss-engine.md) | W1: Engine repo (single-tenant SQLite) |
| [oss-manifesto.md](./oss-manifesto.md) | W2: Practitioner manifesto |
| [oss-launch-prep.md](./oss-launch-prep.md) | W3: Repo hygiene + landing page |

## Reference

| Plan | Description |
|------|-------------|
| [eag-integration-audit.md](./eag-integration-audit.md) | Deferred items from EAG port |

## Archive

Completed plans in `archive/`:
- E2E test scenarios (2026-05-06)
- as_of time-travel for node_ids (2026-05-06)
- v1.7 Auto-Tagging
- v1.6 Hybrid Storage
- v1.5 Agent Identity (5.0-5d)
- v1.4.1 MCP QoL
- v1d Signals Enhancement
- v1.3, v1.2, v1.1 EAG completion
- v1-beta production hardening
- v1-alpha paradigm gaps

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria

# Admin Dashboard Design

**Date:** 2026-06-05  
**Status:** Ready for implementation

---

## Overview

Admin dashboard for Engrammic providing visibility into memory state, usage patterns, and system health. Serves three personas: self-hosted operators, SaaS admins, and developers debugging memory state.

**Key insight from design partner feedback:** "Latest changes" views showing data evolution are more useful than browsing everything that exists. Heat visualization reveals retrieval quality issues (useful data not being read).

---

## Architecture

### Deployment Model

- **Separate repo:** `engrammic-ai/dashboard`
- **Stack:** TypeScript monorepo — React frontend + Node.js BFF
- **Deployed independently** from context-service

### Data Access Pattern

| Operation | Path | Rationale |
|-----------|------|-----------|
| Mutations | context-service REST API | Graph consistency (supersession chains, heat propagation, link integrity) |
| Dashboard reads | Direct store queries | Custom aggregations without bloating data API |
| Standard reads | context-service REST API | Reuse auth, validation |

Mutations use existing MCP transactions (`forget`, `dismiss`, etc.) via REST API equivalents. No new mutation logic in dashboard.

### Auth Flow

1. User authenticates via WorkOS OAuth (same flow as context-service)
2. Dashboard stores access token
3. REST API calls pass token in Authorization header
4. Direct store queries: BFF validates token + admin scope before executing

### Store Connections (BFF)

| Store | Purpose |
|-------|---------|
| Memgraph | Graph traversals, heat aggregations, activity streams |
| Postgres | Metrics rollups, audit logs, silo config |
| Redis | Real-time access events, session state |

### Considerations

- **Connection pooling:** BFF + context-service both hit Memgraph — monitor for connection exhaustion
- **Cache coherence:** BFF caches aggregations, context-service mutates — need invalidation via Redis pub/sub
- **Auth boundary:** Direct queries bypass context-service auth — BFF must validate admin perms first

---

## Features (MVP)

### 1. Activity Feed

- Latest nodes created/modified per silo
- Filterable by layer (Memory/Knowledge/Wisdom/Intelligence)
- Supersession chain visualization (A → B → C)
- Real-time updates via Redis access_events stream

### 2. Heat/Usage Visualization

- Heat map by layer and time period
- "Cold nodes" view — nodes with zero/low reads (retrieval quality signal)
- Top N most accessed nodes
- Heat decay over time chart

### 3. Basic CRUD

- Node detail view (content, metadata, signals, links)
- Edit → creates new node via supersession (calls REST API)
- Delete → calls `forget` endpoint (soft-delete with chain repair)
- Dismiss engagement markers

### 4. Traces/Metrics

- Query volume over time (per silo)
- Storage stats (node counts by layer, vector count)
- Latency percentiles (p50/p95/p99)
- Active sessions count

### Deferred (v2+)

- Full graph explorer with visual traversal
- Admin CRUD (silos, skills, config)
- Bulk operations beyond forget
- Export/import UI

---

## BFF API

### Direct Queries (Read-Only)

```
GET /api/activity
    ?silo_id=...&layer=...&since=...&cursor=...&limit=50
    → Memgraph: recent nodes by created_at, include supersession chain

GET /api/nodes
    ?silo_id=...&layer=...&cursor=...&limit=50
    → Memgraph: node list with filters

GET /api/nodes/:layer/:id
    → Memgraph: single node with signals and links

GET /api/nodes/:layer/:id/history
    → Memgraph: supersession chain traversal

GET /api/heat/map
    ?silo_id=...&period=7d
    → Memgraph: aggregate heat_score by layer, bucket by day

GET /api/heat/cold
    ?silo_id=...&threshold=0.1&cursor=...&limit=100
    → Memgraph: nodes where heat_score < threshold, sorted by age

GET /api/heat/top
    ?silo_id=...&limit=50
    → Memgraph: nodes sorted by heat_score desc

GET /api/metrics/summary
    ?silo_id=...
    → Postgres: node counts, storage, query volume rollups

GET /api/metrics/latency
    ?silo_id=...&period=24h
    → Postgres: p50/p95/p99 from telemetry tables

GET /api/health
    → BFF health check
```

### Proxied to Context-Service

```
POST   /api/nodes/:layer           → POST /v1/{layer}/ (create/edit with supersedes)
DELETE /api/nodes/:layer/:id       → DELETE /v1/{layer}/{node_id} (forget)
POST   /api/dismiss                  → POST /v1/dismiss (engagement marker by node_id in body)
POST   /api/nodes/batch/forget     → bulk delete (multiple DELETE calls)
GET    /api/recall                 → POST /v1/search/recall
```

### WebSocket

```
WS /api/stream/activity
    → subscribes to Redis silo:{silo_id}:access_events
    → pushes typed events to connected clients
```

### Query Efficiency Notes

- Heat map aggregation: composite index on `(silo_id, created_at, heat_score)` in Memgraph
- Cold nodes: consider materialized "cold" label or background job rather than threshold scan
- Latency percentiles: pre-aggregate in Postgres rollup table
- Redis stream: cap `XREAD COUNT`, provide `?since_id=` for catch-up

---

## Response Shapes

### Standard Envelope

```typescript
interface ApiResponse<T> {
  data: T;
  meta: {
    cursor?: string;
    has_more?: boolean;
    total_estimate?: number;
    took_ms: number;
  };
}
```

### Node

```typescript
interface Node {
  id: string;
  layer: 'memory' | 'knowledge' | 'wisdom' | 'intelligence';
  content: string;
  created_at: string;
  updated_at: string;
  silo_id: string;
  
  // Signals
  heat_score: number;
  freshness: number;
  access_count: number;
  
  // Supersession
  supersedes?: string;
  superseded_by?: string;
  
  // Layer-specific
  evidence?: Evidence[];    // knowledge
  about?: string[];         // wisdom (linked node IDs)
  
  // Links
  links: Link[];
}

interface Evidence {
  uri: string;
  content_hash?: string;
  accessed_at: string;
}

interface Link {
  target_id: string;
  relation: string;
  created_at: string;
}
```

### Activity Event (WebSocket)

```typescript
type ActivityEvent = 
  | { type: 'node_created'; node: Node }
  | { type: 'node_forgotten'; node_id: string; layer: string }
  | { type: 'node_accessed'; node_id: string; heat_score: number }
  | { type: 'heat_decayed'; affected_count: number };
```

### Heat Map

```typescript
interface HeatMapData {
  buckets: Array<{
    date: string;
    layer: string;
    avg_heat: number;
    node_count: number;
  }>;
  period: string;
}
```

---

## Pages & Components

### Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard home — summary stats, recent activity |
| `/activity` | Activity feed with filters, infinite scroll |
| `/heat` | Heat visualization — map, cold nodes, top nodes tabs |
| `/nodes/:layer/:id` | Node detail — content, signals, history, links |
| `/metrics` | Charts — query volume, latency, storage |
| `/settings` | Silo selector, user preferences |

### Key Components

| Component | Purpose |
|-----------|---------|
| `SiloSelector` | Global silo context (header) |
| `ActivityFeed` | Real-time node list with WS updates |
| `NodeCard` | Compact node display (layer badge, heat indicator, excerpt) |
| `NodeDetail` | Full node view with edit/forget actions |
| `SupersessionChain` | Visual timeline: A → B → C with diff view |
| `HeatMap` | D3/Recharts heatmap by layer x time |
| `ColdNodesTable` | Sortable table with bulk select + forget |
| `MetricsChart` | Time-series line charts |
| `SearchBar` | Recall query input with layer filter |

### State Management

- **React Query:** server state (caching, refetch, optimistic updates)
- **Zustand or Context:** UI state (selected silo, filters)
- **WebSocket hook:** real-time activity stream

---

## Deployment

### Repo Structure

```
engrammic-ai/dashboard/
├── apps/
│   ├── web/          # React frontend (Vite)
│   └── bff/          # Node.js backend (Express/Fastify)
├── packages/
│   └── shared/       # Types, utils shared between apps
├── docker-compose.yml
└── Dockerfile
```

### Deployment Options

| Environment | Frontend | BFF |
|-------------|----------|-----|
| Self-hosted | Static files in BFF container | Single container |
| SaaS (beta) | Cloud Run (static) | Cloud Run |
| SaaS (prod) | CDN (Cloudflare/Vercel) | Cloud Run |

### Environment Variables (BFF)

```bash
# Auth
WORKOS_CLIENT_ID=...
WORKOS_API_KEY=...

# Context-service
CONTEXT_SERVICE_URL=http://context-service:8000

# Direct stores (read-only)
MEMGRAPH_URI=bolt://memgraph:7687
POSTGRES_URL=postgres://...
REDIS_URL=redis://redis:6379

# Optional
CORS_ORIGINS=https://dashboard.engrammic.ai
```

### Self-Hosted Bundling

- Single Docker image with BFF serving static frontend
- Configurable via env vars
- Health endpoint at `/health`

---

## Implementation Notes

### Phase 1: Foundation

- Repo scaffold (Vite + Express/Fastify)
- WorkOS OAuth integration
- Basic routing and silo context
- Activity feed (no real-time)

### Phase 2: Core Features

- Node detail and CRUD
- Supersession chain view
- Heat map visualization
- Cold nodes table

### Phase 3: Polish

- WebSocket real-time updates
- Metrics charts
- Bulk operations
- Performance tuning

### Dependencies

- **Frontend:** React, React Query, Zustand, Recharts/D3, TailwindCSS
- **BFF:** Express or Fastify, neo4j-driver (Memgraph), pg, ioredis
- **Build:** Vite, TypeScript, pnpm workspaces

---

## Prerequisites

Before implementation can begin:

1. **REST API endpoints:** Self-hosted REST API Phase 1 must ship first — provides `/v1/memory/`, `/v1/knowledge/`, `/v1/search/recall`. See `2026-05-20-self-hosted-rest-api-phase1.md`.
2. **Dismiss endpoint:** `/v1/dismiss` not yet implemented — add to REST API or call MCP directly via internal route.
3. **Telemetry tables:** `pg-telemetry` plan shipped — tables exist in Postgres.
4. **Access events stream:** `silo:{silo_id}:access_events` published by context-service per signals-port spec.

---

## Auth & Authorization

### Scopes

Inherited from context-service REST API design:

| Scope | Access |
|-------|--------|
| `read` | View activity, nodes, metrics |
| `write` | read + edit/forget nodes |
| `admin` | write + silo management, job triggers |

### Silo Authorization

WorkOS organization maps to silo:
1. User authenticates via WorkOS
2. WorkOS returns `organization_id` in token claims
3. BFF resolves `organization_id` → `silo_id` via Postgres lookup
4. All queries scoped to resolved silo_id
5. Super-admin role (internal) can access all silos

---

## Error Responses

```typescript
interface ErrorResponse {
  error: {
    code: string;           // e.g., "not_found", "forbidden", "validation_error"
    message: string;        // human-readable
    details?: Record<string, unknown>;
  };
  meta: {
    request_id: string;
  };
}
```

| Status | Code | When |
|--------|------|------|
| 400 | `validation_error` | Invalid params |
| 401 | `unauthorized` | Missing/invalid token |
| 403 | `forbidden` | Token valid but no access to silo |
| 404 | `not_found` | Node/resource doesn't exist |
| 429 | `rate_limited` | Too many requests |

### Bulk Operation Limits

- `POST /api/nodes/batch/forget`: max 100 nodes per request
- Rate limit: 10 bulk operations per minute per silo

---

## Open Questions

1. **Memgraph connection pooling:** What's the right pool size for BFF alongside context-service? (Default: 10, tune post-launch)
2. **Cold node threshold:** Default 0.1, configurable per silo via settings
3. **Metrics retention:** Default 90 days, configurable

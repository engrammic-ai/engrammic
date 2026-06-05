# Plan: Admin Dashboard

**Spec:** `docs/superpowers/specs/2026-06-05-admin-dashboard-design.md`  
**Repo:** `engrammic-ai/dashboard` (to be created)  
**Status:** Ready (pending prerequisites)

## Goal

Build admin dashboard for operators, admins, and developers to view memory state, usage patterns, and system health.

## Prerequisites

- [ ] Self-hosted REST API Phase 1 shipped (provides `/v1/memory/`, `/v1/knowledge/`, `/v1/search/recall`)
- [ ] Dismiss endpoint added to REST API

## Phases

### Phase 1: Foundation (3-4 days)

- [ ] Create repo scaffold (Vite + Fastify, pnpm workspaces)
- [ ] WorkOS OAuth integration
- [ ] Basic routing and layout
- [ ] Silo selector component
- [ ] Activity feed (polling, no real-time)

### Phase 2: Core Features (4-5 days)

- [ ] Node list and detail views
- [ ] Edit/forget CRUD operations
- [ ] Supersession chain visualization
- [ ] Heat map (Recharts)
- [ ] Cold nodes table with bulk select

### Phase 3: Polish (2-3 days)

- [ ] WebSocket real-time updates
- [ ] Metrics charts
- [ ] Bulk forget with confirmation
- [ ] Error handling and loading states
- [ ] Performance tuning

### Phase 4: Deployment (1-2 days)

- [ ] Dockerfile (BFF + static frontend)
- [ ] Cloud Run deployment
- [ ] Self-hosted documentation

## Out of Scope

- Full graph explorer (v2)
- Admin CRUD for silos/skills/config (v2)
- Export/import UI (v2)

## Done Criteria

- [ ] Activity feed shows real-time node changes
- [ ] Heat map visualizes usage patterns
- [ ] Can edit and forget nodes via dashboard
- [ ] Metrics charts render query volume and latency
- [ ] Self-hosted deployment works with single Docker image

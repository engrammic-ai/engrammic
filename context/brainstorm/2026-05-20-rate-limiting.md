# Brainstorm: API Rate Limiting with Tiered Pricing

**Date:** 2026-05-20
**Mode:** Feature

## Summary

Rate limiting requires two enforcement points: a custom MCP tool hook (slowapi cannot differentiate tools without body parsing) and ASGI middleware for REST routes. The critical prerequisite is tier storage — no `tier` field exists anywhere in the data model. Recommended path: store tier in `OrgPreferences.settings` JSONB for speed, migrate to typed column before GA.

## Key Insights

1. **slowapi is wrong for MCP tools.** All MCP calls arrive at `/mcp` as JSON-RPC POST. slowapi cannot inspect tool names without violating the read-once ASGI contract. Use slowapi only for REST admin routes; implement custom Redis-based limiting for MCP.

2. **Two rate limit dimensions matter.** Per-org (billing unit) as primary, per-user fairness cap (20% of org limit) as secondary. Two operation buckets: writes (remember/learn/believe/etc.) and recalls (search-based recall is 80x more expensive).

3. **Tier storage is the critical gap.** No tier field exists in `AuthContext`, `OrgPreferences`, or `SiloConfig`. Must add before rate limiting can work. Fastest path: `OrgPreferences.settings["tier"]` JSONB key.

## Recommended Architecture

```
+------------------+     +------------------+     +------------------+
|  REST Routes     |     |   MCP Tools      |     |   TierResolver   |
|  /admin/*        |     |   remember/etc   |     |   (PG + Redis)   |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         v                        v                        |
+--------+---------+     +--------+---------+              |
| RateLimitMiddle- |     | Tool Hook:       |              |
| ware (ASGI)      |     | check_mcp(auth)  |<-------------+
+--------+---------+     +--------+---------+
         |                        |
         +------------------------+
                    |
                    v
         +------------------+
         |   RateLimiter    |
         |   Service        |
         +--------+---------+
                  |
                  v
         +------------------+
         |   Redis          |
         |   incr_with_expire
         +------------------+
```

## Tier Limits (Recommended Defaults)

| Tier | Writes/mo | Recalls/mo | RPM (org) | RPM (user) |
|------|-----------|------------|-----------|------------|
| Free | 2,000 | 200 | 60 | 20 |
| Starter | 50,000 | 5,000 | 300 | 60 |
| Pro | 300,000 | 30,000 | 1,000 | 200 |
| Enterprise | Unlimited | Unlimited | Custom | Custom |

## Implementation Plan

### Phase 1: Foundation (no behavior change)
1. Add `incr_with_expire` to `RedisClient` (atomic INCR + EXPIRE NX)
2. Expand `RateLimitConfig` to `TierLimits`/`EndpointLimits` schema
3. Create `api/rate_limit.py` with `RateLimiter`, `RateLimitExceeded`, tier resolver
4. Add `enabled: bool = False` gate

### Phase 2: REST enforcement
5. Implement `RateLimitMiddleware` (raw ASGI, not BaseHTTPMiddleware)
6. Add `X-RateLimit-*` header injection

### Phase 3: MCP tool enforcement
7. Add `rate_limiter.check_mcp(auth, tool_name)` to each tool's `_*_impl`
8. Wire `RateLimitExceeded` through `mcp_error_boundary`

### Phase 4: Tier provisioning
9. Add tier write on org creation in `services/org.py`
10. Add admin endpoint `POST /admin/orgs/{org_id}/tier`
11. Backfill existing orgs to appropriate tier

## Critical Blockers (Must Resolve Before Deploy)

| Risk | Severity | Mitigation |
|------|----------|------------|
| Redis unavailability crashes requests | HIGH | Fail-open: if Redis fails, allow request, log warning |
| No tier in data model | HIGH | Add `tier` to `OrgPreferences.settings` JSONB |
| Closed beta silos have no tier | HIGH | Backfill all beta silos to Pro tier before deploy |

## Open Questions

1. **Where does tier live?** `OrgPreferences.settings` JSONB (fast) or new typed column (clean)?
2. **Stripe integration:** Is Stripe live? If so, tier should derive from subscription, not static column.
3. **Billing cycle anchor:** Calendar month (simpler) or subscription anniversary?
4. **MCP response format:** FastMCP lacks per-tool headers. Return rate info in JSON-RPC body `_rate_limit` key?

## Next Steps

1. [ ] Decide tier storage approach (JSONB vs migration)
2. [ ] Create implementation plan via `/gsd-plan-phase`
3. [ ] Validate tier limits against pricing model costs
4. [ ] Add feature flag for gradual rollout

---

## Detailed Analysis

### Requirements Analysis

**Primary dimension: per-org (silo_id).** Engrammic is B2B; orgs pay, not individual users. Rate limiting must track at the org level to enforce plan quotas.

**Secondary dimension: per-user within an org.** A single user should not exhaust a shared org quota by accident. Fairness cap per user (20% of org RPM) prevents this.

**Endpoint classification:**
- **Write ops** (remember, learn, believe, reason, reflect, hypothesize, revise, commit, link): cheap individually, limited by monthly volume
- **Recall ops** (recall with search): ~80x more expensive; need tighter RPM limits and separate monthly bucket

**MCP vs REST:** MCP tools are the billable surface. REST admin (`/admin/*`) is internal/operator-only. Rate limiting applies to MCP in v1.

### Implementation Design

**Why slowapi is rejected for MCP:**
- Key functions receive `Request`, not resolved dependencies — tier resolution requires DB query inside key function
- All MCP calls arrive at `/mcp` as JSON-RPC POST — slowapi cannot differentiate by tool name
- MCP auth resolves per-tool-call via `get_mcp_auth_context()`, after slowapi middleware fires

**Recommended approach: Option B**
- REST routes: raw ASGI middleware (not BaseHTTPMiddleware — keeps SSE working)
- MCP tools: hook in each tool's `_*_impl` after `get_mcp_auth_context()`
- Both share one `RateLimiter` service backed by Redis

**Rate limit key structure:**
```
rl:{category}:{window_start}:{org_id}
rl:{category}:{window_start}:{org_id}:{user_id}  # per-user sublimit
```

**Response headers:**
```
X-RateLimit-Limit: {limit}
X-RateLimit-Remaining: {limit - current}
X-RateLimit-Reset: {unix_timestamp_of_window_end}
Retry-After: {seconds}  # on 429 only
```

### Risk Matrix

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Redis unavailability | HIGH | MEDIUM | Fail-open, circuit breaker, in-process cache fallback |
| Performance overhead on hot paths | HIGH | HIGH | Cache tier config, pipeline Redis calls, target <10ms |
| Tier config lookup complexity | MEDIUM | MEDIUM | Define canonical tier enum, cache in SiloService |
| Testing tiered behavior | MEDIUM | HIGH | `fakeredis` for unit tests, parameterize across tiers |
| Migration of existing silos | MEDIUM | HIGH | Backfill quotas JSONB, feature flag rollout |
| Wrong limits blocking legitimate use | MEDIUM | MEDIUM | Validate against actual usage, soft warning at 80% |
| Tier limits don't match costs | HIGH | HIGH | Cost audit before deployment, start conservative |

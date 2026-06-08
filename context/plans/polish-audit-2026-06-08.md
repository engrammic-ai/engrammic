# Polish Audit - 2026-06-08

Comprehensive audit via 11 parallel Sonnet subagents. Findings verified for false positives.

## Critical (Bugs)

### 1. `readiness_check` returns 200 when not ready
**File:** `api/routes/health.py:196-209`
**Issue:** Returns `{"status": "not_ready"}` with HTTP 200. Kubernetes probes check status code, not body.
**Fix:** Return 503 when not ready.

### 2. `MODELS__TIER` silently ignores valid tiers
**File:** `config/models.py:140`
**Issue:** Only accepts `economy/balanced/premium`, ignores `hybrid/self_hosted/self_hosted_budget`.
**Fix:** Accept all 6 valid tier values.

### 3. DB errors during API key auth logged at DEBUG, return None
**File:** `mcp/server.py:216`
**Issue:** Any exception (including DB outage) silently returns `None`, treating it as auth miss.
**Fix:** Log at WARNING/ERROR, distinguish connectivity errors from auth failures.

### 4. Lazy synthesis returns empty content with score=1.0
**File:** `sage/recall.py:458-471`
**Issue:** Freshly synthesized beliefs added to results with `content=""` and `score=1.0`, sorting empty content to top.
**Fix:** Fetch actual content after creation, or don't add to results until populated.

### 5. Cluster lock released to wrong state on low-confidence path
**File:** `sage/transactions.py:1520-1536`
**Issue:** `revise_belief` releases lock to `SPARSE` when confidence below threshold; `synthesize` (line 448-454) releases to `READY` for the same condition. `SPARSE` means "not enough facts" but the issue is confidence, not quantity.
**Fix:** Change line 1534 from `ClusterState.SPARSE` to `ClusterState.READY`.
**Status:** CONFIRMED

### 6. Sync LLM call blocks event loop
**File:** `llm/google_genai_provider.py:111,165`
**Issue:** `client.models.generate_content()` is sync, called inside async methods.
**Fix:** Wrap in `asyncio.to_thread()` or use async client.

## High (Security)

### 7. Client impersonation on token exchange
**File:** `api/routes/oauth.py:417-449`
**Issue:** `/oauth/token` doesn't validate `client_id`. Any party with a valid code can exchange it.
**Fix:** Require and verify `client_id` matches the code's issuing client.

### 8. Host header injection in OAuth discovery
**File:** `mcp/auth.py:159-168, 197-206`
**Issue:** `WWW-Authenticate` URL built from untrusted `Host` header.
**Fix:** Use `settings.oauth.issuer` instead of request headers.

### 9. CSRF via state=None direct signup
**File:** `api/routes/oauth.py:309-344`
**Issue:** Missing `state` treated as valid direct signup with no CSRF protection.
**Fix:** Require explicit signup parameter, not absence of state.

### 10. Weak default Postgres password
**File:** `docker/docker-compose.selfhosted.yml:219`
**Issue:** Fallback password `engrammic` used if env var not set.
**Fix:** Fail startup if no password configured, or generate random default.

### 11. Dagster webserver exposed without auth
**File:** `docker/docker-compose.selfhosted.yml:58-60`
**Issue:** Port 3000 bound to 0.0.0.0 with no authentication.
**Fix:** Bind to 127.0.0.1 or add reverse proxy with auth.

## High (Contract Violations)

### 12. MCP params accepted but never persisted
**File:** `mcp/tools/context_store.py`
**Params:** `observed_from` (remember), `reasoning`/`tags` (learn), `confidence` (believe)
**Fix:** Either wire up or remove from signatures and schema.

### 13. Skills router entirely 501
**File:** `api/routes/skills.py:26-33`
**Issue:** All endpoints return 501 but router is registered in production.
**Fix:** Remove registration or implement.

### 14. `recall` hard engagement returns empty with no message
**File:** `mcp/tools/recall.py:167-172`
**Issue:** Results silently set to `[]` with no explanation to agent.
**Fix:** Add message explaining suppression.

### 15. Multiple docstring/return mismatches
- `commit`: docstring says `{superseded}`, returns `{confidences}`
- `link`: docstring lists `DERIVES` which doesn't exist
- `forget`: docstring says `cascade_forgotten` list, returns `cascade_count` int

## Medium (Dead Code / Config)

### 16. Dead config fields
- `settings.retrieval_tuning` - duplicate of `retrieval.walker`, never used
- `settings.bear_*` - TODO stub, never implemented
- Triple `vertex_project` fields with no canonical source

### 17. Duplicate cycle-detection functions
**File:** `sage/transactions.py:1791,1809`
**Issue:** `_would_create_cycle` and `would_create_cycle` - private one used, public one dead.

### 18. Schedules missing default_status=RUNNING
**File:** `pipelines/schedules.py:235-260, 394-418`
**Issue:** `sage_groundskeeper_schedule` and `sage_validator_schedule` off by default after deploy.

## Medium (Reliability)

### 19. Rate limiter counts batches as 1 request
**File:** `embeddings/rate_limit.py:82`
**Issue:** Batch of 64 texts counted as 1 request; won't protect quota.

### 20. Rerank cache has no TTL in Qdrant
**File:** `cache/rerank_cache.py:187-233`
**Issue:** L2 entries never expire; unbounded growth.

### 21. Supersession lock fails open
**File:** `engine/memgraph_store.py:448-473`
**Issue:** Redis errors return `True`, allowing concurrent writes that can corrupt chain.

### 22. MemgraphClient closes driver on pool timeout, never reinits
**File:** `stores/memgraph.py:118-128`
**Issue:** Pool timeout closes driver; subsequent calls fail until restart.

### 23. TEI embeddings have no retry
**File:** `embeddings/tei_embeddings.py:108-142`
**Issue:** Single try/except, no retry. Transient errors escalate to cloud fallback.

### 24. Overly broad retry in google_genai_provider
**File:** `llm/google_genai_provider.py:21-26`
**Issue:** Retries on `Exception` base class, including permanent errors.

## Medium (Observability)

### 25. Missing silo_id on multi-tenant warnings
**Files:** `mcp/tools/context_store.py`, `mcp/tools/learn.py`
**Issue:** Warnings logged without silo context.

### 26. f-string logs break structured logging
**Files:** `custodian/visit.py`, `extraction/service.py`

### 27. `from None` breaks exception chaining
**File:** `mcp/middleware.py:70,76`

### 28. Extraction cost_usd always 0.0
**File:** `extraction/service.py:783`
**Issue:** Usage object captured but never consumed.

### 29. causal_relationships parsed but never applied
**File:** `extraction/service.py`
**Issue:** Field in schema/prompts but silently discarded in code.

## Low (Test / Migration Debt)

### 30. 5 MCP tools with zero tests
**Tools:** hypothesize, commit, reason, reflect, revise

### 31. Storage tests are hasattr-only
**Files:** `test_postgres_store.py`, `test_redis_incr.py`

### 32. Migration 0008 downgrade will fail
**File:** `alembic/versions/0008_fix_user_datetime_tz.py:36-47`
**Issue:** Missing `USING` clause for timezone cast.

### 33. Unpinned uv:latest in Dockerfiles
**Files:** All Dockerfiles

### 34. Destructive CLI ops without confirmation
**Files:** `scripts/migrate_qdrant_to_hybrid.py`, `scripts/workos_api_keys.py`

## False Positives (Verified)

- ~~PostgresStore sessions never commit~~ - `get_session()` does commit at line 95
- ~~revise parameter order mismatch~~ - call correctly remaps positions

---

## Implementation Plan

### Phase 1: Security Fixes (P0 - do first)

#### 1.1 OAuth client_id binding
**File:** `api/routes/oauth.py`
**Fix:**
- Add `client_id: str` parameter to token endpoint
- Validate `client_id == auth_request.client_id` before issuing tokens
- Return 400 if mismatch

#### 1.2 Host header injection
**File:** `mcp/auth.py`
**Fix:**
- Add `settings.oauth.issuer` or `settings.base_url` config field
- Replace `request.headers.get("host")` with configured value
- Fallback to request header only in dev mode

#### 1.3 CSRF state=None
**File:** `api/routes/oauth.py`
**Fix:**
- Add explicit `signup: bool = Query(False)` parameter
- Require `signup=true` for direct signup flow, not just absence of state
- Or: generate and verify a nonce for direct signup path too

#### 1.4 Weak postgres password
**File:** `docker/docker-compose.selfhosted.yml`
**Fix:**
- Remove default fallback: `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}`
- Add validation in entrypoint or docs

#### 1.5 Dagster no auth
**File:** `docker/docker-compose.selfhosted.yml`
**Fix:**
- Bind to `127.0.0.1:3000` instead of `0.0.0.0:3000`
- Add docs note about reverse proxy with auth for remote access

### Phase 2: Critical Bugs (P0)

#### 2.1 readiness_check HTTP 200
**File:** `api/routes/health.py:196-209`
**Fix:**
```python
from fastapi.responses import JSONResponse

if not all([memgraph_ok, redis_ok, qdrant_ok, postgres_ok]):
    return JSONResponse({"status": "not_ready"}, status_code=503)
```

#### 2.2 MODELS__TIER ignores tiers
**File:** `config/models.py:140`
**Fix:**
```python
VALID_TIERS = ("economy", "balanced", "premium", "hybrid", "self_hosted", "self_hosted_budget")
if env_tier and env_tier in VALID_TIERS:
    data["tier"] = env_tier
```

#### 2.3 API key auth DEBUG logging
**File:** `mcp/server.py:216`
**Fix:**
```python
except Exception as exc:
    logger.warning("api_key_auth_failed", reason="exception", error=str(exc))
    return None
```

#### 2.4 Lazy synthesis empty content
**File:** `sage/recall.py:458-471`
**Fix:**
- Fetch actual content from the newly created belief
- Or: don't add to results until content is populated
- Set score based on synthesis confidence, not hardcoded 1.0

#### 2.5 Cluster lock wrong state
**File:** `sage/transactions.py:1534`
**Fix:**
```python
"state": ClusterState.READY.value,  # was SPARSE
```

#### 2.6 Sync LLM blocks event loop
**File:** `llm/google_genai_provider.py:120,173`
**Fix:**
```python
import asyncio
response = await asyncio.to_thread(_call)
```

### Phase 3: Contract Violations (P1)

#### 3.1 MCP params never persisted
**Files:** `mcp/tools/context_store.py`
**Fix:** Either wire up `observed_from`, `reasoning`, `tags`, `confidence` or remove from signatures

#### 3.2 Skills router 501
**File:** `api/routes/skills.py`
**Fix:** Remove registration from `api/__init__.py` until implemented

#### 3.3 recall hard engagement no message
**File:** `mcp/tools/recall.py:167-172`
**Fix:**
```python
result["results"] = []
result["message"] = "Results suppressed: engagement checkpoint requires resolution"
```

#### 3.4 Docstring/return mismatches
**Files:** `mcp/tools/commit.py`, `link.py`, `forget.py`
**Fix:** Update docstrings to match actual return shapes

### Phase 4: Reliability (P1)

#### 4.1 Dead config fields
**File:** `config/settings.py`
**Fix:** Remove `retrieval_tuning` (lines 228-244, 970), `bear_*` (lines 1284-1292)

#### 4.2 Schedules missing default_status
**File:** `pipelines/schedules.py`
**Fix:** Add `default_status=dg.DefaultScheduleStatus.RUNNING` to groundskeeper and validator

#### 4.3 Supersession lock fails open
**File:** `engine/memgraph_store.py:465-473`
**Fix:** Return `False` on Redis error, or add retry with backoff

#### 4.4 MemgraphClient driver close
**File:** `stores/memgraph.py:118-128`
**Fix:** Reinitialize driver after close, or don't close on timeout

#### 4.5 TEI no retry
**File:** `embeddings/tei_embeddings.py`
**Fix:** Add retry decorator matching LiteLLM pattern

#### 4.6 google_genai broad retry
**File:** `llm/google_genai_provider.py:21-26`
**Fix:** Narrow to transient errors only (RateLimitError, ServiceUnavailable)

### Phase 5: Observability (P2)

- Add `silo_id` to multi-tenant warnings
- Convert f-string logs to structured
- Remove `from None` or add `__cause__` preservation
- Wire up extraction `cost_usd`
- Wire up or remove `causal_relationships`

### Phase 6: Test/Migration Debt (P2)

- Add tests for hypothesize/commit/reason/reflect/revise
- Fix migration 0008 downgrade USING clause
- Pin uv version in Dockerfiles
- Add confirmation prompts to destructive CLI ops

---

## Execution Order

1. **Branch:** `fix/polish-audit-p0`
2. **Security fixes (1.1-1.5)** - single commit each
3. **Critical bugs (2.1-2.6)** - single commit each
4. **Run `just check` and `just test`**
5. **PR for Phase 1+2**
6. **Branch:** `fix/polish-audit-p1` for remaining phases

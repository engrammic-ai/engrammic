# OTEL/Telemetry Cleanup Plan

## Context
OTEL export to SigNoz now works. Several warnings and issues remain.

## Issues

### 1. SigNoz registration 405 (blocking UI)
**Symptom:** `/api/v1/register` returns 405
**Cause:** Two SigNoz stacks running - the old `signoz` container (port 8080) and new `signoz-query-service`. The frontend at :3301 might be hitting the wrong backend.
**Fix:** Stop old signoz containers, verify frontend config points to correct query-service.

### 2. `_get_collection_name` deprecation (qdrant.py)
**Symptom:** Warning on startup
**Cause:** Legacy single-tenant code path still uses deprecated function
**Scope:** ~10 call sites in `src/context_service/stores/qdrant.py`
**Fix:** Pass `silo_id` through all vector operations. Medium refactor.

### 3. Skills directory missing
**Symptom:** `Skills directory does not exist path=skills` (2x)
**Cause:** No `skills/` dir in container
**Fix:** Either:
  - Create empty `skills/` dir and commit
  - Change warning to debug level (it's expected for minimal deployments)

### 4. Beacon DNS failure
**Symptom:** `telemetry_heartbeat_failed error='[Errno -2] Name or service not known'`
**Cause:** `tel.engrammic.com` doesn't exist yet
**Fix:** Change to debug level when DNS fails (expected until endpoint deployed)

## Execution Order
1. Fix SigNoz stack conflict (quick, unblocks UI)
2. Quick fixes: skills warning, beacon warning (5 min)
3. Qdrant refactor (defer to separate PR)

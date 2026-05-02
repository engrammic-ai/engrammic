# Plan: Auth Completion + Silo Ownership Enforcement

**Status:** Complete 2026-05-02 (verified by audit; per-request auth limitation documented 2026-05-02)
**Branch:** `phase-eag-d-auth-finish`
**Workstream:** v1-β phase 1

## Goal

Finish the auth surface from v1-α: replace the `MCP_DEV_TOKEN` stop-gap with per-request transport-header auth, add the silo-ownership enforcement that v1-α deferred, and verify the WorkOS SDK call against a real tenant.

## Why

v1-α shipped boot-time prod-guard + fail-closed resolver paths, but the MCP surface still resolves auth at session start (not per-request) and `silo.org_id == auth_ctx.org_id` is not checked anywhere. Both are needed before v1-β features land — every Dagster asset, every silo export/import, every silo-scoped read tool will assume these contracts hold.

## Current state (anchored from audit on 2026-04-28)

- `src/context_service/auth/resolve.py:25-74` — `resolve_mcp_auth()` reads `MCP_DEV_TOKEN` env var. Documented stop-gap.
- `src/context_service/mcp/server.py:80-110` — `get_mcp_auth_context()` returns the session-startup-resolved context. No per-request resolution.
- `src/context_service/auth/workos_client.py:36-45` — calls `client.user_management.authenticate_with_session_token(token=token)` with TODO to verify against a real tenant + SDK ≥4.0.
- `src/context_service/services/silo.py:79-110` — has `validate_silo_ownership()` already (per the conftest mock pattern). Need to confirm it's called on every entry point or wire it where missing.
- No tool currently raises on `silo.org_id != auth_ctx.org_id`.

## Tasks (priority order)

1. **Audit existing `validate_silo_ownership` call sites.**
   - grep `validate_silo_ownership` across `src/`. List every MCP tool entry that takes a `silo_id` and confirm it calls the helper.
   - For any tool that doesn't, add the call after the auth resolution step. Consistent placement: right after `auth_ctx` resolves, before any service call.

2. **Strengthen `validate_silo_ownership`.**
   - File: `src/context_service/services/silo.py`. Confirm it does `MATCH (s:Silo {id: $silo_id, org_id: $org_id})` and raises (e.g. `SiloAccessError`) on no rows.
   - Cache positive results in Redis with a short TTL (60-120s) keyed by `silo_ownership:{org_id}:{silo_id}`. Saves a DB round-trip per request once warmed.
   - Cache misses do not negative-cache (security cost too high).

3. **Per-request MCP auth investigation.**
   - Read FastMCP source / docs to find how tool functions can access per-request transport metadata. Candidates: `Context` parameter on tool functions, `mcp.server.lowlevel` request handlers, session metadata via `RequestContext`.
   - If a stable per-request header path exists: refactor `auth/resolve.py` so each tool call resolves its own `AuthContext`. Pass the resolved context into `services/context.py` calls (most existing service methods already accept an `auth_ctx` shape via `ScopeContext` — confirm).
   - If no stable path exists: document the limitation precisely. Keep the env-var path for dev only; ensure prod paths still fail closed (already done in v1-α).

4. **Verify WorkOS SDK against a real tenant.**
   - Pin SDK version in `pyproject.toml`. Confirm `authenticate_with_session_token` is the right method for the SDK version we're pinned to. If the SDK has changed (≥4.0 may have renamed it to `authenticate_with_session_token_and_organization_id` or moved it to `client.sso.*`), update accordingly.
   - Update the integration test in `tests/integration/test_auth_workos.py` to match the verified shape. Mocks were correct in v1-α; verify the real call path now.

5. **Silo-ownership regression test.**
   - `tests/integration/test_silo_ownership.py`: assert in silo A as org X, attempt to query silo A as org Y, expect `SiloAccessError` (or 403 / equivalent MCP error). Pin the boundary.

## Out of scope

- Role-based access control within an org. RBAC is v1.0+.
- Audit logging of auth decisions to a separate store.
- Org-level rate limits or quotas.

## Done criteria

- Every MCP tool entry that takes a `silo_id` calls `validate_silo_ownership` before any service call.
- `validate_silo_ownership` cached via Redis (positive results only, short TTL).
- MCP tool calls under `AUTH_ENABLED=true` resolve auth per-request via ``get_mcp_auth_context()`` (``get_http_headers`` on every tool call). ``MCPAuthMiddleware`` is not mounted -- this limitation is documented in ``mcp/auth.py`` and ``mcp/server.py`` with the rationale (no stable Starlette mount point on FastMCP) and the deferred-to-future-version note.
- WorkOS verify call works against a real tenant or the API is documented as-is with a verified SDK version pin.
- Cross-org silo access raises and the regression test pins it.
- `just check` and `just test` green.

## Findings to absorb (from review 2026-04-28)

The 2026-04-28 codebase review (`context/review/codebase-review-2026-04-28.md`) flagged five auth findings that belong here. **S-001** was lifted into β0 (`v1b-review-cleanup.md`) because the MCP surface raised `RuntimeError` on every call without it; the rest stay here:

- **S-002** (`mcp/auth.py:78-87`) — `validate_mcp_request()` dev-mode fallback has no env guard at request layer; misconfigured prod is full-admin. Add a hard prod check inside the validator, complementing the boot-time guard already shipped in v1-α.
- **S-003** (`auth/resolve.py:58`) — single process-wide `MCP_DEV_TOKEN` static token. Rotation requires restart. The per-request rewrite in task 3 above closes this; ensure the env-var path is dev-only.
- **S-004** (`mcp/auth.py:101`) — `token != expected_key` is timing-unsafe. Replace with `hmac.compare_digest`. Two-line fix; bundle with task 3.
- **S-007** (`auth/workos_client.py:28,37`) — WorkOS SDK method has a TODO marker; verify against the pinned SDK version. Already in this plan as task 4.
- **S-008** (`auth/workos_client.py:28`) — `workos_api_key` typed as `str`, should be `SecretStr` (pydantic). Bundle with task 4.

S-001 status: fixed in `phase-eag-c-review-cleanup` commit `2c68e1a` (route tools to startup auth context). Per-request resolution in this plan supersedes that fix; the absorbing work for β1 is to rewrite around `mcp/auth.py`'s `MCPAuthContext` properly, not to revert the β0 routing.

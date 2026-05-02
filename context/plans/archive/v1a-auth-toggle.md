# Plan: Toggleable WorkOS Auth (Dev Bypass)

**Status:** Approved 2026-04-28
**Branch:** `phase-eag-c-auth-toggle`
**Workstream:** v1-α (close paradigm gaps)

## Goal

Wire WorkOS auth on the FastAPI surface and the MCP server, gated behind an `AUTH_ENABLED` env var so local dev can run without a real WorkOS tenant. When the toggle is off, requests resolve to a fixed dev `org_id` / `user_id`. Boot-time guard prevents shipping the bypass to production.

## Why this matters

The v1 wiki page lists WorkOS as in-scope. The `auth` optional extra in `pyproject.toml` is already declared, but no auth code exists yet. We need to introduce auth without making local development require an external tenant. A toggle is cheap if added now, expensive if retrofitted later.

## Current state (anchored from audit on 2026-04-28)

- No `workos` imports anywhere under `src/`.
- `api/app.py` has no auth middleware. `api/deps.py` has no auth dependency.
- `mcp/server.py` extracts `silo_id` from tool args; no concept of caller identity.
- `config/settings.py` has no auth fields.
- `pyproject.toml` lists `workos` under the `auth` optional extra.

## Tasks (priority order)

1. **Settings.**
   - Edit `config/settings.py`: add fields
     - `auth_enabled: bool = False` (env: `AUTH_ENABLED`)
     - `workos_api_key: str | None = None`
     - `workos_client_id: str | None = None`
     - `dev_org_id: str = "dev-org"`
     - `dev_user_id: str = "dev-user"`
     - `environment: str = "dev"` (env: `ENVIRONMENT`) — if missing, default `dev`.
   - Validator: if `environment == "production"` and `auth_enabled is False`, raise on construction. Prevents accidental prod ship.
   - Validator: if `auth_enabled is True`, require both `workos_api_key` and `workos_client_id` non-None.

2. **`AuthContext` model.**
   - New file `src/context_service/auth/context.py` (create the `auth/` package).
   - `AuthContext` dataclass: `org_id: str`, `user_id: str`, `email: str | None`, `is_dev: bool`. Frozen.

3. **WorkOS client wrapper.**
   - New file `src/context_service/auth/workos_client.py`. Thin wrapper around the `workos` SDK. One method: `verify_session(token: str) -> AuthContext`.
   - Imported lazily inside the function so the module is import-safe even when the `auth` extra is not installed (dev path).

4. **FastAPI dependency.**
   - New file `src/context_service/api/auth_dep.py`. Single dependency `get_auth_context(request) -> AuthContext`:
     - If `settings.auth_enabled` is `False`: return `AuthContext(org_id=settings.dev_org_id, user_id=settings.dev_user_id, email=None, is_dev=True)`. Log once at INFO on first call: `auth: dev bypass active — AUTH_ENABLED=false`.
     - If `True`: extract bearer token, call `workos_client.verify_session`. On failure raise `HTTPException(401)`.
   - Edit `api/deps.py` to re-export `get_auth_context`.

5. **Apply the dependency to existing routes.**
   - `api/routes/health.py` stays unauthenticated (liveness probe).
   - All other future admin routes will take `auth_ctx: AuthContext = Depends(get_auth_context)`. Add a one-line note in `api/routes/__init__.py` or a route-template comment.

6. **MCP server.**
   - Edit `mcp/server.py`: at session start, resolve auth context from the MCP transport's auth header (FastMCP exposes this) using the same `get_auth_context` logic — refactor it to a transport-agnostic helper in `auth/resolve.py` if needed.
   - Dev bypass behaves identically: returns the dev `AuthContext`.
   - Tools that take `silo_id` should validate `silo.org_id == auth_ctx.org_id` (deferred — out of scope here; this plan only resolves the context, doesn't enforce silo ownership).

7. **`.env.example`.**
   - Add:
     ```
     # Auth
     AUTH_ENABLED=false                 # dev only; production must be true
     ENVIRONMENT=dev                    # dev | staging | production
     # WORKOS_API_KEY=
     # WORKOS_CLIENT_ID=
     # DEV_ORG_ID=dev-org
     # DEV_USER_ID=dev-user
     ```

8. **Tests.**
   - `tests/test_auth_dev_bypass.py`: with `AUTH_ENABLED=false`, calling a protected route returns 200 and the handler sees `is_dev=True`.
   - `tests/test_auth_prod_guard.py`: constructing `Settings(environment="production", auth_enabled=False)` raises.
   - `tests/test_auth_workos.py` (marker `integration`): mock the WorkOS SDK; with `AUTH_ENABLED=true` and a valid token, dependency returns the parsed context; with an invalid token, returns 401.

9. **Docs.**
   - Brief note in `architecture/README.md` (the same file Plan 1 will create): "auth toggle for dev; prod-guard prevents bypass leak".

## Out of scope

- Silo ownership enforcement (`silo.org_id == auth_ctx.org_id` on every read/write). Deferred to v1-β.
- Role-based permissions / scopes. v1 wiki page calls "advanced RBAC" out-of-scope.
- WorkOS user provisioning / org sync. Manual for v1.
- MCP transport-level auth header negotiation if FastMCP doesn't expose it cleanly — fall back to a `MCP_DEV_TOKEN` env var read in dev mode and document the gap.

## Done criteria

- `AUTH_ENABLED=false` lets `just dev` start with no WorkOS env vars; routes return 200; `auth_ctx.is_dev` is `True` in handlers.
- `AUTH_ENABLED=true` with valid WorkOS creds verifies real sessions; invalid token returns 401.
- `Settings(environment="production", auth_enabled=False)` raises at construction time.
- `just check` and `just test` pass.
- `.env.example` documents all four auth-related variables.

# Per-request MCP auth: capability spike

**Date:** 2026-04-28
**FastMCP version:** `fastmcp>=2.0` pinned in `pyproject.toml`; resolved in `.venv` to **3.2.4**
**Stream:** v1-β phase 1, Stream C

## Verdict

**REACHABLE** — FastMCP 3.2.4 ships first-class per-request DI primitives (`CurrentHeaders`, `CurrentAccessToken`, `get_http_headers`, `get_http_request`) that expose the live inbound HTTP request, including the `Authorization` header, to every tool invocation. The session-startup cache can be replaced with per-call resolution with no monkey-patching.

## What works

The relevant primitives all live in `fastmcp/server/dependencies.py` and are publicly exported:

- `get_http_headers(include_all=False, include=None) -> dict[str, str]` — `dependencies.py:411-465`. By default it strips `authorization`; pass `include={"authorization"}` to keep it. Never raises — returns `{}` on stdio / no-request.
- `get_http_request() -> starlette.requests.Request` — `dependencies.py:364-408`. Resolves via `mcp.server.lowlevel.server.request_ctx.get().request` first, then falls back to FastMCP's `_current_http_request` ContextVar (`fastmcp/server/http.py`), then a Docket-task header snapshot.
- `get_access_token() -> AccessToken | None` — `dependencies.py:468-532`. Pulls `request.scope["user"].access_token` (an `AuthenticatedUser` from `mcp.server.auth.middleware.bearer_auth`), with a fallback to the SDK's `auth_context_var`.
- `CurrentHeaders()` / `CurrentAccessToken()` — `dependencies.py:1054-1090`, `1265-1309`. `Depends`-style markers usable as default values on tool params; FastMCP's `transform_context_annotations` + `resolve_dependencies` (`dependencies.py:687-727`) wires them in for every tool call.

The MCP SDK side is the same `request_ctx: ContextVar[RequestContext]` that fastmcp imports at `dependencies.py:29` (`from mcp.server.lowlevel.server import request_ctx`). Each MCP request sets a fresh value, so reads are per-call, not per-session.

## What doesn't

- **STDIO transport:** there is no HTTP request, so `get_http_request()` raises `RuntimeError` and `get_http_headers()` returns `{}`. `CurrentAccessToken()` will raise. We need an explicit dev-bypass branch for stdio (and for tests). The current `AUTH_ENABLED=false` env-var path covers this cleanly.
- **`on_initialize` middleware:** `request_ctx` is not yet set; FastMCP works around this with its own `_current_http_request` ContextVar. Not a concern for tool calls — only matters if we hook initialize.
- **Background / Docket tasks:** auth comes from a Redis-backed snapshot taken at submission. We don't run `fastmcp[tasks]`, so irrelevant today; flag if we adopt it.

## Proposed shape

Replace the module-level `_mcp_auth_context` cache. Refactor `resolve_mcp_auth()` in `src/context_service/auth/resolve.py` to accept the inbound `Authorization` value directly, then turn `get_mcp_auth_context()` into a per-call resolver:

```python
# src/context_service/mcp/server.py
from fastmcp.server.dependencies import get_http_headers
from context_service.auth.resolve import resolve_mcp_auth_from_header, MCPAuthError

async def get_mcp_auth_context() -> AuthContext:
    settings = get_settings()
    headers = get_http_headers(include={"authorization"})  # {} on stdio
    auth_header = headers.get("authorization")

    if auth_header:
        return await resolve_mcp_auth_from_header(auth_header)

    # No header: stdio transport, dev mode, or test harness.
    if settings.auth_enabled:
        raise MCPAuthError("Missing Authorization header on authenticated MCP transport")
    return AuthContext(org_id=settings.dev_org_id, user_id=settings.dev_user_id,
                       email=None, is_dev=True)
```

Each tool entry point in `mcp/tools/*.py` already calls `get_mcp_auth_context()`; making it `async` (or keeping it sync — `get_http_headers` is sync) means tools `await` it once at the top of the handler. Drop `resolve_mcp_auth_context()` and its startup call in `api/app.py`. If we want stronger typing, declare `headers: dict[str, str] = CurrentHeaders()` on each tool signature and pass it through, but the ContextVar read is equivalent and less invasive.

For dev-token parity, `MCP_DEV_TOKEN` continues to work — we just read it from `headers["authorization"]` rather than the env var, and document that `AUTH_ENABLED=false` is the stdio/local bypass.

## Fallback plan

N/A — reachable.

## References

- `.venv/lib/python3.13/site-packages/fastmcp/server/dependencies.py:29` (`request_ctx` import)
- `.venv/lib/python3.13/site-packages/fastmcp/server/dependencies.py:364-408` (`get_http_request`)
- `.venv/lib/python3.13/site-packages/fastmcp/server/dependencies.py:411-465` (`get_http_headers`)
- `.venv/lib/python3.13/site-packages/fastmcp/server/dependencies.py:468-532` (`get_access_token`)
- `.venv/lib/python3.13/site-packages/fastmcp/server/dependencies.py:1054-1090` (`CurrentHeaders`)
- `.venv/lib/python3.13/site-packages/fastmcp/server/dependencies.py:1265-1309` (`CurrentAccessToken`)
- `.venv/lib/python3.13/site-packages/fastmcp/server/http.py` (`_current_http_request`)
- `src/context_service/mcp/server.py:80-117` (current cached auth path)

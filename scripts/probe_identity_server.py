"""Standalone FastMCP server that logs incoming identity signals.

Throwaway. Used to answer: what does each MCP harness send as identity?

Run:
    uv run python scripts/probe_identity_server.py

Then point an MCP client at http://localhost:8765/mcp and make a few calls.
Output goes to stdout, one JSON line per request.

The server matches production config (stateless_http=True) so we test the
same shape we deploy.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext


class IdentityProbeMiddleware(Middleware):
    """Logs every identity signal we can extract from an incoming request."""

    async def on_request(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        try:
            headers = get_http_headers(
                include={
                    "authorization",
                    "x-agent-id",
                    "x-session-id",
                    "x-org-id",
                    "mcp-session-id",
                    "user-agent",
                }
            )
        except Exception:
            headers = {}

        fmc = context.fastmcp_context

        def _safe(attr: str) -> Any:
            if fmc is None:
                return None
            try:
                value = getattr(fmc, attr, None)
                if callable(value):
                    return f"<callable {attr}>"
                return value
            except Exception as exc:
                return f"<error: {type(exc).__name__}: {exc}>"

        record = {
            "event": "identity_probe",
            "method": context.method,
            "source": context.source,
            "type": context.type,
            "headers": headers,
            "fmc_id": id(fmc) if fmc is not None else None,
            "client_id": _safe("client_id"),
            "session_id": _safe("session_id"),
            "request_id": _safe("request_id"),
            "origin_request_id": _safe("origin_request_id"),
            "task_id": _safe("task_id"),
            "transport": str(_safe("transport")),
        }
        print(json.dumps(record), flush=True)
        return await call_next(context)


mcp = FastMCP("engrammic-probe")
mcp.add_middleware(IdentityProbeMiddleware())


@mcp.tool
def echo(message: str = "hello") -> str:
    """Return the message. Stub tool for triggering probe."""
    return message


if __name__ == "__main__":
    port = 8765
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    print(f"Probe server listening on http://localhost:{port}/mcp", flush=True)
    print("Point an MCP client at it and make tool calls.", flush=True)
    print("=" * 60, flush=True)
    mcp.run(transport="http", host="127.0.0.1", port=port, stateless_http=False)

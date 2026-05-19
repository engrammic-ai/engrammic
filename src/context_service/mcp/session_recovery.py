"""ASGI middleware for MCP session recovery.

Catches FastMCP's "initialization was complete" errors and returns HTTP 404,
triggering spec-compliant client re-initialization per MCP spec 2025-11-25.
"""
from __future__ import annotations

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


class MCPSessionRecoveryMiddleware:
    """Wrap MCP ASGI app to handle session corruption gracefully.

    When FastMCP marks a session as uninitialized (typically after a backend
    error propagates), this middleware catches the error and returns HTTP 404.
    Per MCP spec, clients MUST re-initialize when receiving 404.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            error_str = str(e).lower()
            if "initialization" in error_str and not response_started:
                logger.warning("mcp_session_corrupted", error=str(e))
                await send({
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error": "Session expired or invalid"}',
                })
            else:
                raise

"""Tests for MCP session recovery middleware."""
import pytest
from starlette.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from context_service.mcp.session_recovery import MCPSessionRecoveryMiddleware


def make_test_app(handler):
    """Create a raw ASGI app wrapped with the middleware.

    We avoid wrapping a full Starlette app here because Starlette adds
    ServerErrorMiddleware between our wrapper and the route handler, which
    catches exceptions before our middleware can and emits a 500.  A raw
    ASGI callable lets us test the middleware contract directly.
    """

    async def asgi_app(scope, receive, send):
        request = Request(scope, receive)
        response = await handler(request)
        await response(scope, receive, send)

    return MCPSessionRecoveryMiddleware(asgi_app)


class TestMCPSessionRecoveryMiddleware:
    def test_passes_through_success(self):
        async def handler(request):
            return JSONResponse({"status": "ok"})

        app = make_test_app(handler)
        client = TestClient(app)
        response = client.post("/mcp/test")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_returns_404_on_initialization_error(self):
        async def handler(request):
            raise Exception("Received request before initialization was complete")

        app = make_test_app(handler)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/mcp/test")
        assert response.status_code == 404
        assert "expired" in response.json()["error"].lower()

    def test_reraises_other_errors(self):
        async def handler(request):
            raise ValueError("Something else went wrong")

        app = make_test_app(handler)
        with pytest.raises(ValueError, match="Something else went wrong"):
            client = TestClient(app, raise_server_exceptions=True)
            client.post("/mcp/test")

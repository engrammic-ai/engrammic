"""Tests for MCP error boundary module."""

import pytest

from context_service.mcp.error_boundary import (
    MCPBackendError,
    _classify_backend,
    _is_retriable,
    mcp_error_boundary,
)


class TestClassifyBackend:
    def test_qdrant_error(self):
        import httpx
        from qdrant_client.http.exceptions import UnexpectedResponse

        exc = UnexpectedResponse(
            status_code=500,
            reason_phrase="error",
            content=b"",
            headers=httpx.Headers({}),
        )
        assert _classify_backend(exc) == "qdrant"

    def test_redis_error(self):
        from redis.exceptions import ConnectionError

        exc = ConnectionError("Connection refused")
        assert _classify_backend(exc) == "redis"

    def test_memgraph_error(self):
        exc = Exception("neo4j.exceptions.ServiceUnavailable: Connection refused")
        assert _classify_backend(exc) == "memgraph"

    def test_postgres_error(self):
        exc = Exception("asyncpg.exceptions.ConnectionDoesNotExistError")
        assert _classify_backend(exc) == "postgres"

    def test_unknown_error(self):
        exc = ValueError("something else")
        assert _classify_backend(exc) == "unknown"


class TestIsRetriable:
    def test_timeout_is_retriable(self):
        exc = Exception("Connection timeout after 30s")
        assert _is_retriable(exc) is True

    def test_connection_refused_is_retriable(self):
        exc = Exception("Connection refused")
        assert _is_retriable(exc) is True

    def test_unavailable_is_retriable(self):
        exc = Exception("Service temporarily unavailable")
        assert _is_retriable(exc) is True

    def test_validation_error_not_retriable(self):
        exc = ValueError("Invalid node_id format")
        assert _is_retriable(exc) is False

    def test_auth_error_not_retriable(self):
        exc = Exception("Authentication failed")
        assert _is_retriable(exc) is False


class TestMCPBackendError:
    def test_error_attributes(self):
        exc = MCPBackendError(backend="qdrant", message="query failed", retriable=True)
        assert exc.backend == "qdrant"
        assert exc.message == "query failed"
        assert exc.retriable is True
        assert str(exc) == "query failed"

    def test_default_retriable(self):
        exc = MCPBackendError(backend="redis", message="timeout")
        assert exc.retriable is True

    def test_jsonrpc_error_code(self):
        exc = MCPBackendError(backend="qdrant", message="timeout", retriable=True)
        assert exc.jsonrpc_code == -32000

    def test_jsonrpc_error_code_non_retriable(self):
        exc = MCPBackendError(backend="postgres", message="auth failed", retriable=False)
        assert exc.jsonrpc_code == -32000


class TestMCPErrorBoundary:
    async def test_passes_through_success(self):
        @mcp_error_boundary
        async def successful_tool():
            return {"result": "ok"}

        result = await successful_tool()
        assert result == {"result": "ok"}

    async def test_wraps_backend_error_as_mcp_error(self):
        @mcp_error_boundary
        async def failing_tool():
            raise Exception("qdrant connection timeout")

        with pytest.raises(MCPBackendError) as exc_info:
            await failing_tool()
        assert exc_info.value.backend == "qdrant"
        assert exc_info.value.retriable is True
        assert exc_info.value.jsonrpc_code == -32000

    async def test_preserves_already_wrapped_error(self):
        @mcp_error_boundary
        async def tool_with_wrapped_error():
            raise MCPBackendError(backend="redis", message="explicit error", retriable=False)

        with pytest.raises(MCPBackendError) as exc_info:
            await tool_with_wrapped_error()
        assert exc_info.value.backend == "redis"
        assert exc_info.value.retriable is False

    async def test_surfaces_brain_error_message(self):
        from context_service.sage.transactions import InvariantViolation

        @mcp_error_boundary
        async def tool_with_invariant_violation():
            raise InvariantViolation(
                "NO_MEMORY_EVIDENCE",
                "At least one evidence ref must be from Memory layer (INV2)",
            )

        with pytest.raises(MCPBackendError) as exc_info:
            await tool_with_invariant_violation()
        assert exc_info.value.backend == "validation"
        assert exc_info.value.retriable is False
        assert "NO_MEMORY_EVIDENCE" in exc_info.value.message
        assert "At least one evidence ref must be from Memory layer" in exc_info.value.message

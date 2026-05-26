"""MCP error boundary: classify and wrap backend errors as JSON-RPC -32000."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable

import structlog
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from context_service.api.rate_limit import RateLimitExceeded

# JSON-RPC server error code (-32000 to -32099 are reserved for implementation-defined server errors)
_SERVER_ERROR_CODE = -32000

logger = structlog.get_logger(__name__)


def _classify_backend(e: Exception) -> str:
    """Identify which backend caused the error."""
    error_str = str(type(e).__module__) + str(type(e).__name__) + str(e)
    error_lower = error_str.lower()
    if "qdrant" in error_lower:
        return "qdrant"
    if "neo4j" in error_lower or "memgraph" in error_lower:
        return "memgraph"
    if "redis" in error_lower:
        return "redis"
    if "postgres" in error_lower or "asyncpg" in error_lower:
        return "postgres"
    return "unknown"


def _is_retriable(e: Exception) -> bool:
    """Determine if error is transient and retriable."""
    error_str = (str(type(e).__module__) + str(type(e).__name__) + str(e)).lower()
    transient_patterns = ["timeout", "connection", "unavailable", "temporary", "refused"]
    return any(p in error_str for p in transient_patterns)


class MCPBackendError(McpError):
    """Backend error that maps to JSON-RPC -32000."""

    backend: str
    message: str
    retriable: bool
    jsonrpc_code: int

    def __init__(self, backend: str, message: str, retriable: bool = True) -> None:
        self.backend = backend
        self.message = message
        self.retriable = retriable
        self.jsonrpc_code = _SERVER_ERROR_CODE
        super().__init__(
            ErrorData(
                code=_SERVER_ERROR_CODE,
                message=message,
                data={"backend": backend, "retriable": retriable},
            )
        )

    def __str__(self) -> str:
        return self.message


def mcp_error_boundary[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Wrap MCP tool handlers to catch backend errors cleanly."""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except MCPBackendError:
            raise
        except RateLimitExceeded as exc:
            logger.info(
                "mcp_rate_limit_exceeded",
                tool=func.__name__,
                retry_after=exc.retry_after,
            )
            return {  # type: ignore[return-value]
                "error": "rate_limit_exceeded",
                "message": str(exc),
                "retry_after": exc.retry_after,
                "limit": exc.limit,
            }
        except Exception as e:
            backend = _classify_backend(e)
            retriable = _is_retriable(e)
            # Log full error internally but sanitize for client response
            logger.warning(
                "mcp_tool_error",
                tool=func.__name__,
                backend=backend,
                error=str(e),
                retriable=retriable,
            )
            # Generic error message to prevent internal details leaking to clients
            safe_message = f"Backend error ({backend})"
            if retriable:
                safe_message += " - please retry"
            raise MCPBackendError(backend=backend, message=safe_message, retriable=retriable) from e

    return wrapper

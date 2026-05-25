# context_service/mcp/middleware.py
"""FastMCP-native middleware for error handling, logging, and timing.

These middleware use FastMCP's Middleware base class and hook into MCP
operations directly (not HTTP layer like Starlette middleware).

Usage:
    mcp = FastMCP("engrammic")
    mcp.add_middleware(ErrorHandlingMiddleware(mask_errors=True))
    mcp.add_middleware(LoggingMiddleware())
    mcp.add_middleware(TimingMiddleware())
"""

from __future__ import annotations

import time
import traceback
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from context_service.telemetry.metrics import record_tool_error

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class ErrorHandlingMiddleware(Middleware):
    """Catches exceptions in tool calls and returns clean error messages.

    In production, internal errors are masked to avoid leaking implementation
    details. In dev mode, full tracebacks are included.

    Args:
        mask_errors: If True, replace internal error messages with generic text.
        include_traceback: If True (and mask_errors=False), include traceback in error.
    """

    def __init__(self, mask_errors: bool = True, include_traceback: bool = False) -> None:
        self.mask_errors = mask_errors
        self.include_traceback = include_traceback

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        """Wrap tool calls with error handling."""
        tool_name = context.method or "unknown"
        try:
            return await call_next(context)
        except Exception as e:
            error_id = f"{tool_name}:{int(time.time())}"
            logger.error(
                "mcp.tool_error",
                tool=tool_name,
                error_id=error_id,
                error_type=type(e).__name__,
                error_message=str(e),
                exc_info=True,
            )
            record_tool_error(tool_name, type(e).__name__)

            if self.mask_errors:
                raise RuntimeError(
                    f"Internal error (ref: {error_id}). Check server logs for details."
                ) from None

            if self.include_traceback:
                tb = traceback.format_exc()
                raise RuntimeError(f"{type(e).__name__}: {e}\n\n{tb}") from None

            raise


class LoggingMiddleware(Middleware):
    """Logs all MCP requests and notifications.

    Logs at INFO level for successful operations, WARNING for failures.
    """

    async def on_request(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        """Log incoming requests."""
        method = context.method or "unknown"
        start = time.perf_counter()

        logger.info(
            "mcp.request.start",
            method=method,
            source=context.source,
            type=context.type,
        )

        try:
            result = await call_next(context)
            elapsed_ms = (time.perf_counter() - start) * 1000

            logger.info(
                "mcp.request.success",
                method=method,
                elapsed_ms=round(elapsed_ms, 2),
            )
            return result

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "mcp.request.failed",
                method=method,
                elapsed_ms=round(elapsed_ms, 2),
                error_type=type(e).__name__,
                error_message=str(e),
            )
            raise

    async def on_notification(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        """Log notifications (fire-and-forget messages)."""
        method = context.method or "unknown"
        logger.debug("mcp.notification", method=method, source=context.source)
        return await call_next(context)


class TimingMiddleware(Middleware):
    """Records timing metrics for MCP operations.

    Integrates with Prometheus metrics if available, otherwise logs timing.
    """

    def __init__(self, slow_threshold_ms: float = 500.0) -> None:
        """Initialize timing middleware.

        Args:
            slow_threshold_ms: Log warning if operation exceeds this threshold.
        """
        self.slow_threshold_ms = slow_threshold_ms
        self._histogram = self._get_histogram()

    def _get_histogram(self) -> Any:
        """Try to get Prometheus histogram, return None if unavailable."""
        try:
            from prometheus_client import Histogram

            from context_service.api.metrics import REGISTRY

            return Histogram(
                "mcp_tool_duration_seconds",
                "MCP tool call duration in seconds",
                ["tool"],
                registry=REGISTRY,
            )
        except Exception:
            return None

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        """Time tool calls and record metrics."""
        tool_name = context.method or "unknown"
        start = time.perf_counter()

        try:
            return await call_next(context)
        finally:
            elapsed = time.perf_counter() - start
            elapsed_ms = elapsed * 1000

            if self._histogram is not None:
                self._histogram.labels(tool=tool_name).observe(elapsed)

            if elapsed_ms > self.slow_threshold_ms:
                logger.warning(
                    "mcp.slow_tool",
                    tool=tool_name,
                    elapsed_ms=round(elapsed_ms, 2),
                    threshold_ms=self.slow_threshold_ms,
                )

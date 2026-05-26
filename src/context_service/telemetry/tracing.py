"""Tracing stubs - no-op implementations replacing OTEL tracing."""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def traced(
    name: str | None = None,
    *,
    capture_args: list[str] | None = None,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """No-op decorator replacing OTEL tracing."""

    def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def setup_tracing(service_name: str = "context-service") -> None:
    """No-op - tracing disabled."""
    pass


def instrument_fastapi(app: object) -> None:
    """No-op - FastAPI instrumentation disabled."""
    pass

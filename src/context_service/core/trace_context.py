"""Async context-var scoped trace context for structured logging correlation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TraceContext:
    org_id: str | None = None
    silo_id: str | None = None
    request_id: str | None = None
    visit_id: str | None = None
    pass_id: str | None = None
    cluster_id: str | None = None


_trace_var: ContextVar[TraceContext] = ContextVar("context_service_trace", default=TraceContext())  # noqa: B039


def current_trace() -> TraceContext:
    return _trace_var.get()


@asynccontextmanager
async def trace_scope(**overrides: str | None) -> AsyncIterator[TraceContext]:
    prev = _trace_var.get()
    new = replace(prev, **{k: v for k, v in overrides.items() if v is not None})
    token = _trace_var.set(new)
    try:
        yield new
    finally:
        _trace_var.reset(token)


def update_current_trace(**overrides: str | None) -> TraceContext:
    """Mutate the current-task trace context in place (no reset)."""
    prev = _trace_var.get()
    new = replace(prev, **{k: v for k, v in overrides.items() if v is not None})
    _trace_var.set(new)
    return new


__all__ = ["TraceContext", "current_trace", "trace_scope", "update_current_trace"]

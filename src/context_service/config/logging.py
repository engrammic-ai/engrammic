"""Logging configuration.

Ported pattern from prototype/app/core/logging.py.
Uses structlog for structured JSON logging.
"""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from dagster import AssetExecutionContext

# Dagster context for log bridging
_dagster_context: ContextVar["AssetExecutionContext | None"] = ContextVar(
    "dagster_context", default=None
)


def configure_logging(log_level: str = "INFO", json_format: bool = True) -> None:
    """Configure structlog for the application.

    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: If True, output JSON; if False, output console-friendly format
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _dagster_bridge,
    ]

    if json_format:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger instance."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def set_dagster_context(ctx: "AssetExecutionContext | None") -> None:
    """Set Dagster context for log bridging."""
    _dagster_context.set(ctx)


def _dagster_bridge(
    _logger: logging.Logger, method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """Processor that forwards logs to Dagster context if available."""
    ctx = _dagster_context.get()
    if ctx is not None:
        event = event_dict.get("event", "")
        extra = {k: v for k, v in event_dict.items() if k not in ("event", "level", "timestamp")}
        msg = f"{event} {extra}" if extra else event
        getattr(ctx.log, method_name, ctx.log.info)(msg)
    return event_dict

"""Taskiq worker configuration for reaction event processing.

This module provides middleware and startup/shutdown hooks for the Taskiq
worker process. The worker itself is launched via `taskiq worker`; this
module is imported by the entry-point to configure the broker before the
worker loop starts.

Usage::

    from context_service.reactions.broker import get_broker
    from context_service.reactions.worker import configure_worker

    broker = get_broker(silo_id="default")
    configure_worker(broker, concurrency=4)
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

import structlog
from opentelemetry import trace
from taskiq import TaskiqEvents, TaskiqMessage, TaskiqMiddleware, TaskiqResult, TaskiqState
from taskiq_redis import ListQueueBroker

from context_service.config.settings import get_settings

logger = structlog.get_logger(__name__)

tracer = trace.get_tracer(__name__)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class LoggingMiddleware(TaskiqMiddleware):
    """Add structlog context to every task execution.

    Binds ``task_name``, ``task_id``, and ``silo_id`` (when present in
    labels) into the structlog context for the duration of each task so
    that all downstream log calls carry those fields automatically.
    """

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Bind task metadata into structlog context before execution."""
        silo_id = message.labels.get("silo_id") or _extract_silo_from_args(message)
        structlog.contextvars.bind_contextvars(
            task_name=message.task_name,
            task_id=message.task_id,
            silo_id=silo_id,
        )
        logger.debug("task_pre_execute", task_name=message.task_name, task_id=message.task_id)
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Clear structlog context and log completion after execution."""
        if result.is_err:
            logger.warning(
                "task_post_execute_error",
                task_name=message.task_name,
                task_id=message.task_id,
                error=repr(result.error),
            )
        else:
            logger.debug(
                "task_post_execute_ok",
                task_name=message.task_name,
                task_id=message.task_id,
            )
        structlog.contextvars.unbind_contextvars("task_name", "task_id", "silo_id")


class TracingMiddleware(TaskiqMiddleware):
    """Wrap task execution in an OpenTelemetry span.

    Creates a span for each task execution. The span carries ``task.name``
    and ``task.id`` as attributes. If OpenTelemetry is not configured (no
    exporter), the span is a no-op, so this middleware is always safe to
    include.
    """

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Start a span and store its token in the message labels."""
        # Purge stale entries if dict is getting large (prevents memory leak
        # from tasks that crash without calling post_execute).
        if len(_active_spans) > _MAX_ACTIVE_SPANS:
            _purge_stale_spans()

        span = tracer.start_span(
            name=f"taskiq.{message.task_name}",
            attributes={
                "task.name": message.task_name,
                "task.id": message.task_id,
            },
        )
        # Attach span to current context and store context token so
        # post_execute can end the span. We store the span object in a
        # module-level dict keyed by task_id to avoid pydantic-model
        # mutations on TaskiqMessage.
        _active_spans[message.task_id] = (span, time.monotonic())
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """End the span that was started in pre_execute."""
        entry = _active_spans.pop(message.task_id, None)
        if entry is None:
            return
        span, started_at = entry
        elapsed_ms = (time.monotonic() - started_at) * 1000
        if result.is_err:
            span.set_attribute("task.error", repr(result.error))
            span.set_status(trace.StatusCode.ERROR)
        span.set_attribute("task.duration_ms", round(elapsed_ms, 2))
        span.end()

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],  # noqa: ARG002
        exception: BaseException,
    ) -> None:
        """Record the exception on the active span if one exists."""
        entry = _active_spans.get(message.task_id)
        if entry is None:
            return
        span, _ = entry
        span.record_exception(exception)
        span.set_status(trace.StatusCode.ERROR, description=str(exception))


# Module-level storage for in-flight spans so we can close them in
# post_execute without needing to mutate TaskiqMessage.
# Entries are cleaned up in post_execute; stale entries (from crashed tasks)
# are purged when the dict exceeds _MAX_ACTIVE_SPANS.
_active_spans: dict[str, tuple[trace.Span, float]] = {}
_MAX_ACTIVE_SPANS = 1000
_STALE_SPAN_SECONDS = 3600.0  # 1 hour


def _purge_stale_spans() -> None:
    """Remove spans older than _STALE_SPAN_SECONDS from _active_spans.

    Called when _active_spans exceeds _MAX_ACTIVE_SPANS to prevent unbounded
    memory growth from tasks that crash without calling post_execute.
    """
    now = time.monotonic()
    stale_ids = [
        task_id
        for task_id, (_, started_at) in _active_spans.items()
        if now - started_at > _STALE_SPAN_SECONDS
    ]
    for task_id in stale_ids:
        entry = _active_spans.pop(task_id, None)
        if entry:
            span, _ = entry
            span.set_status(trace.StatusCode.ERROR, description="span_purged_as_stale")
            span.end()
    if stale_ids:
        logger.warning("purged_stale_spans", count=len(stale_ids))


# ---------------------------------------------------------------------------
# Worker event handlers
# ---------------------------------------------------------------------------


def _register_worker_hooks(broker: ListQueueBroker) -> None:
    """Register WORKER_STARTUP and WORKER_SHUTDOWN hooks on ``broker``."""

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def _on_worker_startup(state: TaskiqState) -> None:
        settings = get_settings()
        logger.info(
            "worker_startup",
            app=settings.app_name,
            environment=settings.environment,
        )

        # Initialise Sentry if a DSN is available in the environment.
        sentry_dsn = _get_sentry_dsn()
        if sentry_dsn:
            try:
                import importlib

                sentry_sdk = importlib.import_module("sentry_sdk")
                sentry_sdk.init(
                    dsn=sentry_dsn,
                    environment=settings.environment,
                    release=settings.version,
                )
                state.sentry_enabled = True
                logger.info("sentry_initialised", environment=settings.environment)
            except ImportError:
                logger.warning("sentry_sdk_not_installed_skipping")
                state.sentry_enabled = False
        else:
            state.sentry_enabled = False

        # Initialize telemetry metrics buffer
        from context_service.telemetry.metrics import setup_metrics

        setup_metrics()
        logger.info("worker_metrics_initialized")

        # Initialise service layer so task handlers can call get_context_service().
        try:
            from context_service.embeddings import build_embedding_service
            from context_service.engine.memgraph_store import MemgraphStore
            from context_service.mcp.server import configure_services
            from context_service.stores import (
                MemgraphClient,
                QdrantClient,
                RedisClient,
                create_memgraph_driver,
                create_redis_pool,
            )

            memgraph_driver = await create_memgraph_driver(settings)
            memgraph_client = MemgraphClient(memgraph_driver)
            logger.info("worker_memgraph_connected")

            redis_pool = await create_redis_pool(settings)
            redis_client = RedisClient(redis_pool)
            logger.info("worker_redis_connected")

            # Initialize embedding rate limiter for distributed coordination
            from context_service.config.config_loader import load_config
            from context_service.config.settings import ModelRateLimitConfig
            from context_service.embeddings import set_embedding_rate_limiter

            embeddings_config = load_config("embeddings")
            rate_limit_dict = embeddings_config.get("rate_limit", {})
            rate_limit_config = ModelRateLimitConfig(**rate_limit_dict)
            set_embedding_rate_limiter(
                redis=redis_client,
                config=rate_limit_config,
                requests_per_minute=rate_limit_config.requests_per_minute,
            )
            logger.info(
                "worker_embedding_rate_limiter_configured",
                rpm=rate_limit_config.requests_per_minute,
                max_concurrent=rate_limit_config.max_concurrent_requests,
            )

            qdrant_client = QdrantClient.from_settings(settings)
            await qdrant_client.ensure_collection(hybrid=settings.hybrid_search_enabled)
            logger.info("worker_qdrant_connected")

            embedding_service = None
            try:
                from context_service.cache.embedding_cache import EmbeddingCache

                embedding_cache = EmbeddingCache(redis_client)
                embedding_service = build_embedding_service(embedding_cache)
                logger.info("worker_embedding_service_configured")
            except Exception as exc:
                logger.warning(
                    "worker_embedding_service_unconfigured",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    hint="create config/embeddings.yaml to enable semantic search",
                )

            memgraph_store = MemgraphStore(memgraph_client)
            configure_services(
                memgraph=memgraph_store,
                qdrant=qdrant_client,
                redis=redis_client,
                embedding=embedding_service,
            )

            state.qdrant = qdrant_client
            state.memgraph_driver = memgraph_driver
            state.redis_pool = redis_pool
            logger.info("worker_services_configured")
        except Exception as exc:
            logger.error(
                "worker_service_init_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            # Worker continues in degraded mode; task handlers will log errors.

        # Set up metrics flushing to postgres
        try:
            import asyncio

            import asyncpg

            from context_service.telemetry.flush import flush_metrics_to_db
            from context_service.telemetry.metrics import get_buffer, set_db_pool

            pg_pool = await asyncpg.create_pool(settings.postgres_dsn)
            set_db_pool(pg_pool)
            state.pg_pool = pg_pool

            async def periodic_flush() -> None:
                while True:
                    await asyncio.sleep(60)
                    buffer = get_buffer()
                    if buffer is not None and pg_pool is not None:
                        try:
                            await flush_metrics_to_db(pg_pool, buffer)
                        except Exception:
                            logger.warning("worker_metrics_flush_failed")

            state.metrics_flush_task = asyncio.create_task(periodic_flush())
            logger.info("worker_metrics_flush_started")
        except Exception as exc:
            logger.warning(
                "worker_metrics_flush_setup_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        state.started_at = time.monotonic()
        logger.info("worker_startup_complete")

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def _on_worker_shutdown(state: TaskiqState) -> None:
        uptime_s = time.monotonic() - getattr(state, "started_at", time.monotonic())
        logger.info("worker_shutdown", uptime_seconds=round(uptime_s, 1))

        # Close database connections
        if hasattr(state, "memgraph_driver") and state.memgraph_driver is not None:
            try:
                await state.memgraph_driver.close()
                logger.info("worker_memgraph_closed")
            except Exception:
                logger.warning("worker_memgraph_close_failed")

        if hasattr(state, "redis_pool") and state.redis_pool is not None:
            try:
                await state.redis_pool.aclose()
                logger.info("worker_redis_closed")
            except Exception:
                logger.warning("worker_redis_close_failed")

        # Final metrics flush before shutdown
        if hasattr(state, "metrics_flush_task"):
            state.metrics_flush_task.cancel()
            with contextlib.suppress(Exception):
                await state.metrics_flush_task

        if hasattr(state, "pg_pool") and state.pg_pool is not None:
            try:
                from context_service.telemetry.flush import flush_metrics_to_db
                from context_service.telemetry.metrics import get_buffer

                buffer = get_buffer()
                if buffer is not None:
                    await flush_metrics_to_db(state.pg_pool, buffer)
                await state.pg_pool.close()
                logger.info("worker_metrics_flushed_and_pg_closed")
            except Exception:
                logger.warning("worker_pg_close_failed")

        if getattr(state, "sentry_enabled", False):
            try:
                import importlib

                sentry_sdk = importlib.import_module("sentry_sdk")
                sentry_sdk.flush(timeout=5)
            except Exception:
                logger.warning("sentry_flush_failed")

        logger.info("worker_shutdown_complete")


# ---------------------------------------------------------------------------
# Health check task
# ---------------------------------------------------------------------------


def _register_health_check(broker: ListQueueBroker) -> None:
    """Register a lightweight health-check task on ``broker``.

    The task pings the Redis connection and returns a status dict.
    External monitors (Dagster sensors, uptime checks) can kick this task
    and inspect the result to verify the worker is alive and connected.
    """

    @broker.task(task_name="worker.health_check")
    async def health_check_task() -> dict[str, Any]:
        """Verify the worker is alive and Redis is reachable.

        Returns:
            A dict with ``status`` ("ok" or "degraded"), ``timestamp``, and
            ``redis_ping`` boolean.
        """
        redis_ok = False
        try:
            from redis.asyncio import Redis as AsyncRedis

            settings = get_settings()
            async with AsyncRedis.from_url(settings.redis_url, socket_timeout=2) as r:
                # redis-py stubs declare ping() as Awaitable[bool] | bool;
                # in the asyncio client it always returns a coroutine.
                ping_result: bool = await r.ping()  # type: ignore[misc]
                redis_ok = bool(ping_result)
        except Exception as exc:
            logger.warning("health_check_redis_ping_failed", error=repr(exc))

        status = "ok" if redis_ok else "degraded"
        logger.info("health_check", status=status, redis_ok=redis_ok)
        return {
            "status": status,
            "redis_ok": redis_ok,
            "timestamp": time.time(),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_worker(
    broker: ListQueueBroker,
    concurrency: int = 4,
) -> None:
    """Configure middleware, hooks, and concurrency on ``broker``.

    Call this before starting the Taskiq worker loop.  The `taskiq worker`
    CLI picks up the broker module path; calling ``configure_worker`` in that
    module's top-level ensures configuration is applied at import time.

    Args:
        broker: A silo-partitioned ``ListQueueBroker`` from ``get_broker()``.
        concurrency: Number of concurrent task workers (default: 4).
    """
    # Worker concurrency is set as a broker attribute that the Taskiq
    # `WorkerSettings` / CLI picks up via `--workers` flag or this attribute.
    # Storing it here so the deployment layer can read it back.
    broker.is_worker_process = True  # mark as worker so middleware activates

    broker.add_middlewares(LoggingMiddleware(), TracingMiddleware())
    _register_worker_hooks(broker)
    _register_health_check(broker)

    settings = get_settings()
    logger.info(
        "worker_configured",
        concurrency=concurrency,
        environment=settings.environment,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_sentry_dsn() -> str | None:
    """Return the Sentry DSN from the environment, or None.

    Checks the ``SENTRY_DSN`` environment variable directly since
    ``Settings`` does not declare a ``sentry_dsn`` field.
    """
    import os

    return os.environ.get("SENTRY_DSN") or None


def _extract_silo_from_args(message: TaskiqMessage) -> str | None:
    """Best-effort extraction of ``silo_id`` from task kwargs.

    Most task handlers accept ``silo_id`` as a keyword argument. This helper
    reads it from the raw message args so ``LoggingMiddleware`` can include it
    in the structlog context even when it is not present in the labels dict.

    Args:
        message: The incoming Taskiq message.

    Returns:
        The ``silo_id`` string if found, else ``None``.
    """
    kwargs = message.kwargs if isinstance(message.kwargs, dict) else {}
    silo_id = kwargs.get("silo_id")
    return str(silo_id) if silo_id is not None else None

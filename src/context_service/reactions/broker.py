"""Taskiq broker setup for reaction queues.

Uses a single shared queue for all silos. Silo isolation is enforced at the
task level via the ``silo_id`` kwarg, not at the queue level. This simplifies
worker deployment (one worker pool serves all tenants) while maintaining
logical isolation in task handlers.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import structlog
from taskiq import (
    BrokerMessage,
    SmartRetryMiddleware,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqResult,
)
from taskiq_redis import ListQueueBroker

from context_service.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Retry policy constants
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS: float = 5.0
_MAX_DELAY_SECONDS: float = 60.0


class DeadLetterMiddleware(TaskiqMiddleware):
    """Push exhausted tasks to the dead letter queue.

    The SmartRetryMiddleware increments ``_retries`` and re-kicks the task
    when ``retries < max_retries``. When retries are exhausted it logs a
    warning and returns without sending -- leaving the result in place.
    This middleware's ``on_error`` hook runs *after* the retry middleware
    has already decided not to retry, so by the time we reach the
    exhaustion branch the label state mirrors what SmartRetryMiddleware
    computed.  We replicate the same exhaustion condition so we only push
    to the DLQ on the final failure, not on transient errors that will be
    retried.
    """

    def __init__(self, dlq_name: str) -> None:
        super().__init__()
        self._dlq_name = dlq_name
        self._dlq_broker: ListQueueBroker | None = None
        self._startup_lock = asyncio.Lock()
        self._started = False

    def set_broker(self, broker: ListQueueBroker) -> None:
        super().set_broker(broker)
        settings = get_settings()
        self._dlq_broker = ListQueueBroker(
            url=settings.redis_url,
            queue_name=self._dlq_name,
            max_connection_pool_size=settings.redis_max_connections,
        )

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],  # noqa: ARG002
        exception: BaseException,
    ) -> None:
        """Route exhausted tasks to the dead letter queue.

        Only acts when retries are exhausted (mirrors SmartRetryMiddleware
        logic to avoid double-pushing mid-retry failures).
        """
        retries = int(message.labels.get("_retries", 0)) + 1
        max_retries = int(message.labels.get("max_retries", _MAX_RETRIES))

        if retries < max_retries:
            # Not exhausted yet -- retry middleware will re-kick.
            return

        if self._dlq_broker is None:
            logger.warning(
                "dlq_broker_not_initialised",
                task_name=message.task_name,
                task_id=message.task_id,
            )
            return

        try:
            async with self._startup_lock:
                if not self._started and not self._dlq_broker.is_worker_process:
                    await self._dlq_broker.startup()
                    self._started = True

            updated_labels = {
                **message.labels,
                "_dlq_reason": repr(exception),
            }
            dlq_message = BrokerMessage(
                task_id=message.task_id,
                task_name=message.task_name,
                message=message.model_dump_json().encode(),
                labels=updated_labels,
            )
            await self._dlq_broker.kick(dlq_message)
            logger.warning(
                "task_sent_to_dlq",
                task_name=message.task_name,
                task_id=message.task_id,
                retries=retries,
                dlq=self._dlq_name,
            )
        except Exception:
            logger.exception(
                "failed_to_send_to_dlq",
                task_name=message.task_name,
                task_id=message.task_id,
            )


def _build_broker() -> ListQueueBroker:
    """Construct a configured broker for reaction events.

    Uses a single shared queue for all silos. Silo isolation is enforced
    at the task level via the ``silo_id`` kwarg passed to each handler.
    """
    settings = get_settings()
    queue_name = "reactions:default"
    dlq_name = "reactions:dlq"

    broker = ListQueueBroker(
        url=settings.redis_url,
        queue_name=queue_name,
        max_connection_pool_size=settings.redis_max_connections,
    )

    retry_middleware = SmartRetryMiddleware(
        default_retry_count=_MAX_RETRIES,
        default_retry_label=True,
        default_delay=_BASE_DELAY_SECONDS,
        use_delay_exponent=True,
        use_jitter=True,
        max_delay_exponent=_MAX_DELAY_SECONDS,
    )

    dlq_middleware = DeadLetterMiddleware(dlq_name=dlq_name)

    # Order matters: retry middleware must evaluate exhaustion before DLQ
    # middleware pushes. Both hooks are called in registration order.
    broker.add_middlewares(retry_middleware, dlq_middleware)

    # Register all reaction task handlers onto the broker so find_task resolves
    # correctly at emit time. Imported here to avoid a circular import (tasks
    # imports broker constants; broker imports tasks only after the broker is
    # built).
    from context_service.reactions.tasks import register_tasks

    register_tasks(broker)

    return broker


@lru_cache(maxsize=1)
def get_broker() -> ListQueueBroker:
    """Return the cached Taskiq broker for reaction events.

    Returns a singleton broker instance. All silos share the same queue;
    silo isolation is enforced at the task level via the ``silo_id`` kwarg.

    Returns:
        A configured ``ListQueueBroker`` backed by Redis.
    """
    return _build_broker()

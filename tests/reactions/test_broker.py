"""Tests for broker factory and dead letter middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from taskiq import InMemoryBroker, TaskiqMessage

from context_service.reactions.broker import (
    _MAX_RETRIES,
    DeadLetterMiddleware,
    get_broker,
)
from context_service.reactions.events import ReactionEventType

# ---------------------------------------------------------------------------
# Broker factory
# ---------------------------------------------------------------------------


class TestGetBroker:
    def test_returns_broker(self) -> None:
        with patch("context_service.reactions.broker.ListQueueBroker") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.add_middlewares = MagicMock()
            mock_cls.return_value = mock_instance
            with patch("context_service.reactions.tasks.register_tasks"):
                broker = get_broker()
        assert broker is not None

    def test_returns_cached_singleton(self) -> None:
        with (
            patch("context_service.reactions.broker.ListQueueBroker") as mock_cls,
            patch("context_service.reactions.tasks.register_tasks"),
        ):
            instance = MagicMock()
            instance.add_middlewares = MagicMock()
            mock_cls.return_value = instance

            first = get_broker()
            second = get_broker()

        assert first is second

    def test_uses_shared_queue_name(self) -> None:
        """All silos share a single queue; silo isolation is at task level."""
        captured_kwargs: list[dict] = []

        def capture(*args: object, **kwargs: object) -> MagicMock:
            captured_kwargs.append(kwargs)
            m = MagicMock()
            m.add_middlewares = MagicMock()
            return m

        with (
            patch(
                "context_service.reactions.broker.ListQueueBroker",
                side_effect=capture,
            ),
            patch("context_service.reactions.tasks.register_tasks"),
        ):
            get_broker.cache_clear()
            get_broker()

        main_queue_call = captured_kwargs[0]
        assert main_queue_call.get("queue_name") == "reactions:default"

    def test_uses_shared_dlq_name(self) -> None:
        middlewares_added: list = []

        def capture_broker(*args: object, **kwargs: object) -> MagicMock:
            m = MagicMock()
            m.add_middlewares = MagicMock(side_effect=lambda *mws: middlewares_added.extend(mws))
            return m

        with (
            patch(
                "context_service.reactions.broker.ListQueueBroker",
                side_effect=capture_broker,
            ),
            patch("context_service.reactions.tasks.register_tasks"),
        ):
            get_broker.cache_clear()
            get_broker()

        dlq_mw = next(
            (mw for mw in middlewares_added if isinstance(mw, DeadLetterMiddleware)),
            None,
        )
        assert dlq_mw is not None
        assert dlq_mw._dlq_name == "reactions:dlq"


# ---------------------------------------------------------------------------
# Tasks registered on broker
# ---------------------------------------------------------------------------


class TestBrokerTaskRegistration:
    # Event types that have concrete task handlers registered in Phase 8a.
    # CASCADE_STALENESS_COMPLETE, CONFLICT_DETECTED, and CHECK_EXTRACTION_TRIGGER
    # are notification/signal-only enum members with no handler by design (Phase 8a
    # plan, Task 3 table); they will remain handler-less until Phase 9.
    _HANDLER_BACKED = frozenset(
        {
            ReactionEventType.COMPUTE_EMBEDDING,
            ReactionEventType.UPDATE_HEAT,
            ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP,
            ReactionEventType.CASCADE_STALENESS,
            ReactionEventType.FLAG_CONTRADICTION,
            ReactionEventType.CONSOLIDATE,
            ReactionEventType.CHECK_SYNTHESIS,
            ReactionEventType.PROPAGATE_CONFIDENCE,
        }
    )

    def test_handler_backed_event_types_registered(self, in_memory_broker: InMemoryBroker) -> None:
        """Every handler-backed ReactionEventType should resolve via find_task."""
        for event_type in self._HANDLER_BACKED:
            task = in_memory_broker.find_task(event_type)
            assert task is not None, f"Task not registered: {event_type}"

    def test_notification_only_event_types_not_registered(self, in_memory_broker: InMemoryBroker) -> None:
        """Notification-only enum members have no registered handler in Phase 8a."""
        notification_only = set(ReactionEventType) - self._HANDLER_BACKED
        for event_type in notification_only:
            task = in_memory_broker.find_task(event_type)
            assert task is None, f"Unexpected handler for notification-only type: {event_type}"


# ---------------------------------------------------------------------------
# DeadLetterMiddleware
# ---------------------------------------------------------------------------


def _make_message(task_id: str, task_name: str, labels: dict) -> TaskiqMessage:
    return TaskiqMessage(
        task_id=task_id,
        task_name=task_name,
        labels=labels,
        args=[],
        kwargs={},
    )


class TestDeadLetterMiddleware:
    @pytest.mark.asyncio
    async def test_not_exhausted_does_not_push_to_dlq(self) -> None:
        """When retries are not exhausted, DLQ is not called."""
        mw = DeadLetterMiddleware(dlq_name="test:dlq")
        dlq_broker = AsyncMock()
        mw._dlq_broker = dlq_broker

        message = _make_message(
            task_id="t1",
            task_name="some.task",
            labels={"_retries": 0, "max_retries": _MAX_RETRIES},
        )
        result = MagicMock()
        await mw.on_error(message, result, RuntimeError("boom"))

        dlq_broker.kick.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exhausted_pushes_to_dlq(self) -> None:
        """When retries are exhausted (retries == max_retries), task goes to DLQ."""
        mw = DeadLetterMiddleware(dlq_name="test:dlq")
        dlq_broker = AsyncMock()
        dlq_broker.is_worker_process = True
        # Provide a minimal formatter mock
        formatter = MagicMock()
        formatter.dumps = MagicMock(return_value=b"serialised")
        dlq_broker.formatter = formatter
        mw._dlq_broker = dlq_broker

        # _retries=2, max_retries=3 -> retries=3, NOT < 3 -> exhausted
        message = _make_message(
            task_id="t2",
            task_name="some.task",
            labels={"_retries": 2, "max_retries": _MAX_RETRIES},
        )
        result = MagicMock()
        exc = RuntimeError("terminal failure")
        await mw.on_error(message, result, exc)

        dlq_broker.kick.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exhausted_dlq_message_contains_reason(self) -> None:
        """DLQ message labels include '_dlq_reason' with the exception repr."""
        mw = DeadLetterMiddleware(dlq_name="test:dlq")
        dlq_broker = AsyncMock()
        dlq_broker.is_worker_process = True
        captured: list[object] = []

        async def capture_kick(payload: object) -> None:
            captured.append(payload)

        dlq_broker.kick = capture_kick

        formatter = MagicMock()
        formatter.dumps = MagicMock(side_effect=lambda msg: msg)  # pass-through
        dlq_broker.formatter = formatter
        mw._dlq_broker = dlq_broker

        message = _make_message(
            task_id="t3",
            task_name="some.task",
            labels={"_retries": 2, "max_retries": _MAX_RETRIES},
        )
        exc = ValueError("specific error")
        await mw.on_error(message, MagicMock(), exc)

        assert len(captured) == 1
        sent = captured[0]
        # formatter.dumps receives the updated message copy
        assert "_dlq_reason" in sent.labels
        assert "specific error" in sent.labels["_dlq_reason"]

    @pytest.mark.asyncio
    async def test_none_dlq_broker_logs_warning_and_does_not_raise(self) -> None:
        """If DLQ broker was never set, on_error should not raise."""
        mw = DeadLetterMiddleware(dlq_name="test:dlq")
        # _dlq_broker remains None

        message = _make_message(
            task_id="t4",
            task_name="some.task",
            labels={"_retries": 2, "max_retries": _MAX_RETRIES},
        )
        # Should complete without exception
        await mw.on_error(message, MagicMock(), RuntimeError("fail"))

    @pytest.mark.asyncio
    async def test_boundary_just_below_exhaustion(self) -> None:
        """Retry at _retries=1 with max_retries=3 is NOT exhausted."""
        mw = DeadLetterMiddleware(dlq_name="test:dlq")
        dlq_broker = AsyncMock()
        mw._dlq_broker = dlq_broker

        message = _make_message(
            task_id="t5",
            task_name="some.task",
            labels={"_retries": 1, "max_retries": _MAX_RETRIES},
        )
        await mw.on_error(message, MagicMock(), RuntimeError("transient"))

        dlq_broker.kick.assert_not_awaited()

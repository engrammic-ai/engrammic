"""Tests for ReactionEvent schema and emit_reaction helper."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reactions.events import (
    _EMIT_TIMEOUT_SECONDS,
    ReactionEvent,
    ReactionEventType,
    emit_reaction,
)

# ---------------------------------------------------------------------------
# ReactionEventType
# ---------------------------------------------------------------------------


class TestReactionEventType:
    def test_is_str_enum(self) -> None:
        assert isinstance(ReactionEventType.COMPUTE_EMBEDDING, str)

    def test_string_values_match_names(self) -> None:
        # StrEnum values should be usable directly as strings (for Taskiq task names)
        assert ReactionEventType.COMPUTE_EMBEDDING == "compute_embedding"
        assert ReactionEventType.CASCADE_STALENESS == "cascade_staleness"
        assert ReactionEventType.UPDATE_HEAT == "update_heat"
        assert ReactionEventType.FLAG_CONTRADICTION == "flag_contradiction"
        assert ReactionEventType.CONSOLIDATE == "consolidate"
        assert ReactionEventType.CHECK_SYNTHESIS == "check_synthesis"
        assert ReactionEventType.PROPAGATE_CONFIDENCE == "propagate_confidence"

    def test_all_expected_members_present(self) -> None:
        expected = {
            "COMPUTE_EMBEDDING",
            "CASCADE_STALENESS",
            "CASCADE_STALENESS_COMPLETE",
            "UPDATE_HEAT",
            "UPDATE_CLUSTER_MEMBERSHIP",
            "FLAG_CONTRADICTION",
            "CONFLICT_DETECTED",
            "CHECK_SYNTHESIS",
            "CHECK_EXTRACTION_TRIGGER",
            "PROPAGATE_CONFIDENCE",
            "CONSOLIDATE",
        }
        actual = {m.name for m in ReactionEventType}
        assert expected == actual


# ---------------------------------------------------------------------------
# ReactionEvent
# ---------------------------------------------------------------------------


class TestReactionEvent:
    def test_basic_creation(self) -> None:
        node_id = str(uuid.uuid4())
        silo_id = "test-silo"
        event = ReactionEvent(
            event_type=ReactionEventType.COMPUTE_EMBEDDING,
            node_id=node_id,
            silo_id=silo_id,
        )
        assert event.event_type == ReactionEventType.COMPUTE_EMBEDDING
        assert event.node_id == node_id
        assert event.silo_id == silo_id
        assert event.payload == {}

    def test_created_at_defaults_to_utc_now(self) -> None:
        before = datetime.now(UTC)
        event = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="silo-x",
        )
        after = datetime.now(UTC)
        assert before <= event.created_at <= after
        assert event.created_at.tzinfo is not None

    def test_payload_stored(self) -> None:
        event = ReactionEvent(
            event_type=ReactionEventType.FLAG_CONTRADICTION,
            node_id=str(uuid.uuid4()),
            silo_id="silo-x",
            payload={"conflict_node_id": "abc", "severity": "high"},
        )
        assert event.payload["conflict_node_id"] == "abc"
        assert event.payload["severity"] == "high"

    def test_accepts_plain_string_event_type(self) -> None:
        event = ReactionEvent(
            event_type="custom_event",
            node_id=str(uuid.uuid4()),
            silo_id="silo-x",
        )
        assert event.event_type == "custom_event"

    def test_different_events_do_not_share_payload(self) -> None:
        e1 = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="s1",
        )
        e2 = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="s2",
        )
        e1.payload["key"] = "value"
        assert "key" not in e2.payload


# ---------------------------------------------------------------------------
# emit_reaction
# ---------------------------------------------------------------------------


def _make_broker_with_kicker(kiq_coro: AsyncMock | None = None) -> MagicMock:
    """Build a minimal broker mock with find_task returning a kicker."""
    kicker = MagicMock()
    if kiq_coro is None:
        kiq_coro = AsyncMock(return_value=None)
    kicker.kiq = kiq_coro

    broker = MagicMock()
    broker.find_task = MagicMock(return_value=kicker)
    return broker


class TestEmitReaction:
    @pytest.mark.asyncio
    async def test_emit_calls_kiq_with_node_and_silo(self) -> None:
        kiq = AsyncMock(return_value=None)
        broker = _make_broker_with_kicker(kiq)
        node_id = str(uuid.uuid4())
        silo_id = "emit-silo"
        event = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=node_id,
            silo_id=silo_id,
            payload={"delta": 2.5},
        )

        with patch("context_service.reactions.broker.get_broker", return_value=broker):
            await emit_reaction(event)

        kiq.assert_awaited_once_with(node_id=node_id, silo_id=silo_id, delta=2.5)

    @pytest.mark.asyncio
    async def test_emit_uses_silo_broker(self) -> None:
        broker = _make_broker_with_kicker()
        silo_id = "specific-silo-" + uuid.uuid4().hex[:6]
        event = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id=silo_id,
        )

        with patch("context_service.reactions.broker.get_broker", return_value=broker) as mock_get_broker:
            await emit_reaction(event)

        mock_get_broker.assert_called_once_with(silo_id)

    @pytest.mark.asyncio
    async def test_emit_task_not_registered_logs_warning_and_returns(self) -> None:
        broker = MagicMock()
        broker.find_task = MagicMock(return_value=None)
        event = ReactionEvent(
            event_type="unregistered_event",
            node_id=str(uuid.uuid4()),
            silo_id="silo-x",
        )

        # Should not raise, just warn
        with patch("context_service.reactions.broker.get_broker", return_value=broker):
            await emit_reaction(event)

        # find_task was called but kiq was never called
        broker.find_task.assert_called_once_with("unregistered_event")

    @pytest.mark.asyncio
    async def test_emit_timeout_does_not_propagate(self) -> None:
        async def slow_kiq(**_kwargs: object) -> None:
            await asyncio.sleep(10)

        kicker = MagicMock()
        kicker.kiq = slow_kiq
        broker = MagicMock()
        broker.find_task = MagicMock(return_value=kicker)

        event = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="silo-x",
        )

        # Patch timeout to near-zero so the test runs fast
        with (
            patch("context_service.reactions.broker.get_broker", return_value=broker),
            patch("context_service.reactions.events._EMIT_TIMEOUT_SECONDS", 0.01),
        ):
            # emit_reaction must not raise even on timeout
            await emit_reaction(event)

    @pytest.mark.asyncio
    async def test_emit_broker_exception_does_not_propagate(self) -> None:
        async def raise_kiq(**_kwargs: object) -> None:
            raise ConnectionError("Redis down")

        kicker = MagicMock()
        kicker.kiq = raise_kiq
        broker = MagicMock()
        broker.find_task = MagicMock(return_value=kicker)

        event = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="silo-x",
        )

        # Exceptions from the broker must be swallowed
        with patch("context_service.reactions.broker.get_broker", return_value=broker):
            await emit_reaction(event)

    @pytest.mark.asyncio
    async def test_emit_timeout_constant_in_expected_range(self) -> None:
        # Defensive: ensure the module constant is sane (fire-and-forget should be fast)
        assert 0 < _EMIT_TIMEOUT_SECONDS <= 5.0

    @pytest.mark.asyncio
    async def test_silo_isolation_different_silos_use_different_brokers(self) -> None:
        """emit_reaction uses get_broker(silo_id), so different silos are isolated."""
        brokers_called: list[str] = []

        def mock_get_broker(silo_id: str) -> MagicMock:
            brokers_called.append(silo_id)
            b = MagicMock()
            kicker = MagicMock()
            kicker.kiq = AsyncMock(return_value=None)
            b.find_task = MagicMock(return_value=kicker)
            return b

        event_a = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="silo-alpha",
        )
        event_b = ReactionEvent(
            event_type=ReactionEventType.UPDATE_HEAT,
            node_id=str(uuid.uuid4()),
            silo_id="silo-beta",
        )

        with patch("context_service.reactions.broker.get_broker", side_effect=mock_get_broker):
            await emit_reaction(event_a)
            await emit_reaction(event_b)

        assert "silo-alpha" in brokers_called
        assert "silo-beta" in brokers_called
        assert brokers_called[0] != brokers_called[1]

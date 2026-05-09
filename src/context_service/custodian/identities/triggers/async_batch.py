from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from context_service.custodian.identities.triggers.protocols import CustodianTrigger

OnFireCallback = Callable[[str, list[str]], Awaitable[None]]


@dataclass
class AsyncBatchTrigger(CustodianTrigger):
    """Micro-batch trigger: fires on batch_size OR window_seconds, whichever first."""

    batch_size: int = 5
    window_seconds: float = 2.0
    on_fire: OnFireCallback | None = None

    _queues: dict[str, list[str]] = field(default_factory=dict, init=False)
    _timers: dict[str, asyncio.TimerHandle] = field(default_factory=dict, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def enqueue(self, silo_id: str, node_id: str, event_type: str) -> None:
        async with self._lock:
            if silo_id not in self._queues:
                self._queues[silo_id] = []

            self._queues[silo_id].append(node_id)

            if len(self._queues[silo_id]) >= self.batch_size:
                await self._fire(silo_id)
            elif silo_id not in self._timers:
                self._schedule_timer(silo_id)

    async def flush(self, silo_id: str) -> list[str]:
        async with self._lock:
            node_ids = self._queues.pop(silo_id, [])
            self._cancel_timer(silo_id)
            return node_ids

    async def _fire(self, silo_id: str) -> None:
        node_ids = self._queues.pop(silo_id, [])
        self._cancel_timer(silo_id)

        if node_ids and self.on_fire:
            await self.on_fire(silo_id, node_ids)

    def _schedule_timer(self, silo_id: str) -> None:
        loop = asyncio.get_event_loop()
        self._timers[silo_id] = loop.call_later(
            self.window_seconds,
            lambda: asyncio.create_task(self._fire_from_timer(silo_id)),
        )

    async def _fire_from_timer(self, silo_id: str) -> None:
        async with self._lock:
            if silo_id in self._queues:
                await self._fire(silo_id)

    def _cancel_timer(self, silo_id: str) -> None:
        if silo_id in self._timers:
            self._timers[silo_id].cancel()
            del self._timers[silo_id]

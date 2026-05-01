"""Service registry with background health monitoring and automatic rebuild."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_HEALTH_CHECK_INTERVAL = 30  # seconds
_HEALTH_CHECK_TIMEOUT = 1.0  # seconds


class ServiceRegistry:
    """Holds backing-store singletons and monitors their health.

    On unhealthy detection the store is marked stale; the next request
    that calls ``get`` with ``rebuild=True`` (or calls ``rebuild_store``)
    will invoke the factory to get a fresh instance.
    """

    def __init__(self) -> None:
        self._stores: dict[str, Any] = {}
        self._healthy: dict[str, bool] = {}
        self._factories: dict[str, Callable[[], Coroutine[Any, Any, Any]]] = {}
        self._task: asyncio.Task[None] | None = None

    def register(
        self,
        name: str,
        instance: Any,
        factory: Callable[[], Coroutine[Any, Any, Any]] | None = None,
    ) -> None:
        """Register a store instance, optionally with a rebuild factory."""
        self._stores[name] = instance
        self._healthy[name] = True
        if factory is not None:
            self._factories[name] = factory

    def get(self, name: str) -> Any:
        return self._stores.get(name)

    def is_healthy(self, name: str) -> bool:
        return self._healthy.get(name, False)

    async def rebuild_store(self, name: str) -> bool:
        """Attempt to rebuild a store using its registered factory."""
        factory = self._factories.get(name)
        if factory is None:
            logger.error("service_registry_no_factory", store=name)
            return False
        try:
            instance = await factory()
            self._stores[name] = instance
            self._healthy[name] = True
            logger.info("service_registry_rebuilt", store=name)
            return True
        except Exception as e:
            logger.error("service_registry_rebuild_failed", store=name, error=str(e))
            return False

    async def _run_checks(self) -> None:
        for name, instance in list(self._stores.items()):
            check = getattr(instance, "health_check", None)
            if check is None:
                continue
            try:
                ok: bool = await asyncio.wait_for(check(), timeout=_HEALTH_CHECK_TIMEOUT)
            except TimeoutError:
                logger.warning("service_registry_health_timeout", store=name)
                ok = False
            except Exception as e:
                logger.warning("service_registry_health_error", store=name, error=str(e))
                ok = False

            was_healthy = self._healthy.get(name, True)
            self._healthy[name] = ok

            if not ok:
                logger.error("service_registry_unhealthy", store=name)
                if name in self._factories:
                    await self.rebuild_store(name)
            elif not was_healthy and ok:
                logger.info("service_registry_recovered", store=name)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
            await self._run_checks()

    def start(self) -> None:
        """Start the background health-check loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="service_registry_health")
            logger.info("service_registry_started", interval_s=_HEALTH_CHECK_INTERVAL)

    async def stop(self) -> None:
        """Cancel the background loop and wait for it to finish."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("service_registry_stopped")

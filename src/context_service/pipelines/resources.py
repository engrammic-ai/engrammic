"""Dagster resources for context-service.

Thin wrappers around store clients. Resources hold config only; asset bodies
call the existing async functions via asyncio.run() or await.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import dagster as dg
from pydantic import PrivateAttr

from context_service.config.settings import Settings, get_settings

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from qdrant_client import AsyncQdrantClient
    from redis.asyncio import Redis


class MemgraphResource(dg.ConfigurableResource):
    """Wraps context_service.stores.memgraph.create_memgraph_driver.

    Asset bodies call `await resource.driver()` inside an async context, or
    `asyncio.run(resource.driver())` from sync code.
    """

    uri: str
    user: str = ""
    password: str = ""

    _driver: AsyncDriver | None = PrivateAttr(default=None)

    async def driver(self) -> AsyncDriver:
        if self._driver is None:
            from context_service.stores.memgraph import create_memgraph_driver

            settings = get_settings()
            self._driver = await create_memgraph_driver(settings)
        return self._driver

    def teardown_after_execution(self, context: dg.InitResourceContext) -> None:
        if self._driver is not None:
            driver = self._driver
            self._driver = None
            try:
                asyncio.run(driver.close())
            except RuntimeError:
                pass


class RedisResource(dg.ConfigurableResource):
    """Wraps context_service.stores.redis.create_redis_pool."""

    url: str

    _client: Redis | None = PrivateAttr(default=None)

    async def client(self) -> Redis:
        if self._client is None:
            from context_service.stores.redis import create_redis_pool

            settings = get_settings()
            self._client = await create_redis_pool(settings)
        return self._client

    def teardown_after_execution(self, context: dg.InitResourceContext) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            try:
                asyncio.run(client.aclose())
            except RuntimeError:
                pass


class QdrantResource(dg.ConfigurableResource):
    """Holds Qdrant config. Asset bodies build AsyncQdrantClient on demand."""

    url: str
    api_key: str = ""

    _client: AsyncQdrantClient | None = PrivateAttr(default=None)

    def client(self) -> AsyncQdrantClient:
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(
                url=self.url,
                api_key=self.api_key if self.api_key else None,
            )
        return self._client

    def teardown_after_execution(self, context: dg.InitResourceContext) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            try:
                asyncio.run(client.close())
            except RuntimeError:
                pass


def build_default_resources() -> dict[str, dg.ConfigurableResource]:
    """Constructs the standard resource dict for Definitions(resources=...).

    All values sourced from context_service.config.settings.get_settings().
    """
    settings: Settings = get_settings()

    return {
        "memgraph": MemgraphResource(
            uri=settings.memgraph_uri,
            user=settings.memgraph_user,
            password=settings.memgraph_password,
        ),
        "redis": RedisResource(url=settings.redis_url),
        "qdrant": QdrantResource(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        ),
    }


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


__all__ = [
    "MemgraphResource",
    "QdrantResource",
    "RedisResource",
    "asyncio",
    "build_default_resources",
]

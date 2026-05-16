"""Dagster resources for context-service.

Thin wrappers around store clients. Resources hold config only; asset bodies
call the existing async functions via asyncio.run() or await.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import TYPE_CHECKING

import dagster as dg
from pydantic import PrivateAttr

from context_service.config.settings import Settings, get_settings

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from qdrant_client import AsyncQdrantClient
    from redis.asyncio import Redis

    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore
    from context_service.engine.qdrant_store import EngineQdrantStore
    from context_service.llm.base import LLMProvider


def _close_async(coro: object) -> None:
    # asyncio.run() raises RuntimeError if a loop is already running (Dagster runs
    # teardown from within its own event loop). Submit the close to a fresh thread
    # that gets its own loop; block until it completes so the resource is released.

    async def _safe_close() -> None:
        # Wrap the close in try/except to handle drivers that fail during
        # event loop teardown (e.g. neo4j raising "Event loop is closed").
        try:
            await coro  # type: ignore[misc]
        except RuntimeError as e:
            if "Event loop is closed" not in str(e):
                raise

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_safe_close())
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        f: concurrent.futures.Future[None] = pool.submit(lambda: asyncio.run(_safe_close()))
        f.result(timeout=30)


def _build_llm_provider(provider: str, model: str | None) -> LLMProvider:
    from context_service.llm import build_llm_provider

    return build_llm_provider(provider, model)


def _build_embedding_service() -> EmbeddingService:
    from context_service.embeddings import build_embedding_service

    return build_embedding_service()


class MemgraphResource(dg.ConfigurableResource):  # type: ignore[type-arg]
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
            from neo4j import AsyncGraphDatabase

            auth = (self.user, self.password) if self.user else None
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=auth,
                max_connection_pool_size=50,
                connection_acquisition_timeout=30.0,
            )
        return self._driver

    async def store(self) -> HyperGraphStore:
        """Return a HyperGraphStore wrapping the Memgraph driver.

        Centralises the concrete MemgraphStore construction so asset bodies
        depend only on the HyperGraphStore protocol (rule 8).
        """
        from context_service.engine.memgraph_store import MemgraphStore
        from context_service.stores import MemgraphClient

        driver = await self.driver()
        return MemgraphStore(MemgraphClient(driver))

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._driver is not None:
            driver = self._driver
            self._driver = None
            _close_async(driver.close())


class RedisResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Wraps context_service.stores.redis.create_redis_pool."""

    url: str

    _client: Redis | None = PrivateAttr(default=None)

    async def client(self) -> Redis:
        if self._client is None:
            from redis.asyncio import ConnectionPool
            from redis.asyncio import Redis as _Redis

            pool = ConnectionPool.from_url(
                self.url,
                max_connections=50,
                decode_responses=False,
            )
            self._client = _Redis(connection_pool=pool)
        return self._client

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            _close_async(client.aclose())


class QdrantResource(dg.ConfigurableResource):  # type: ignore[type-arg]
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

    def qdrant_store(self) -> EngineQdrantStore:
        """Return an EngineQdrantStore backed by the resource's Qdrant config.

        Asset bodies should call this rather than importing EngineQdrantStore
        directly, keeping concrete store construction out of pipeline assets.
        The caller is responsible for closing the underlying client when done.
        """
        from context_service.config.config_loader import load_config
        from context_service.engine.qdrant_store import EngineQdrantStore
        from context_service.stores.qdrant import QdrantClient as StoreQdrantClient

        dimensions = load_config("embeddings")["dimensions"]
        store_client = StoreQdrantClient(
            url=self.url,
            api_key=self.api_key if self.api_key else None,
            vector_size=dimensions,
        )
        return EngineQdrantStore(store_client)

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            _close_async(client.close())


class LLMResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Dispatches to an LLMProvider implementation based on `provider`.

    Supported values: "anthropic", "gemini", "openai", "vertex_gemini".
    Defaults to the value of settings.default_llm_model's provider family if
    not explicitly set; falls back to "gemini".
    """

    provider: str = "gemini"
    model: str = ""

    _llm: LLMProvider | None = PrivateAttr(default=None)

    def get_client(self) -> LLMProvider:
        if self._llm is None:
            self._llm = _build_llm_provider(self.provider, self.model or None)
        return self._llm

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._llm is not None:
            llm = self._llm
            self._llm = None
            _close_async(llm.close())


class EmbeddingResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Loads EmbeddingService from config/embeddings.yaml."""

    _service: EmbeddingService | None = PrivateAttr(default=None)

    def get_client(self) -> EmbeddingService:
        if self._service is None:
            self._service = _build_embedding_service()
        return self._service

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._service is not None:
            svc = self._service
            self._service = None
            _close_async(svc.close())


def build_default_resources() -> dict[str, dg.ConfigurableResource]:  # type: ignore[type-arg]
    """Constructs the standard resource dict for Definitions(resources=...).

    All values sourced from context_service.config.settings.get_settings().
    """
    settings: Settings = get_settings()

    memgraph_password = (
        settings.memgraph_password.get_secret_value() if settings.memgraph_password else ""
    )
    qdrant_api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else ""

    return {
        "memgraph": MemgraphResource(
            uri=settings.memgraph_uri,
            user=settings.memgraph_user,
            password=memgraph_password,
        ),
        "redis": RedisResource(url=settings.redis_url),
        "qdrant": QdrantResource(
            url=settings.qdrant_url,
            api_key=qdrant_api_key,
        ),
        "llm": LLMResource(
            provider=settings.models.get_model("default").provider,
            model=settings.models.get_model("default").model,
        ),
        "embedding": EmbeddingResource(),
    }


__all__ = [
    "EmbeddingResource",
    "LLMResource",
    "MemgraphResource",
    "QdrantResource",
    "RedisResource",
    "build_default_resources",
]

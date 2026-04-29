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
    from context_service.llm.base import LLMProvider


def _close_async(coro: object) -> None:
    # asyncio.run() raises RuntimeError if a loop is already running (Dagster runs
    # teardown from within its own event loop). Submit the close to a fresh thread
    # that gets its own loop; block until it completes so the resource is released.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)  # type: ignore[arg-type]
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        f: concurrent.futures.Future[None] = pool.submit(asyncio.run, coro)  # type: ignore[arg-type]
        f.result()


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


def _build_llm_provider(provider: str, model: str | None) -> LLMProvider:
    if provider == "anthropic":
        from context_service.llm.anthropic import AnthropicProvider

        return AnthropicProvider.from_settings(model)
    if provider == "openai":
        from context_service.llm.openai import OpenAIProvider

        return OpenAIProvider.from_settings(model)
    if provider == "vertex_gemini":
        from context_service.llm.vertex_gemini import VertexGeminiProvider

        return VertexGeminiProvider.from_settings(model)
    # default: gemini
    from context_service.llm.gemini import GeminiProvider

    settings = get_settings()
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=model or settings.default_llm_model,
    )


class EmbeddingResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Dispatches to an EmbeddingService implementation based on `provider`.

    Supported values: "jina", "vertex".
    """

    provider: str = "jina"

    _service: EmbeddingService | None = PrivateAttr(default=None)

    def get_client(self) -> EmbeddingService:
        if self._service is None:
            self._service = _build_embedding_service(self.provider)
        return self._service

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._service is not None:
            svc = self._service
            self._service = None
            _close_async(svc.close())


def _build_embedding_service(provider: str) -> EmbeddingService:
    settings = get_settings()
    if provider == "vertex":
        from context_service.embeddings.vertex import VertexAIEmbeddingService

        return VertexAIEmbeddingService(
            project=settings.vertex_project_id,
            region=settings.vertex_location,
        )
    from context_service.embeddings.jina import JinaEmbeddingService

    return JinaEmbeddingService(api_key=settings.jina_api_key)


def build_default_resources() -> dict[str, dg.ConfigurableResource]:  # type: ignore[type-arg]
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
        "llm": LLMResource(provider=_infer_llm_provider(settings.default_llm_model)),
        "embedding": EmbeddingResource(
            provider="jina" if settings.jina_api_key else "vertex"
        ),
    }


def _infer_llm_provider(default_model: str) -> str:
    """Map a model name to its provider key."""
    lower = default_model.lower()
    if lower.startswith("claude"):
        return "anthropic"
    if lower.startswith("gpt"):
        return "openai"
    if "vertex" in lower:
        return "vertex_gemini"
    return "gemini"


__all__ = [
    "EmbeddingResource",
    "LLMResource",
    "MemgraphResource",
    "QdrantResource",
    "RedisResource",
    "build_default_resources",
]

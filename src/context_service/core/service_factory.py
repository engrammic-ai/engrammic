"""Centralized service construction from settings.

Used by both the app lifespan and Dagster worker flows to construct services
from environment/settings without passing non-serializable objects across
process boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.config.logging import get_logger
from context_service.core.settings import get_settings

logger = get_logger(__name__)

if TYPE_CHECKING:
    from context_service.cache.embedding_cache import EmbeddingCache
    from context_service.core.settings import Settings
    from context_service.embeddings.jina import JinaEmbeddingService
    from context_service.embeddings.vertex import VertexAIEmbeddingService
    from context_service.llm.base import LLMProvider
    from context_service.stores.memgraph import MemgraphClient
    from context_service.stores.redis import RedisClient

    # TODO: import once ported
    # from context_service.compression.bear import BearCompressor
    # from context_service.extraction.service import ExtractionService
    # from context_service.clustering.service import ClusteringService
    # from context_service.services.context import ContextService
    # from context_service.services.retrieval_planner.controller import Controller
    # from context_service.services.retrieval_planner.planner import Planner
    # from context_service.ingest.pipeline import IngestDeps
    # from context_service.ingestion.service import BulkIngestionService


class ServiceFactory:
    """Construct services from settings.

    Most methods are async classmethods and pull settings via ``get_settings()``.
    An instance may also be constructed with an explicit settings object; this
    is primarily for convenience/smoke-testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else get_settings()

    @classmethod
    async def create_memgraph_client(cls) -> MemgraphClient:
        from context_service.stores.memgraph import MemgraphClient as MC
        from context_service.stores.memgraph import create_memgraph_driver

        settings = get_settings()
        driver = await create_memgraph_driver(settings)
        client = MC(driver)
        logger.info("ServiceFactory: Memgraph client created")
        return client

    @classmethod
    async def create_redis_client(cls) -> RedisClient:
        from context_service.stores.redis import RedisClient as RC
        from context_service.stores.redis import create_redis_pool

        settings = get_settings()
        pool = await create_redis_pool(settings)
        client = RC(pool)
        logger.info("ServiceFactory: Redis client created")
        return client

    @staticmethod
    def _create_llm_provider(settings: Settings) -> LLMProvider | None:
        """Create LLM provider from settings (returns None if not configured)."""
        provider_name = settings.llm_provider.lower()

        # VertexAI Gemini authenticates via service account, not API key.
        if provider_name == "vertex-gemini":
            from context_service.llm.vertex_gemini import VertexGeminiProvider

            if not settings.vertex_project:
                logger.warning("vertex-gemini provider selected but VERTEX_PROJECT is empty")
                return None
            return VertexGeminiProvider(
                project=settings.vertex_project,
                location=settings.vertex_location,
                model=settings.llm_model,
                credentials_path=settings.vertex_credentials_path,
            )

        if settings.llm_api_key is None:
            return None

        api_key = settings.llm_api_key.get_secret_value()

        if provider_name == "anthropic":
            from context_service.llm.anthropic import AnthropicProvider

            api_url = settings.llm_api_url or "https://api.anthropic.com/v1/messages"
            return AnthropicProvider(api_key=api_key, model=settings.llm_model, api_url=api_url)

        if provider_name == "gemini":
            from context_service.llm.gemini import GeminiProvider

            api_url = (
                settings.llm_api_url
                or "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            )
            return GeminiProvider(api_key=api_key, model=settings.llm_model, api_url=api_url)

        # Default to OpenAI-compatible
        from context_service.llm.openai import OpenAIProvider

        api_url = settings.llm_api_url or "https://api.openai.com/v1/chat/completions"
        return OpenAIProvider(api_key=api_key, model=settings.llm_model, api_url=api_url)

    @staticmethod
    def _build_llm_provider_from_uri(uri: str, settings: Settings) -> LLMProvider:
        """Dispatch a provider URI like 'vertex:gemini-2.5-flash' to an LLMProvider."""
        if uri.startswith("vertex:"):
            from context_service.llm.vertex_gemini import VertexGeminiProvider

            model = uri[len("vertex:"):]
            return VertexGeminiProvider(
                project=settings.vertex_project or "",
                location=settings.vertex_location,
                model=model,
                credentials_path=settings.vertex_credentials_path,
            )
        if uri.startswith("anthropic:"):
            from context_service.llm.anthropic import AnthropicProvider

            model = uri[len("anthropic:"):]
            api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
            return AnthropicProvider(api_key=api_key, model=model)
        if uri.startswith("gemini:"):
            from context_service.llm.gemini import GeminiProvider

            model = uri[len("gemini:"):]
            api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
            return GeminiProvider(api_key=api_key, model=model)
        # Default: openai-compatible
        from context_service.llm.openai import OpenAIProvider

        model = uri[len("openai:"):] if uri.startswith("openai:") else uri
        api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        return OpenAIProvider(api_key=api_key, model=model)

    @staticmethod
    def _create_embedding_service(
        settings: Settings,
        embedding_cache: EmbeddingCache | None = None,
    ) -> JinaEmbeddingService | VertexAIEmbeddingService | None:
        """Create embedding service from settings, or None."""
        if settings.embedding_provider == "vertex" and settings.vertex_project:
            from context_service.embeddings.vertex import VertexAIEmbeddingService

            return VertexAIEmbeddingService.from_settings(settings, embedding_cache)
        if settings.jina_api_key:
            from context_service.embeddings.jina import JinaEmbeddingService

            return JinaEmbeddingService.from_settings(settings, embedding_cache)
        return None

    # =========================================================================
    # TODO: Port the following methods once their modules are ported
    # =========================================================================

    # @classmethod
    # async def create_extraction_service(cls) -> ExtractionService | None:
    #     """TODO: Port after extraction module is ported."""
    #     raise NotImplementedError("extraction module not yet ported")

    # @classmethod
    # async def create_filter_orchestrator(cls, ...) -> FilterOrchestrator:
    #     """TODO: Port after extraction.filter module is ported."""
    #     raise NotImplementedError("extraction.filter module not yet ported")

    # @classmethod
    # async def create_clustering_service(cls) -> ClusteringService | None:
    #     """TODO: Port after clustering module is ported."""
    #     raise NotImplementedError("clustering module not yet ported")

    # @classmethod
    # async def create_custodian_clients(cls) -> tuple[MemgraphClient, RedisClient]:
    #     """Create (MemgraphClient, RedisClient) for custodian flows."""
    #     memgraph = await cls.create_memgraph_client()
    #     redis = await cls.create_redis_client()
    #     return memgraph, redis

    # @classmethod
    # async def create_planner(cls) -> Planner:
    #     """TODO: Port after retrieval_planner module is ported."""
    #     raise NotImplementedError("retrieval_planner module not yet ported")

    # @classmethod
    # def create_planner_controller(cls, settings: Settings, redis: RedisClient) -> Controller:
    #     """TODO: Port after retrieval_planner module is ported."""
    #     raise NotImplementedError("retrieval_planner module not yet ported")

    # @classmethod
    # async def create_ingest_deps(cls, ...) -> IngestDeps:
    #     """TODO: Port after ingest module is ported."""
    #     raise NotImplementedError("ingest module not yet ported")

    # @classmethod
    # def create_context_service(cls, ...) -> ContextService:
    #     """TODO: Port after services.context module is ported."""
    #     raise NotImplementedError("services.context module not yet ported")

    # @classmethod
    # def create_ingest_subscriber(cls, ...) -> object:
    #     """TODO: Port after services.ingest_subscriber module is ported."""
    #     raise NotImplementedError("services.ingest_subscriber module not yet ported")

    # @classmethod
    # async def create_ingestion_service(cls) -> BulkIngestionService:
    #     """TODO: Port after ingestion module is ported."""
    #     raise NotImplementedError("ingestion module not yet ported")

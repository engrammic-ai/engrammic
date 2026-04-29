"""Unit tests for pipelines/resources.py — no live services required."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from context_service.pipelines.resources import (
    EmbeddingResource,
    LLMResource,
    MemgraphResource,
    QdrantResource,
    RedisResource,
    _infer_llm_provider,
    build_default_resources,
)

# ---------------------------------------------------------------------------
# _infer_llm_provider
# ---------------------------------------------------------------------------


def test_infer_llm_provider_anthropic() -> None:
    assert _infer_llm_provider("claude-3-haiku") == "anthropic"


def test_infer_llm_provider_openai() -> None:
    assert _infer_llm_provider("gpt-4o-mini") == "openai"


def test_infer_llm_provider_vertex() -> None:
    assert _infer_llm_provider("vertex-gemini-pro") == "vertex_gemini"


def test_infer_llm_provider_gemini_default() -> None:
    assert _infer_llm_provider("gemini-2.0-flash") == "gemini"


# ---------------------------------------------------------------------------
# LLMResource
# ---------------------------------------------------------------------------


class _FakeLLM:
    async def complete(self, messages: Any, **kwargs: Any) -> tuple[str, Any]:
        return ("ok", None)

    async def extract_structured(self, messages: Any, schema: Any, **kwargs: Any) -> tuple[Any, Any]:
        return ({}, None)

    async def close(self) -> None:
        pass


def test_llm_resource_get_client_lazy() -> None:
    resource = LLMResource(provider="gemini", model="gemini-2.0-flash")
    assert resource._llm is None  # not created until get_client()

    with patch(
        "context_service.pipelines.resources._build_llm_provider",
        return_value=_FakeLLM(),
    ) as mock_build:
        client = resource.get_client()
        mock_build.assert_called_once_with("gemini", "gemini-2.0-flash")
        assert client is resource._llm


def test_llm_resource_get_client_cached() -> None:
    resource = LLMResource(provider="gemini", model="gemini-2.0-flash")
    fake = _FakeLLM()

    with patch(
        "context_service.pipelines.resources._build_llm_provider",
        return_value=fake,
    ) as mock_build:
        c1 = resource.get_client()
        c2 = resource.get_client()
        assert c1 is c2
        mock_build.assert_called_once()


def test_llm_resource_teardown_closes_client() -> None:
    resource = LLMResource(provider="gemini")
    fake = _FakeLLM()
    resource._llm = fake  # type: ignore[assignment]

    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_called_once()
        assert resource._llm is None


def test_llm_resource_teardown_noop_when_no_client() -> None:
    resource = LLMResource(provider="gemini")
    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_not_called()


# ---------------------------------------------------------------------------
# EmbeddingResource
# ---------------------------------------------------------------------------


class _FakeEmbeddingService:
    @property
    def dimensions(self) -> int:
        return 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions] * len(texts)

    async def embed_single(self, text: str) -> list[float]:
        return [0.0] * self.dimensions

    async def embed_query(self, query: str) -> list[float]:
        return [0.0] * self.dimensions

    async def close(self) -> None:
        pass


def test_embedding_resource_get_client_lazy() -> None:
    resource = EmbeddingResource(provider="jina")
    assert resource._service is None

    with patch(
        "context_service.pipelines.resources._build_embedding_service",
        return_value=_FakeEmbeddingService(),
    ) as mock_build:
        client = resource.get_client()
        mock_build.assert_called_once_with("jina")
        assert client is resource._service


def test_embedding_resource_get_client_cached() -> None:
    resource = EmbeddingResource(provider="jina")
    fake = _FakeEmbeddingService()

    with patch(
        "context_service.pipelines.resources._build_embedding_service",
        return_value=fake,
    ) as mock_build:
        c1 = resource.get_client()
        c2 = resource.get_client()
        assert c1 is c2
        mock_build.assert_called_once()


def test_embedding_resource_teardown_closes_service() -> None:
    resource = EmbeddingResource(provider="jina")
    resource._service = _FakeEmbeddingService()  # type: ignore[assignment]

    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_called_once()
        assert resource._service is None


def test_embedding_resource_teardown_noop_when_no_service() -> None:
    resource = EmbeddingResource(provider="jina")
    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_not_called()


# ---------------------------------------------------------------------------
# MemgraphResource teardown
# ---------------------------------------------------------------------------


def test_memgraph_resource_teardown_noop_when_no_driver() -> None:
    resource = MemgraphResource(uri="bolt://localhost:7687")
    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_not_called()


# ---------------------------------------------------------------------------
# RedisResource teardown
# ---------------------------------------------------------------------------


def test_redis_resource_teardown_noop_when_no_client() -> None:
    resource = RedisResource(url="redis://localhost:6379")
    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_not_called()


# ---------------------------------------------------------------------------
# QdrantResource teardown
# ---------------------------------------------------------------------------


def test_qdrant_resource_teardown_noop_when_no_client() -> None:
    resource = QdrantResource(url="http://localhost:6333")
    with patch("context_service.pipelines.resources._close_async") as mock_close:
        resource.teardown_after_execution(MagicMock())
        mock_close.assert_not_called()


# ---------------------------------------------------------------------------
# build_default_resources
# ---------------------------------------------------------------------------


def test_build_default_resources_keys() -> None:
    with patch("context_service.pipelines.resources.get_settings") as mock_settings:
        s = MagicMock()
        s.memgraph_uri = "bolt://localhost:7687"
        s.memgraph_user = ""
        s.memgraph_password = ""
        s.redis_url = "redis://localhost:6379"
        s.qdrant_url = "http://localhost:6333"
        s.qdrant_api_key = ""
        s.default_llm_model = "gemini-2.0-flash"
        s.jina_api_key = "test-key"
        mock_settings.return_value = s

        resources = build_default_resources()

    assert set(resources.keys()) == {"memgraph", "redis", "qdrant", "llm", "embedding"}
    assert isinstance(resources["llm"], LLMResource)
    assert isinstance(resources["embedding"], EmbeddingResource)
    assert resources["llm"].provider == "gemini"
    assert resources["embedding"].provider == "jina"


def test_build_default_resources_picks_vertex_embedding_when_no_jina() -> None:
    with patch("context_service.pipelines.resources.get_settings") as mock_settings:
        s = MagicMock()
        s.memgraph_uri = "bolt://localhost:7687"
        s.memgraph_user = ""
        s.memgraph_password = ""
        s.redis_url = "redis://localhost:6379"
        s.qdrant_url = "http://localhost:6333"
        s.qdrant_api_key = ""
        s.default_llm_model = "claude-3-haiku"
        s.jina_api_key = ""  # empty -> falls back to vertex
        mock_settings.return_value = s

        resources = build_default_resources()

    assert resources["llm"].provider == "anthropic"
    assert resources["embedding"].provider == "vertex"

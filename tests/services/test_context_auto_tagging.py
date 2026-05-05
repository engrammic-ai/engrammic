"""Tests for AutoTaggingService integration with ContextService.store()."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.auto_tagging import AutoTaggingService
from context_service.services.context import ContextService
from context_service.services.models import ScopeContext


def _make_scope() -> ScopeContext:
    return ScopeContext(org_id="test-org", silo_id=uuid.uuid4())


def _make_service(
    auto_tagging: AutoTaggingService | None = None,
    embedding_return: list[float] | None = None,
) -> tuple[ContextService, AsyncMock, AsyncMock]:
    memgraph = AsyncMock()
    memgraph.execute_write = AsyncMock(return_value=[])
    memgraph.execute_query = AsyncMock(return_value=[])

    qdrant = AsyncMock()
    qdrant.upsert = AsyncMock(return_value=None)

    embedding = AsyncMock()
    embedding.embed_single = AsyncMock(return_value=embedding_return or [0.1, 0.2, 0.3])

    svc = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        auto_tagging=auto_tagging,
    )
    return svc, memgraph, qdrant


class TestContextServiceAutoTagging:
    @pytest.mark.asyncio
    async def test_store_without_auto_tagging_does_not_set_auto_tags(self) -> None:
        svc, memgraph, _ = _make_service(auto_tagging=None)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            node = await svc.store(scope, "some content about databases", "Document")

        # No auto_tags in properties when service not configured
        assert "auto_tags" not in node.properties

        # Tag SET query should not have been called (only CREATE write)
        write_calls = [str(call) for call in memgraph.execute_write.call_args_list]
        assert not any("auto_tags" in c for c in write_calls)

    @pytest.mark.asyncio
    async def test_store_with_auto_tagging_sets_tags_on_node(self) -> None:
        auto_tagging = AsyncMock(spec=AutoTaggingService)
        auto_tagging.suggest_tags = AsyncMock(return_value=["database", "backend"])

        svc, memgraph, _ = _make_service(auto_tagging=auto_tagging)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            node = await svc.store(scope, "some content about databases", "Document")

        assert node.properties.get("auto_tags") == ["database", "backend"]
        assert "database" in node.properties.get("tags", [])
        assert "backend" in node.properties.get("tags", [])

        # Verify the Memgraph SET call was made with the right keys
        write_calls = memgraph.execute_write.call_args_list
        set_call = next(
            (c for c in write_calls if "auto_tags" in str(c)),
            None,
        )
        assert set_call is not None
        _, kwargs_or_args = set_call
        call_params: dict[str, Any] = (
            set_call.args[1] if set_call.args else set_call.kwargs.get("params", {})
        )
        assert call_params.get("auto_tags") == ["database", "backend"]

    @pytest.mark.asyncio
    async def test_store_merges_user_tags_with_auto_tags(self) -> None:
        auto_tagging = AsyncMock(spec=AutoTaggingService)
        auto_tagging.suggest_tags = AsyncMock(return_value=["database", "backend"])

        svc, memgraph, _ = _make_service(auto_tagging=auto_tagging)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            node = await svc.store(
                scope,
                "some content about databases",
                "Document",
                properties={"tags": ["user-tag"]},
            )

        tags = node.properties.get("tags", [])
        assert "user-tag" in tags
        assert "database" in tags
        assert "backend" in tags
        # user tags come first (order preserved)
        assert tags.index("user-tag") < tags.index("database")

    @pytest.mark.asyncio
    async def test_store_deduplicates_tags(self) -> None:
        auto_tagging = AsyncMock(spec=AutoTaggingService)
        # auto returns a tag already in user_tags
        auto_tagging.suggest_tags = AsyncMock(return_value=["shared", "new"])

        svc, memgraph, _ = _make_service(auto_tagging=auto_tagging)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            node = await svc.store(
                scope,
                "some content",
                "Document",
                properties={"tags": ["shared"]},
            )

        tags = node.properties.get("tags", [])
        assert tags.count("shared") == 1
        assert "new" in tags

    @pytest.mark.asyncio
    async def test_store_auto_tagging_failure_is_non_fatal(self) -> None:
        auto_tagging = AsyncMock(spec=AutoTaggingService)
        auto_tagging.suggest_tags = AsyncMock(side_effect=RuntimeError("embed service down"))

        svc, _, _ = _make_service(auto_tagging=auto_tagging)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            # Should not raise
            node = await svc.store(scope, "some content about databases", "Document")

        # No auto_tags set when suggest_tags raised
        assert "auto_tags" not in node.properties

    @pytest.mark.asyncio
    async def test_store_auto_tagging_empty_result_skips_db_write(self) -> None:
        auto_tagging = AsyncMock(spec=AutoTaggingService)
        auto_tagging.suggest_tags = AsyncMock(return_value=[])

        svc, memgraph, _ = _make_service(auto_tagging=auto_tagging)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            node = await svc.store(scope, "some content", "Document")

        # No extra SET when no tags returned
        write_calls = [str(call) for call in memgraph.execute_write.call_args_list]
        assert not any("auto_tags" in c for c in write_calls)
        assert "auto_tags" not in node.properties

    @pytest.mark.asyncio
    async def test_suggest_tags_called_with_correct_vector_and_silo(self) -> None:
        auto_tagging = AsyncMock(spec=AutoTaggingService)
        auto_tagging.suggest_tags = AsyncMock(return_value=["api"])

        vector = [0.5, 0.6, 0.7]
        svc, _, _ = _make_service(auto_tagging=auto_tagging, embedding_return=vector)
        scope = _make_scope()

        with patch("context_service.services.context.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                expansion_generation_enabled=False,
                heat_ranking_enabled=False,
                heat_weight=0.0,
                freshness_weight=0.0,
                freshness_sigma_days=30,
            )
            await svc.store(scope, "long enough content here", "Document")

        auto_tagging.suggest_tags.assert_awaited_once()
        call_kwargs = auto_tagging.suggest_tags.call_args
        assert call_kwargs.kwargs["content_vector"] == vector
        assert call_kwargs.kwargs["silo_id"] == str(scope.silo_id)

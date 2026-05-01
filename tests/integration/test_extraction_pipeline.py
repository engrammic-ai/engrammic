"""Integration tests for the extraction Dagster asset.

Requires a live Memgraph instance on localhost:7687. Skipped automatically
when the stack is not running (uses the docker_available marker from conftest).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import dagster as dg
import pytest

from context_service.config.settings import get_settings
from context_service.pipelines.assets.extraction import extraction as _extraction_asset
from context_service.pipelines.resources import LLMResource, MemgraphResource
from context_service.stores import MemgraphClient, create_memgraph_driver
from tests.integration.conftest import docker_available

_extraction_fn = _extraction_asset.op.compute_fn.decorated_fn


def _sync_run(coro: Any) -> Any:
    """Run a coroutine synchronously (for use in sync test functions)."""
    return asyncio.run(coro)


@docker_available
@pytest.mark.integration
class TestExtractionPipeline:
    """Seed documents, run extraction asset, verify claims land in Memgraph."""

    @pytest.fixture
    def unique_org_id(self) -> str:
        return f"test-org-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def unique_silo_id(self, unique_org_id: str) -> uuid.UUID:
        from context_service.services.models import derive_silo_id

        return derive_silo_id(unique_org_id)

    @pytest.fixture
    def seeded_docs(self, unique_silo_id: uuid.UUID) -> list[str]:
        """Insert two Document nodes and return their ids."""
        silo_id = str(unique_silo_id)
        doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        async def _seed() -> None:
            settings = get_settings()
            driver = await create_memgraph_driver(settings)
            client = MemgraphClient(driver)
            try:
                for doc_id in doc_ids:
                    await client.execute_write(
                        """
                        CREATE (d:Document {
                            id: $id,
                            silo_id: $silo_id,
                            content: $content,
                            committed: true
                        })
                        """,
                        {
                            "id": doc_id,
                            "silo_id": silo_id,
                            "content": f"Alice depends on Bob via document {doc_id}.",
                        },
                    )
            finally:
                await driver.close()

        _sync_run(_seed())
        return doc_ids

    @pytest.fixture
    def cleanup_silo(self, unique_silo_id: uuid.UUID) -> Any:
        """Cleanup test silo and nodes after test."""
        yield

        async def _cleanup() -> None:
            settings = get_settings()
            driver = await create_memgraph_driver(settings)
            client = MemgraphClient(driver)
            silo_id = str(unique_silo_id)
            try:
                await client.execute_write(
                    "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
                    {"silo_id": silo_id},
                )
                await client.execute_write(
                    "MATCH (s:Silo {id: $silo_id}) DELETE s",
                    {"silo_id": silo_id},
                )
            finally:
                await driver.close()

        _sync_run(_cleanup())

    @pytest.fixture
    def memgraph_resource_factory(self) -> Any:
        """Factory that creates fresh MemgraphResource per call (avoids event loop caching issues)."""
        settings = get_settings()

        def _factory() -> MemgraphResource:
            return MemgraphResource(
                uri=str(settings.memgraph_uri),
                user=settings.memgraph_user,
                password=settings.memgraph_password.get_secret_value() if settings.memgraph_password else "",
            )

        return _factory

    @pytest.fixture
    def mock_llm_resource(self) -> LLMResource:
        """LLMResource mock that returns a fixed extraction result."""
        llm_res = MagicMock(spec=LLMResource)
        mock_provider = AsyncMock()
        mock_provider.extract_structured = AsyncMock(
            return_value=(
                {
                    "entities": [
                        {"name": "Alice", "entity_type": "person", "description": ""},
                        {"name": "Bob", "entity_type": "person", "description": ""},
                    ],
                    "relationships": [
                        {
                            "source": "Alice",
                            "target": "Bob",
                            "relationship_type": "DEPENDS_ON",
                            "kind": "depends_on",
                            "confidence": 0.9,
                        }
                    ],
                },
                MagicMock(total_tokens=50),
            )
        )
        llm_res.get_client.return_value = mock_provider
        return llm_res

    def test_extraction_writes_claims_for_each_doc(
        self,
        unique_silo_id: uuid.UUID,
        seeded_docs: list[str],
        memgraph_resource_factory: Any,
        mock_llm_resource: LLMResource,
        cleanup_silo: None,
    ) -> None:
        """Each seeded Document should produce at least one :Claim node."""
        silo_id = str(unique_silo_id)

        ctx = MagicMock(spec=dg.AssetExecutionContext)
        ctx.partition_key = silo_id
        ctx.log = MagicMock()

        result = _extraction_fn(ctx, memgraph=memgraph_resource_factory(), llm=mock_llm_resource)

        assert isinstance(result, dg.Output)
        assert result.value["docs_processed"] == len(seeded_docs)
        assert result.value["claims_created"] > 0

        async def _verify() -> int:
            settings = get_settings()
            driver = await create_memgraph_driver(settings)
            client = MemgraphClient(driver)
            try:
                rows = await client.execute_query(
                    "MATCH (c:Claim {silo_id: $silo_id}) RETURN count(c) AS cnt",
                    {"silo_id": silo_id},
                )
                return int(rows[0]["cnt"]) if rows else 0
            finally:
                await driver.close()

        claim_count = _sync_run(_verify())
        assert claim_count > 0, "Expected :Claim nodes to be written to Memgraph"

    def test_extraction_attaches_claims_to_documents(
        self,
        unique_silo_id: uuid.UUID,
        seeded_docs: list[str],
        memgraph_resource_factory: Any,
        mock_llm_resource: LLMResource,
        cleanup_silo: None,
    ) -> None:
        """Extracted :Claim nodes must be attached via EXTRACTED_FROM to their source :Document."""
        silo_id = str(unique_silo_id)

        ctx = MagicMock(spec=dg.AssetExecutionContext)
        ctx.partition_key = silo_id
        ctx.log = MagicMock()

        _extraction_fn(ctx, memgraph=memgraph_resource_factory(), llm=mock_llm_resource)

        async def _verify() -> int:
            settings = get_settings()
            driver = await create_memgraph_driver(settings)
            client = MemgraphClient(driver)
            try:
                rows = await client.execute_query(
                    """
                    MATCH (c:Claim {silo_id: $silo_id})-[:EXTRACTED_FROM]->(d:Document {silo_id: $silo_id})
                    RETURN count(c) AS cnt
                    """,
                    {"silo_id": silo_id},
                )
                return int(rows[0]["cnt"]) if rows else 0
            finally:
                await driver.close()

        attached = _sync_run(_verify())
        assert attached > 0, "Expected EXTRACTED_FROM edges between :Claim and :Document"

    def test_extraction_idempotent_on_rerun(
        self,
        unique_silo_id: uuid.UUID,
        seeded_docs: list[str],
        memgraph_resource_factory: Any,
        mock_llm_resource: LLMResource,
        cleanup_silo: None,
    ) -> None:
        """Running the asset twice on the same silo must not double-write :Claim nodes."""
        silo_id = str(unique_silo_id)

        ctx = MagicMock(spec=dg.AssetExecutionContext)
        ctx.partition_key = silo_id
        ctx.log = MagicMock()

        _extraction_fn(ctx, memgraph=memgraph_resource_factory(), llm=mock_llm_resource)

        async def _count() -> int:
            settings = get_settings()
            driver = await create_memgraph_driver(settings)
            client = MemgraphClient(driver)
            try:
                rows = await client.execute_query(
                    "MATCH (c:Claim {silo_id: $silo_id}) RETURN count(c) AS cnt",
                    {"silo_id": silo_id},
                )
                return int(rows[0]["cnt"]) if rows else 0
            finally:
                await driver.close()

        count_first = _sync_run(_count())

        # Second run: no pending docs remain (all have EXTRACTED_FROM edges now).
        result2 = _extraction_fn(ctx, memgraph=memgraph_resource_factory(), llm=mock_llm_resource)
        assert result2.value["docs_processed"] == 0

        count_second = _sync_run(_count())
        assert count_second == count_first, "Second run must not create additional :Claim nodes"

"""Integration tests for the extraction Dagster asset.

Requires a live Memgraph instance on localhost:7687. Skipped automatically
when the stack is not running (uses the docker_available marker from conftest).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import dagster as dg
import pytest

# Call the underlying decorated function directly — @dg.asset returns an AssetsDefinition,
# not a plain callable, so tests must reach through to the wrapped function.
from context_service.pipelines.assets.extraction import extraction as _extraction_asset
from tests.integration.conftest import docker_available

_extraction_fn = _extraction_asset.op.compute_fn.decorated_fn


@docker_available
@pytest.mark.integration
class TestExtractionPipeline:
    """Seed documents, run extraction asset, verify claims land in Memgraph."""

    @pytest.fixture
    async def seeded_docs(
        self,
        memgraph_client: Any,
        unique_silo_id: uuid.UUID,
    ) -> list[str]:
        """Insert two Document nodes and return their ids."""
        silo_id = str(unique_silo_id)
        doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        for doc_id in doc_ids:
            await memgraph_client.execute_write(
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
        return doc_ids

    @pytest.fixture
    def mock_llm_resource(self) -> MagicMock:
        """LLMResource mock that returns a fixed extraction result."""
        llm_res = MagicMock()
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

    @pytest.mark.asyncio
    async def test_extraction_writes_claims_for_each_doc(
        self,
        memgraph_client: Any,
        memgraph_driver: Any,
        unique_silo_id: uuid.UUID,
        seeded_docs: list[str],
        mock_llm_resource: MagicMock,
        cleanup_silo: None,
    ) -> None:
        """Each seeded Document should produce at least one :Claim node."""
        silo_id = str(unique_silo_id)

        memgraph_res = MagicMock()

        async def _driver() -> Any:
            return memgraph_driver

        memgraph_res.driver = _driver

        ctx = MagicMock(spec=dg.AssetExecutionContext)
        ctx.partition_key = silo_id
        ctx.log = MagicMock()

        result = _extraction_fn(ctx, memgraph=memgraph_res, llm=mock_llm_resource)

        assert isinstance(result, dg.Output)
        assert result.value["docs_processed"] == len(seeded_docs)
        assert result.value["claims_created"] > 0

        rows = await memgraph_client.execute_query(
            "MATCH (c:Claim {silo_id: $silo_id}) RETURN count(c) AS cnt",
            {"silo_id": silo_id},
        )
        claim_count = int(rows[0]["cnt"]) if rows else 0
        assert claim_count > 0, "Expected :Claim nodes to be written to Memgraph"

    @pytest.mark.asyncio
    async def test_extraction_attaches_claims_to_documents(
        self,
        memgraph_client: Any,
        memgraph_driver: Any,
        unique_silo_id: uuid.UUID,
        seeded_docs: list[str],
        mock_llm_resource: MagicMock,
        cleanup_silo: None,
    ) -> None:
        """Extracted :Claim nodes must be attached via EXTRACTED_FROM to their source :Document."""
        silo_id = str(unique_silo_id)

        memgraph_res = MagicMock()

        async def _driver() -> Any:
            return memgraph_driver

        memgraph_res.driver = _driver

        ctx = MagicMock(spec=dg.AssetExecutionContext)
        ctx.partition_key = silo_id
        ctx.log = MagicMock()

        _extraction_fn(ctx, memgraph=memgraph_res, llm=mock_llm_resource)

        rows = await memgraph_client.execute_query(
            """
            MATCH (c:Claim {silo_id: $silo_id})-[:EXTRACTED_FROM]->(d:Document {silo_id: $silo_id})
            RETURN count(c) AS cnt
            """,
            {"silo_id": silo_id},
        )
        attached = int(rows[0]["cnt"]) if rows else 0
        assert attached > 0, "Expected EXTRACTED_FROM edges between :Claim and :Document"

    @pytest.mark.asyncio
    async def test_extraction_idempotent_on_rerun(
        self,
        memgraph_client: Any,
        memgraph_driver: Any,
        unique_silo_id: uuid.UUID,
        seeded_docs: list[str],
        mock_llm_resource: MagicMock,
        cleanup_silo: None,
    ) -> None:
        """Running the asset twice on the same silo must not double-write :Claim nodes."""
        silo_id = str(unique_silo_id)

        memgraph_res = MagicMock()

        async def _driver() -> Any:
            return memgraph_driver

        memgraph_res.driver = _driver

        ctx = MagicMock(spec=dg.AssetExecutionContext)
        ctx.partition_key = silo_id
        ctx.log = MagicMock()

        _extraction_fn(ctx, memgraph=memgraph_res, llm=mock_llm_resource)

        rows_after_first = await memgraph_client.execute_query(
            "MATCH (c:Claim {silo_id: $silo_id}) RETURN count(c) AS cnt",
            {"silo_id": silo_id},
        )
        count_first = int(rows_after_first[0]["cnt"]) if rows_after_first else 0

        # Second run: no pending docs remain (all have EXTRACTED_FROM edges now).
        result2 = _extraction_fn(ctx, memgraph=memgraph_res, llm=mock_llm_resource)
        assert result2.value["docs_processed"] == 0

        rows_after_second = await memgraph_client.execute_query(
            "MATCH (c:Claim {silo_id: $silo_id}) RETURN count(c) AS cnt",
            {"silo_id": silo_id},
        )
        count_second = int(rows_after_second[0]["cnt"]) if rows_after_second else 0
        assert count_second == count_first, "Second run must not create additional :Claim nodes"

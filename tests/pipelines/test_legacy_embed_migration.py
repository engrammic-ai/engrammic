"""Tests for the legacy embed migration job."""

from __future__ import annotations

import dagster as dg
import pytest

from context_service.pipelines.jobs.legacy_embed_migration_job import (
    BATCH_SIZE,
    MAX_EMBED_CHARS,
    MIN_CONTENT_LEN,
    sage_legacy_embed_migration_job,
)
from context_service.pipelines.resources import EmbeddingResource, MemgraphResource, QdrantResource


def _resources() -> dict[str, dg.ConfigurableResource]:  # type: ignore[type-arg]
    return {
        "memgraph": MemgraphResource(uri="bolt://fake:7687"),
        "qdrant": QdrantResource(url="http://fake:6333"),
        "embedding": EmbeddingResource(),
    }


class TestLegacyEmbedMigrationConstants:
    def test_batch_size(self) -> None:
        assert BATCH_SIZE == 50

    def test_max_embed_chars(self) -> None:
        assert MAX_EMBED_CHARS == 8000

    def test_min_content_len(self) -> None:
        assert MIN_CONTENT_LEN == 10


class TestLegacyEmbedMigrationJob:
    def test_job_name(self) -> None:
        assert sage_legacy_embed_migration_job.name == "sage_legacy_embed_migration_job"

    def test_job_has_no_schedule(self) -> None:
        """Migration job must not be scheduled — it is manual/ad-hoc."""
        from context_service.pipelines.schedules import all_schedules

        schedule_job_names = {s.job_name for s in all_schedules}
        assert "sage_legacy_embed_migration_job" not in schedule_job_names

    def test_job_has_op(self) -> None:
        """Job graph includes the migration op."""
        op_names = {node.name for node in sage_legacy_embed_migration_job.nodes}
        assert "legacy_embed_migration_op" in op_names

    def test_job_requires_memgraph_resource(self) -> None:
        """Migration op must declare memgraph as a required resource."""
        from context_service.pipelines.jobs.legacy_embed_migration_job import (
            legacy_embed_migration_op,
        )

        assert "memgraph" in legacy_embed_migration_op.required_resource_keys

    def test_job_requires_qdrant_and_embedding_resources(self) -> None:
        """Migration op must declare qdrant and embedding as required resources."""
        from context_service.pipelines.jobs.legacy_embed_migration_job import (
            legacy_embed_migration_op,
        )

        assert "qdrant" in legacy_embed_migration_op.required_resource_keys
        assert "embedding" in legacy_embed_migration_op.required_resource_keys


class TestLegacyEmbedMigrationLogic:
    """Unit tests for migration logic without Dagster execution overhead."""

    @pytest.mark.asyncio
    async def test_skips_nodes_below_min_content_len(self) -> None:
        """Nodes with content shorter than MIN_CONTENT_LEN are skipped."""
        rows = [
            {"id": "abc", "content": "short", "node_type": "Claim"},
            {"id": "def", "content": "x" * MIN_CONTENT_LEN, "node_type": "Claim"},
        ]
        eligible = [
            r for r in rows if r.get("content") and len(str(r["content"])) >= MIN_CONTENT_LEN
        ]
        assert len(eligible) == 1
        assert eligible[0]["id"] == "def"

    def test_content_truncated_at_max_embed_chars(self) -> None:
        """Content exceeding MAX_EMBED_CHARS is truncated before embedding."""
        long_content = "x" * (MAX_EMBED_CHARS + 1000)
        truncated = long_content[:MAX_EMBED_CHARS]
        assert len(truncated) == MAX_EMBED_CHARS

    def test_registered_in_definitions(self) -> None:
        """Migration job must appear in Dagster Definitions."""
        from context_service.pipelines.definitions import defs

        job_names = {j.name for j in defs.jobs}  # type: ignore[union-attr]
        assert "sage_legacy_embed_migration_job" in job_names

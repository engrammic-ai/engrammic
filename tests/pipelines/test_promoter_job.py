"""Tests for the sage_promoter_job skeleton (SAGE Phase B)."""

from __future__ import annotations

from context_service.pipelines.jobs.promoter_job import (
    promoter_op,
    sage_promoter_job,
    sage_promoter_schedule,
)


class TestPromoterJob:
    def test_job_name(self) -> None:
        assert sage_promoter_job.name == "sage_promoter_job"

    def test_job_has_op(self) -> None:
        op_names = {node.name for node in sage_promoter_job.nodes}
        assert "promoter_op" in op_names

    def test_op_requires_memgraph_resource(self) -> None:
        assert "memgraph" in promoter_op.required_resource_keys

    def test_registered_in_definitions(self) -> None:
        from context_service.pipelines.definitions import defs

        job_names = {j.name for j in defs.jobs}  # type: ignore[union-attr]
        assert "sage_promoter_job" in job_names


class TestPromoterSchedule:
    def test_schedule_cron(self) -> None:
        assert sage_promoter_schedule.cron_schedule == "*/5 * * * *"

    def test_schedule_targets_promoter_job(self) -> None:
        assert sage_promoter_schedule.job_name == "sage_promoter_job"

    def test_schedule_registered_in_definitions(self) -> None:
        from context_service.pipelines.definitions import defs

        schedule_names = {s.name for s in defs.schedules}  # type: ignore[union-attr]
        assert "sage_promoter_job_schedule" in schedule_names

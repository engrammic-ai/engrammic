"""Tests for the sage_synthesizer_job skeleton (SAGE Phase C)."""

from __future__ import annotations

from context_service.pipelines.jobs.synthesizer_job import (
    sage_synthesizer_job,
    sage_synthesizer_schedule,
    synthesizer_op,
)


class TestSynthesizerJob:
    def test_job_name(self) -> None:
        assert sage_synthesizer_job.name == "sage_synthesizer_job"

    def test_job_has_op(self) -> None:
        op_names = {node.name for node in sage_synthesizer_job.nodes}
        assert "synthesizer_op" in op_names

    def test_op_requires_memgraph_resource(self) -> None:
        assert "memgraph" in synthesizer_op.required_resource_keys

    def test_op_requires_llm_resource(self) -> None:
        assert "llm" in synthesizer_op.required_resource_keys

    def test_registered_in_definitions(self) -> None:
        from context_service.pipelines.definitions import defs

        job_names = {j.name for j in defs.jobs}  # type: ignore[union-attr]
        assert "sage_synthesizer_job" in job_names


class TestSynthesizerSchedule:
    def test_schedule_cron(self) -> None:
        assert sage_synthesizer_schedule.cron_schedule == "*/15 * * * *"

    def test_schedule_targets_synthesizer_job(self) -> None:
        assert sage_synthesizer_schedule.job_name == "sage_synthesizer_job"

    def test_schedule_registered_in_definitions(self) -> None:
        from context_service.pipelines.definitions import defs

        schedule_names = {s.name for s in defs.schedules}  # type: ignore[union-attr]
        assert "sage_synthesizer_job_schedule" in schedule_names

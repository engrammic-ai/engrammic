"""Tests for the sage_decayer_job (SAGE Phase D)."""

from __future__ import annotations

import pytest

from context_service.pipelines.jobs.decayer_job import (
    _DEFAULT_DECAY_RATE,
    decay_confidence,
    decayer_op,
    sage_decayer_job,
    sage_decayer_schedule,
)


class TestDecayerJob:
    def test_job_name(self) -> None:
        assert sage_decayer_job.name == "sage_decayer_job"

    def test_job_has_op(self) -> None:
        op_names = {node.name for node in sage_decayer_job.nodes}
        assert "decayer_op" in op_names

    def test_op_requires_memgraph_resource(self) -> None:
        assert "memgraph" in decayer_op.required_resource_keys

    def test_registered_in_definitions(self) -> None:
        from context_service.pipelines.definitions import defs

        job_names = {j.name for j in defs.jobs}  # type: ignore[union-attr]
        assert "sage_decayer_job" in job_names


class TestDecayerSchedule:
    def test_schedule_cron(self) -> None:
        assert sage_decayer_schedule.cron_schedule == "0 * * * *"

    def test_schedule_targets_decayer_job(self) -> None:
        assert sage_decayer_schedule.job_name == "sage_decayer_job"

    def test_schedule_registered_in_definitions(self) -> None:
        from context_service.pipelines.definitions import defs

        schedule_names = {s.name for s in defs.schedules}  # type: ignore[union-attr]
        assert "sage_decayer_job_schedule" in schedule_names


class TestDecayFormula:
    def test_zero_hours_no_decay(self) -> None:
        result = decay_confidence(1.0, _DEFAULT_DECAY_RATE, 0.0)
        assert result == pytest.approx(1.0)

    def test_one_hour_decay(self) -> None:
        result = decay_confidence(1.0, _DEFAULT_DECAY_RATE, 1.0)
        assert result == pytest.approx(_DEFAULT_DECAY_RATE)

    def test_decay_reduces_confidence(self) -> None:
        result = decay_confidence(0.8, _DEFAULT_DECAY_RATE, 10.0)
        assert result < 0.8

    def test_custom_decay_rate(self) -> None:
        result = decay_confidence(1.0, 0.5, 2.0)
        assert result == pytest.approx(0.25)

    def test_decay_never_negative(self) -> None:
        result = decay_confidence(0.01, 0.5, 1000.0)
        assert result >= 0.0

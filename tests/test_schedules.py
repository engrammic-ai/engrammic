"""Tests: ScheduleDefinitions are wired into Definitions with expected cron and targets."""

import dagster as dg
import pytest

from context_service.pipelines.schedules import (
    all_schedules,
    sage_groundskeeper_schedule,
    sage_validator_schedule,
)


@pytest.fixture()
def defs() -> dg.Definitions:
    from context_service.pipelines.definitions import defs as _defs

    return _defs


def test_sage_groundskeeper_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("sage_groundskeeper_schedule")
    assert sched is not None


def test_sage_validator_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("sage_validator_schedule")
    assert sched is not None


def test_sage_groundskeeper_schedule_cron() -> None:
    assert sage_groundskeeper_schedule.cron_schedule == "*/15 * * * *"


def test_sage_validator_schedule_cron() -> None:
    assert sage_validator_schedule.cron_schedule == "*/5 * * * *"


def test_all_schedules_count() -> None:
    assert len(all_schedules) == 11


def test_schedule_names_in_all_schedules() -> None:
    names = {s.name for s in all_schedules}
    assert "sage_groundskeeper_schedule" in names
    assert "sage_validator_schedule" in names
    assert "auto_tagging_schedule" in names
    assert "daily_maintenance_schedule" in names
    assert "telemetry_gauges_schedule" in names
    assert "telemetry_prune_schedule" in names

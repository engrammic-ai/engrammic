"""Tests: ScheduleDefinitions are wired into Definitions with expected cron and targets."""

import dagster as dg
import pytest

from context_service.pipelines.schedules import (
    all_schedules,
    clustering_schedule,
    custodian_visit_schedule,
    fact_promotion_schedule,
)


@pytest.fixture()
def defs() -> dg.Definitions:
    from context_service.pipelines.definitions import defs as _defs

    return _defs


def test_clustering_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("clustering_schedule")
    assert sched is not None


def test_fact_promotion_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("fact_promotion_schedule")
    assert sched is not None


def test_clustering_schedule_cron() -> None:
    assert clustering_schedule.cron_schedule == "0 4 * * *"


def test_fact_promotion_schedule_cron() -> None:
    assert fact_promotion_schedule.cron_schedule == "0 * * * *"


def test_custodian_visit_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("custodian_visit_schedule")
    assert sched is not None


def test_custodian_visit_schedule_cron() -> None:
    assert custodian_visit_schedule.cron_schedule == "*/15 * * * *"


def test_all_schedules_count() -> None:
    assert len(all_schedules) == 10


def test_schedule_names_in_all_schedules() -> None:
    names = {s.name for s in all_schedules}
    assert "clustering_schedule" in names
    assert "fact_promotion_schedule" in names
    assert "custodian_visit_schedule" in names
    assert "heat_schedule" in names
    assert "auto_tagging_schedule" in names
    assert "tag_maintenance_schedule" in names

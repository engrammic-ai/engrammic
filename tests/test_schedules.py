"""Tests: ScheduleDefinitions are wired into Definitions with expected cron and targets."""

import dagster as dg
import pytest

from context_service.pipelines.schedules import (
    all_schedules,
    clustering_pipeline_schedule,
    custodian_pipeline_schedule,
    heat_pipeline_schedule,
    knowledge_pipeline_schedule,
)


@pytest.fixture()
def defs() -> dg.Definitions:
    from context_service.pipelines.definitions import defs as _defs

    return _defs


def test_custodian_pipeline_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("custodian_pipeline_schedule")
    assert sched is not None


def test_knowledge_pipeline_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("knowledge_pipeline_schedule")
    assert sched is not None


def test_clustering_pipeline_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("clustering_pipeline_schedule")
    assert sched is not None


def test_heat_pipeline_schedule_registered(defs: dg.Definitions) -> None:
    sched = defs.get_schedule_def("heat_pipeline_schedule")
    assert sched is not None


def test_custodian_pipeline_schedule_cron() -> None:
    assert custodian_pipeline_schedule.cron_schedule == "*/15 * * * *"


def test_knowledge_pipeline_schedule_cron() -> None:
    assert knowledge_pipeline_schedule.cron_schedule == "0 * * * *"


def test_clustering_pipeline_schedule_cron() -> None:
    assert clustering_pipeline_schedule.cron_schedule == "0 4 * * *"


def test_heat_pipeline_schedule_cron() -> None:
    assert heat_pipeline_schedule.cron_schedule == "0 2 * * *"


def test_all_schedules_count() -> None:
    assert len(all_schedules) == 11


def test_schedule_names_in_all_schedules() -> None:
    names = {s.name for s in all_schedules}
    assert "custodian_pipeline_schedule" in names
    assert "knowledge_pipeline_schedule" in names
    assert "clustering_pipeline_schedule" in names
    assert "heat_pipeline_schedule" in names
    assert "auto_tagging_schedule" in names
    assert "tag_maintenance_schedule" in names

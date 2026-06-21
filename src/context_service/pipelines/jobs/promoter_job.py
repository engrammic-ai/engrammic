"""Dagster job for promoting eligible Claims to Facts (SAGE Phase B).

Promotion logic is implemented in Task 2. This skeleton wires up the job
and its 5-minute schedule so it can be registered and tested independently.
"""

from __future__ import annotations

import dagster as dg
from dagster import ScheduleDefinition


@dg.op
def promoter_op(context) -> dict[str, int]:
    """Promote eligible claims to facts."""
    # TODO: Implementation in Task 2
    context.log.info("promoter_op: no-op skeleton")
    return {"promoted": 0, "skipped": 0}


@dg.job(
    name="sage_promoter_job",
    description="SAGE Phase B: promote eligible Claims to Facts every 5 minutes.",
)
def sage_promoter_job() -> None:
    """Claim-to-fact promotion job."""
    promoter_op()


sage_promoter_schedule = ScheduleDefinition(
    job=sage_promoter_job,
    cron_schedule="*/5 * * * *",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

"""Dagster asset sensors: causal_transitivity_sensor and chain_stitch_sensor.

causal_transitivity_sensor watches claim_to_fact_promotion materializations and
triggers the causal_transitivity asset for the same silo partition.

chain_stitch_sensor watches custodian_finalize materializations and triggers the
chain_stitch asset for the same silo partition.
"""

from __future__ import annotations

import dagster as dg
from dagster import SensorEvaluationContext


@dg.asset_sensor(
    asset_key=dg.AssetKey("claim_to_fact_promotion"),
    name="causal_transitivity_sensor",
    minimum_interval_seconds=60,
    description=(
        "Triggers causal_transitivity for the same silo partition whenever "
        "claim_to_fact_promotion materializes."
    ),
)
def causal_transitivity_sensor(
    context: SensorEvaluationContext,
    asset_event: dg.EventLogEntry,
) -> dg.RunRequest | None:
    """Yield a RunRequest for causal_transitivity on each claim_to_fact_promotion materialization."""
    partition_key = asset_event.dagster_event.partition if asset_event.dagster_event else None
    if not partition_key:
        context.log.warning(
            "causal_transitivity_sensor: no partition key on materialization event, skipping"
        )
        return None

    context.log.info(
        f"causal_transitivity_sensor: triggering causal_transitivity for partition={partition_key}"
    )
    return dg.RunRequest(
        run_key=f"causal_transitivity:{partition_key}:{asset_event.run_id}",
        partition_key=partition_key,
        asset_selection=[dg.AssetKey("causal_transitivity")],
        tags={"dagster/concurrency_key": partition_key},
    )


@dg.asset_sensor(
    asset_key=dg.AssetKey("custodian_finalize"),
    name="chain_stitch_sensor",
    minimum_interval_seconds=60,
    description=(
        "Triggers chain_stitch for the same silo partition whenever "
        "custodian_finalize materializes."
    ),
)
def chain_stitch_sensor(
    context: SensorEvaluationContext,
    asset_event: dg.EventLogEntry,
) -> dg.RunRequest | None:
    """Yield a RunRequest for chain_stitch on each custodian_finalize materialization."""
    partition_key = asset_event.dagster_event.partition if asset_event.dagster_event else None
    if not partition_key:
        context.log.warning(
            "chain_stitch_sensor: no partition key on materialization event, skipping"
        )
        return None

    context.log.info(f"chain_stitch_sensor: triggering chain_stitch for partition={partition_key}")
    return dg.RunRequest(
        run_key=f"chain_stitch:{partition_key}:{asset_event.run_id}",
        partition_key=partition_key,
        asset_selection=[dg.AssetKey("chain_stitch")],
        tags={"dagster/concurrency_key": partition_key},
    )

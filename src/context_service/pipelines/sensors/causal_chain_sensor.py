"""Dagster asset sensors: causal_transitivity_sensor and chain_stitch_sensor.

causal_transitivity_sensor watches claim_to_fact_promotion materializations and
triggers the causal_transitivity asset for the same silo partition.

chain_stitch_sensor watches custodian_finalize materializations and triggers the
chain_stitch asset for the same silo partition.
"""

from __future__ import annotations

import dagster as dg


@dg.sensor(
    name="causal_transitivity_sensor",
    asset_selection=dg.AssetSelection.assets("causal_transitivity"),
    minimum_interval_seconds=60,
    description=(
        "Triggers causal_transitivity for the same silo partition whenever "
        "claim_to_fact_promotion materializes."
    ),
)
def causal_transitivity_sensor(context) -> dg.SensorResult:
    """Yield RunRequests for causal_transitivity on new claim_to_fact_promotion materializations."""
    from dagster import AssetKey, DagsterEventType

    asset_key = AssetKey("claim_to_fact_promotion")
    cursor = context.cursor or "0"
    events = context.instance.get_event_records(
        dg.EventRecordsFilter(
            event_type=DagsterEventType.ASSET_MATERIALIZATION,
            asset_key=asset_key,
            after_cursor=int(cursor) if cursor.isdigit() else 0,
        ),
        limit=100,
    )

    run_requests: list[dg.RunRequest] = []
    max_cursor = cursor

    for event in events:
        partition_key = event.partition_key
        if not partition_key:
            continue

        run_requests.append(
            dg.RunRequest(
                run_key=f"causal_transitivity:{partition_key}:{event.storage_id}",
                partition_key=partition_key,
                tags={"dagster/concurrency_key": partition_key},
            )
        )
        max_cursor = str(max(int(max_cursor) if max_cursor.isdigit() else 0, event.storage_id))

    return dg.SensorResult(run_requests=run_requests, cursor=max_cursor)


@dg.sensor(
    name="chain_stitch_sensor",
    asset_selection=dg.AssetSelection.assets("chain_stitch"),
    minimum_interval_seconds=60,
    description=(
        "Triggers chain_stitch for the same silo partition whenever "
        "custodian_finalize materializes."
    ),
)
def chain_stitch_sensor(context) -> dg.SensorResult:
    """Yield RunRequests for chain_stitch on new custodian_finalize materializations."""
    from dagster import AssetKey, DagsterEventType

    asset_key = AssetKey("custodian_finalize")
    cursor = context.cursor or "0"
    events = context.instance.get_event_records(
        dg.EventRecordsFilter(
            event_type=DagsterEventType.ASSET_MATERIALIZATION,
            asset_key=asset_key,
            after_cursor=int(cursor) if cursor.isdigit() else 0,
        ),
        limit=100,
    )

    run_requests: list[dg.RunRequest] = []
    max_cursor = cursor

    for event in events:
        partition_key = event.partition_key
        if not partition_key:
            continue

        run_requests.append(
            dg.RunRequest(
                run_key=f"chain_stitch:{partition_key}:{event.storage_id}",
                partition_key=partition_key,
                tags={"dagster/concurrency_key": partition_key},
            )
        )
        max_cursor = str(max(int(max_cursor) if max_cursor.isdigit() else 0, event.storage_id))

    return dg.SensorResult(run_requests=run_requests, cursor=max_cursor)

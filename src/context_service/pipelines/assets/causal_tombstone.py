"""Dagster asset: causal_tombstone — bulk tombstone inferred CAUSES edges per silo.

Accepts filter criteria and delegates transitive invalidation to
engine/tombstone.py.  The asset can be triggered manually via the Dagster UI
(run config) or from the admin API endpoint POST /admin/tombstone.
"""

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.resources import MemgraphResource


def _run_async_dict(coro: Any) -> dict[str, int]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result: dict[str, int] = asyncio.run(coro)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(asyncio.run, coro).result(timeout=300)
        return result


@dg.asset(
    name="causal_tombstone",
    description=(
        "Tombstone inferred CAUSES edges matching filter criteria for a silo. "
        "Also cascades to edges derived from the tombstoned ones via transitive invalidation."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "causal_tombstone"},
    config_schema={
        "silo_id": dg.Field(str, description="Silo to tombstone edges within (required)."),
        "edge_type": dg.Field(
            str,
            is_required=False,
            default_value="",
            description="Filter by edge type (CAUSES, CORROBORATES, PREVENTS). Empty = all.",
        ),
        "confidence_below": dg.Field(
            float,
            is_required=False,
            default_value=-1.0,
            description="Tombstone edges with confidence below this threshold. -1 = no filter.",
        ),
        "created_before": dg.Field(
            str,
            is_required=False,
            default_value="",
            description="ISO-8601 datetime. Tombstone edges created before this timestamp.",
        ),
        "edge_ids": dg.Field(
            dg.Array(str),
            is_required=False,
            default_value=[],
            description="Explicit list of edge IDs to tombstone. Overrides filter criteria.",
        ),
        "max_invalidation_depth": dg.Field(
            int,
            is_required=False,
            default_value=3,
            description="Max cascade hops for derived-edge invalidation.",
        ),
    },
)
def causal_tombstone(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Tombstone matching CAUSES edges and cascade to derived inferences."""
    from context_service.engine.tombstone import run_tombstone

    cfg = context.op_config
    silo_id: str = cfg["silo_id"]
    edge_type: str = cfg.get("edge_type", "")
    confidence_below: float = cfg.get("confidence_below", -1.0)
    created_before_str: str = cfg.get("created_before", "")
    explicit_ids: list[str] = list(cfg.get("edge_ids", []))
    max_depth: int = cfg.get("max_invalidation_depth", 3)

    parsed_confidence = confidence_below if confidence_below >= 0.0 else None
    parsed_edge_type = edge_type if edge_type else None
    parsed_created_before: datetime | None = None
    if created_before_str:
        parsed_created_before = datetime.fromisoformat(created_before_str)
        if parsed_created_before.tzinfo is None:
            parsed_created_before = parsed_created_before.replace(tzinfo=UTC)

    t0 = time.monotonic()

    async def _run() -> dict[str, int]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        return await run_tombstone(
            client,
            silo_id,
            edge_ids=explicit_ids if explicit_ids else None,
            edge_type=parsed_edge_type,
            confidence_below=parsed_confidence,
            created_before=parsed_created_before,
            max_invalidation_depth=max_depth,
        )

    counts = _run_async_dict(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} "
        f"direct_tombstoned={counts['direct']} "
        f"derived_tombstoned={counts['derived']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "direct_tombstoned": counts["direct"],
            "derived_tombstoned": counts["derived"],
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "direct_tombstoned": dg.MetadataValue.int(counts["direct"]),
            "derived_tombstoned": dg.MetadataValue.int(counts["derived"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )

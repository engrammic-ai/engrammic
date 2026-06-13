"""Dagster asset: propagate heat from hot nodes to neighbors."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext  # noqa: F401
from opentelemetry import trace

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource

tracer = trace.get_tracer(__name__)


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="heat_diffusion",
    deps=["heat", "edge_heat"],
    partitions_def=silo_partitions,
    description="Propagate heat from hot nodes to neighbors via BFS",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "heat_diffusion"},
)
def heat_diffusion_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Propagate heat from hot nodes to neighbors."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.config.diffusion import load_diffusion_config
        from context_service.signals.diffusion import (
            diffuse_heat,
            get_materialization_distribution,
        )

        config = load_diffusion_config()

        if not config.enabled:
            context.log.info(f"silo={silo_id} heat_diffusion disabled, skipping")
            return {"skipped": True}

        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        store = MemgraphClient(driver)

        with tracer.start_as_current_span("heat_diffusion") as span:
            span.set_attribute("silo_id", silo_id)

            result = await diffuse_heat(store, silo_id, config)  # type: ignore[arg-type]

            span.set_attribute("hot_nodes", result.hot_nodes)
            span.set_attribute("nodes_updated", result.nodes_updated)

            distribution = await get_materialization_distribution(store, silo_id)  # type: ignore[arg-type]

        return {
            "silo_id": silo_id,
            "hot_nodes": result.hot_nodes,
            "nodes_updated": result.nodes_updated,
            "edge_traversals": result.edge_traversals,
            "distribution": distribution,
        }

    output = _run_async(_run())
    duration_s = time.monotonic() - t0

    if output.get("skipped"):
        return dg.Output(value=output)

    context.log.info(
        f"silo={silo_id} hot_nodes={output['hot_nodes']} "
        f"nodes_updated={output['nodes_updated']} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={**output, "duration_s": duration_s},
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "hot_nodes": dg.MetadataValue.int(output["hot_nodes"]),
            "nodes_updated": dg.MetadataValue.int(output["nodes_updated"]),
            "edge_traversals": dg.MetadataValue.json(output["edge_traversals"]),
            "distribution": dg.MetadataValue.json(output["distribution"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["heat_diffusion_asset"]

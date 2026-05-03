"""Dagster asset: pattern_detection — detect co_occurrence and causal_chain patterns per silo."""

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling nested event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="pattern_detection",
    partitions_def=silo_partitions,
    ins={"claim_to_fact_promotion": dg.AssetIn("claim_to_fact_promotion")},
    description=(
        "Detect co_occurrence and causal_chain :Pattern nodes for the silo partition.  "
        "Gated behind settings.pattern.detection_enabled.  "
        "Also applies exponential confidence decay to stale patterns."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "pattern_detection"},
)
def pattern_detection(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    claim_to_fact_promotion: dg.Nothing,  # type: ignore[valid-type]  # noqa: ARG001 — Dagster dep marker
) -> dg.Output[dict[str, Any]]:
    """Run co_occurrence and causal_chain detection plus pattern decay for the silo partition."""
    settings = get_settings()
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    if not settings.pattern.detection_enabled:
        context.log.info(f"silo={silo_id} pattern detection disabled — skipping")
        return dg.Output(
            value={
                "silo_id": silo_id,
                "co_occurrence_patterns": 0,
                "causal_chain_patterns": 0,
                "patterns_decayed": 0,
                "patterns_tombstoned": 0,
                "skipped": True,
                "duration_s": 0.0,
            },
            metadata={
                "silo_id": dg.MetadataValue.text(silo_id),
                "skipped": dg.MetadataValue.bool(True),
                "co_occurrence_patterns": dg.MetadataValue.int(0),
                "causal_chain_patterns": dg.MetadataValue.int(0),
            },
        )

    async def _run() -> dict[str, Any]:
        from context_service.engine.patterns import (
            DEFAULT_DECAY_FACTOR,
            DEFAULT_DETECTION_LIMIT,
            DEFAULT_MIN_CONFIDENCE,
            decay_patterns,
            detect_patterns,
            process_causal_chain_candidates,
            process_co_occurrence_candidates,
        )
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        _client = MemgraphClient(driver)
        # MemgraphClient satisfies HyperGraphStore structurally; cast for mypy.
        client = cast("HyperGraphStore", _client)

        # --- co_occurrence ---
        co_candidates = await detect_patterns(
            client,
            silo_id,
            "co_occurrence",
            limit=DEFAULT_DETECTION_LIMIT,
        )
        co_count = await process_co_occurrence_candidates(client, silo_id, co_candidates)

        # --- causal_chain ---
        chain_candidates = await detect_patterns(
            client,
            silo_id,
            "causal_chain",
            limit=DEFAULT_DETECTION_LIMIT,
        )
        chain_count = await process_causal_chain_candidates(client, silo_id, chain_candidates)

        # --- decay: treat patterns not observed in the last 7 days as stale ---
        stale_cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        decayed, tombstoned = await decay_patterns(
            client,
            silo_id,
            decay_factor=DEFAULT_DECAY_FACTOR,
            stale_before_iso=stale_cutoff,
            min_confidence=DEFAULT_MIN_CONFIDENCE,
        )

        return {
            "silo_id": silo_id,
            "co_occurrence_patterns": co_count,
            "causal_chain_patterns": chain_count,
            "patterns_decayed": decayed,
            "patterns_tombstoned": tombstoned,
            "skipped": False,
        }

    result: dict[str, Any] = _run_async(_run())
    duration_s = time.monotonic() - t0
    result["duration_s"] = duration_s

    context.log.info(
        f"silo={silo_id} "
        f"co_occurrence={result['co_occurrence_patterns']} "
        f"causal_chain={result['causal_chain_patterns']} "
        f"decayed={result['patterns_decayed']} "
        f"tombstoned={result['patterns_tombstoned']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value=result,
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "co_occurrence_patterns": dg.MetadataValue.int(result["co_occurrence_patterns"]),
            "causal_chain_patterns": dg.MetadataValue.int(result["causal_chain_patterns"]),
            "patterns_decayed": dg.MetadataValue.int(result["patterns_decayed"]),
            "patterns_tombstoned": dg.MetadataValue.int(result["patterns_tombstoned"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )

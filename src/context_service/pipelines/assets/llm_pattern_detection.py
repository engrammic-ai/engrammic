"""Dagster asset: llm_pattern_detection — LLM-based semantic pattern detection per silo.

Runs after clustering and pattern_detection (v1.3a).  Sends each Leiden cluster's
facts to Haiku for classification; accepted results are persisted via the v1.3a
pattern infrastructure (create_or_update_pattern).

Feature flag: settings.pattern.llm_enabled (requires settings.pattern.detection_enabled).
Batch size: 50 clusters per run (plan decision).
Scheduling: daily, after clustering asset.

Fail-safes:
- Per-cluster LLM timeout: skip cluster, log warning, continue.
- Error rate > 10% within a window: circuit breaker trips, disables for 1 hour.
- Confidence < 0.3: pattern discarded (hallucination filter).
"""

import asyncio
import concurrent.futures
import time
from typing import TYPE_CHECKING, Any, cast

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

# Batch size: plan specifies 50 clusters per run.
_BATCH_SIZE = 50

# Circuit breaker: trip after 10% failures in a 60-second window; cooldown 1 hour.
# For 50 clusters, 5 failures (10%) trips the breaker.
_CB_FAILURE_THRESHOLD = 5
_CB_WINDOW_S = 60.0
_CB_COOLDOWN_S = 3600.0

_CB_SERVICE_NAME = "llm_pattern_detection"


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling nested event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=600)


@dg.asset(
    name="llm_pattern_detection",
    partitions_def=silo_partitions,
    deps=["pattern_detection", "clustering"],
    description=(
        "LLM-based semantic pattern detection for the silo partition.  "
        "Classifies Leiden cluster facts via Haiku and persists accepted patterns "
        "using the v1.3a pattern infrastructure.  "
        "Gated behind settings.pattern.llm_enabled."
    ),
    retry_policy=dg.RetryPolicy(max_retries=1, delay=30.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "llm_pattern_detection"},
)
def llm_pattern_detection(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Run LLM-based pattern detection for the silo partition."""
    settings = get_settings()
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    _empty_result: dict[str, Any] = {
        "silo_id": silo_id,
        "patterns_accepted": 0,
        "patterns_discarded_low_confidence": 0,
        "clusters_timed_out": 0,
        "clusters_errored": 0,
        "circuit_breaker_tripped": False,
        "skipped": True,
        "duration_s": 0.0,
    }

    if not settings.pattern.detection_enabled or not settings.pattern.llm_enabled:
        reason = (
            "detection_enabled=False"
            if not settings.pattern.detection_enabled
            else "llm_enabled=False"
        )
        context.log.info(f"silo={silo_id} llm_pattern_detection disabled ({reason}) — skipping")
        return dg.Output(
            value=_empty_result,
            metadata={
                "silo_id": dg.MetadataValue.text(silo_id),
                "skipped": dg.MetadataValue.bool(True),
                "patterns_accepted": dg.MetadataValue.int(0),
            },
        )

    async def _run() -> dict[str, Any]:
        from context_service.db.queries import BATCH_GET_FACTS_BY_CLUSTERS, LIST_CLUSTERS
        from context_service.engine.llm_patterns import process_llm_candidates
        from context_service.extraction.filter.circuit_breaker import get_or_create
        from context_service.llm import build_llm_provider
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        _client = MemgraphClient(driver)
        store = cast("HyperGraphStore", _client)

        # --- Load clusters ---
        cluster_rows = await store.execute_query(
            LIST_CLUSTERS,
            {
                "silo_id": silo_id,
                "level": None,
                "offset": 0,
                "limit": _BATCH_SIZE,
            },
        )

        if not cluster_rows:
            context.log.info(f"silo={silo_id} no clusters found — skipping")
            return {
                "silo_id": silo_id,
                "patterns_accepted": 0,
                "patterns_discarded_low_confidence": 0,
                "clusters_timed_out": 0,
                "clusters_errored": 0,
                "circuit_breaker_tripped": False,
                "skipped": False,
            }

        # --- Fetch facts per cluster (batched to avoid N+1) ---
        cluster_ids = []
        for row in cluster_rows:
            cluster_node = row.get("c", row)
            cluster_id = str(
                cluster_node.get("id", cluster_node)
                if isinstance(cluster_node, dict)
                else cluster_node
            )
            cluster_ids.append(cluster_id)

        fact_rows = await store.execute_query(
            BATCH_GET_FACTS_BY_CLUSTERS,
            {"cluster_ids": cluster_ids, "silo_id": silo_id},
        )

        # Group facts by cluster_id client-side
        from collections import defaultdict

        facts_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in fact_rows:
            cid = str(r.get("cluster_id", ""))
            facts_by_cluster[cid].append(r)

        clusters: list[dict[str, Any]] = []
        for cluster_id in cluster_ids:
            cluster_facts = facts_by_cluster.get(cluster_id, [])
            if not cluster_facts:
                continue
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "facts": [
                        {
                            "content": str(r.get("content", "")),
                            "confidence": float(r.get("confidence", 1.0)),
                            "valid_from": r.get("valid_from"),
                        }
                        for r in cluster_facts
                    ],
                    "fact_ids": [str(r.get("fact_id", "")) for r in cluster_facts],
                }
            )

        if not clusters:
            context.log.info(f"silo={silo_id} no clusters with facts — skipping")
            return {
                "silo_id": silo_id,
                "patterns_accepted": 0,
                "patterns_discarded_low_confidence": 0,
                "clusters_timed_out": 0,
                "clusters_errored": 0,
                "circuit_breaker_tripped": False,
                "skipped": False,
            }

        # --- Circuit breaker ---
        cb = await get_or_create(
            silo_id,
            _CB_SERVICE_NAME,
            failure_threshold=_CB_FAILURE_THRESHOLD,
            window_s=_CB_WINDOW_S,
            cooldown_s=_CB_COOLDOWN_S,
        )

        if await cb.is_open():
            context.log.warning(
                f"silo={silo_id} llm_pattern circuit breaker open — skipping entire batch"
            )
            return {
                "silo_id": silo_id,
                "patterns_accepted": 0,
                "patterns_discarded_low_confidence": 0,
                "clusters_timed_out": 0,
                "clusters_errored": 0,
                "circuit_breaker_tripped": True,
                "skipped": False,
            }

        # --- LLM provider (from models.yaml) ---
        model_spec = settings.models.get_model("pattern_detection")
        llm = build_llm_provider(model_spec.provider, model=model_spec.model)
        try:
            process_result = await process_llm_candidates(
                store,
                silo_id,
                clusters,
                llm,
                cb=cb,
            )
        finally:
            await llm.close()

        return {
            "silo_id": silo_id,
            "patterns_accepted": process_result.patterns_accepted,
            "patterns_discarded_low_confidence": process_result.patterns_discarded_low_confidence,
            "clusters_timed_out": process_result.clusters_timed_out,
            "clusters_errored": process_result.clusters_errored,
            "circuit_breaker_tripped": process_result.circuit_breaker_tripped,
            "skipped": False,
        }

    result: dict[str, Any] = _run_async(_run())
    duration_s = time.monotonic() - t0
    result["duration_s"] = duration_s

    context.log.info(
        f"silo={silo_id} "
        f"accepted={result['patterns_accepted']} "
        f"discarded_low_conf={result['patterns_discarded_low_confidence']} "
        f"timed_out={result['clusters_timed_out']} "
        f"errored={result['clusters_errored']} "
        f"cb_tripped={result['circuit_breaker_tripped']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value=result,
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "patterns_accepted": dg.MetadataValue.int(result["patterns_accepted"]),
            "patterns_discarded_low_confidence": dg.MetadataValue.int(
                result["patterns_discarded_low_confidence"]
            ),
            "clusters_timed_out": dg.MetadataValue.int(result["clusters_timed_out"]),
            "clusters_errored": dg.MetadataValue.int(result["clusters_errored"]),
            "circuit_breaker_tripped": dg.MetadataValue.bool(result["circuit_breaker_tripped"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )

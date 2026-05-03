"""Dagster sensor: confidence_drift_sensor — warn when mean edge confidence drifts.

Polls Memgraph for mean edge/belief confidence per silo and compares against a
rolling baseline stored in the sensor cursor.  Logs a warning (but does not
block runs) when the mean drops more than DRIFT_THRESHOLD from baseline.
"""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg
import structlog

from context_service.pipelines.resources import MemgraphResource
from context_service.utils.json import JSONDecodeError, dumps, loads

logger = structlog.get_logger(__name__)

# How many points below baseline triggers the warning.
DRIFT_THRESHOLD = 0.1

_MEAN_EDGE_CONFIDENCE = """
MATCH ()-[r:CAUSES {silo_id: $silo_id}]->()
WHERE (r.invalidated IS NULL OR r.invalidated = false)
  AND r.consensus_confidence IS NOT NULL
RETURN avg(r.consensus_confidence) AS mean_confidence, count(r) AS sample_size
"""

_MEAN_BELIEF_CONFIDENCE = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.confidence IS NOT NULL
RETURN avg(b.confidence) AS mean_confidence, count(b) AS sample_size
"""

_LIST_ACTIVE_SILOS = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 100
"""

_MIN_SAMPLE_SIZE = 5  # Don't compute drift with fewer than this many observations.


def _parse_cursor(cursor: str | None) -> dict[str, dict[str, float]]:
    """Cursor schema: {silo_id: {"edge_baseline": float, "belief_baseline": float}}."""
    if not cursor:
        return {}
    try:
        data: dict[str, dict[str, float]] = loads(cursor)
        return data
    except JSONDecodeError:
        return {}


@dg.sensor(
    name="confidence_drift_sensor",
    minimum_interval_seconds=300,
    description=(
        "Polls mean edge/belief confidence per silo. "
        "Logs a warning when the mean drops more than 0.1 from the established baseline. "
        "Does not block pipeline runs."
    ),
)
def confidence_drift_sensor(
    context: dg.SensorEvaluationContext,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Check mean confidence per silo and warn on drift."""

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        silo_rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        silo_ids = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]

        readings: list[dict[str, Any]] = []
        for silo_id in silo_ids:
            edge_rows = await client.execute_query(_MEAN_EDGE_CONFIDENCE, {"silo_id": silo_id})
            belief_rows = await client.execute_query(_MEAN_BELIEF_CONFIDENCE, {"silo_id": silo_id})

            edge_mean: float | None = None
            edge_n = 0
            if edge_rows:
                raw = edge_rows[0].get("mean_confidence")
                edge_n = int(edge_rows[0].get("sample_size", 0))
                if raw is not None and edge_n >= _MIN_SAMPLE_SIZE:
                    edge_mean = float(raw)

            belief_mean: float | None = None
            belief_n = 0
            if belief_rows:
                raw = belief_rows[0].get("mean_confidence")
                belief_n = int(belief_rows[0].get("sample_size", 0))
                if raw is not None and belief_n >= _MIN_SAMPLE_SIZE:
                    belief_mean = float(raw)

            readings.append(
                {
                    "silo_id": silo_id,
                    "edge_mean": edge_mean,
                    "edge_n": edge_n,
                    "belief_mean": belief_mean,
                    "belief_n": belief_n,
                }
            )
        return readings

    readings = asyncio.run(_poll())
    cursor_data = _parse_cursor(context.cursor)

    for r in readings:
        silo_id: str = r["silo_id"]
        silo_cursor = cursor_data.setdefault(silo_id, {})

        # Edge confidence drift check
        if r["edge_mean"] is not None:
            edge_mean: float = r["edge_mean"]
            if "edge_baseline" not in silo_cursor:
                silo_cursor["edge_baseline"] = edge_mean
                context.log.info(
                    f"confidence_drift: silo={silo_id} edge_baseline established={edge_mean:.3f} n={r['edge_n']}"
                )
            else:
                baseline: float = silo_cursor["edge_baseline"]
                drop = baseline - edge_mean
                if drop > DRIFT_THRESHOLD:
                    context.log.warning(
                        f"confidence_drift: silo={silo_id} edge_confidence_dropped "
                        f"baseline={baseline:.3f} current={edge_mean:.3f} drop={drop:.3f} n={r['edge_n']}"
                    )
                    logger.warning(
                        "confidence_drift_edge",
                        silo_id=silo_id,
                        baseline=baseline,
                        current=edge_mean,
                        drop=drop,
                        sample_size=r["edge_n"],
                    )
                # Update baseline with a dampened exponential moving average
                # (alpha=0.1 so a single bad batch doesn't shift baseline far).
                silo_cursor["edge_baseline"] = 0.9 * baseline + 0.1 * edge_mean

        # Belief confidence drift check
        if r["belief_mean"] is not None:
            belief_mean: float = r["belief_mean"]
            if "belief_baseline" not in silo_cursor:
                silo_cursor["belief_baseline"] = belief_mean
                context.log.info(
                    f"confidence_drift: silo={silo_id} belief_baseline established={belief_mean:.3f} n={r['belief_n']}"
                )
            else:
                baseline = silo_cursor["belief_baseline"]
                drop = baseline - belief_mean
                if drop > DRIFT_THRESHOLD:
                    context.log.warning(
                        f"confidence_drift: silo={silo_id} belief_confidence_dropped "
                        f"baseline={baseline:.3f} current={belief_mean:.3f} drop={drop:.3f} n={r['belief_n']}"
                    )
                    logger.warning(
                        "confidence_drift_belief",
                        silo_id=silo_id,
                        baseline=baseline,
                        current=belief_mean,
                        drop=drop,
                        sample_size=r["belief_n"],
                    )
                silo_cursor["belief_baseline"] = 0.9 * baseline + 0.1 * belief_mean

    return dg.SensorResult(run_requests=[], cursor=dumps(cursor_data))

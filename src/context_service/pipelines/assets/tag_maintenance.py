"""Dagster asset: tag_maintenance — daily pruning of stale dynamic tags per silo.

For each silo partition, queries Memgraph for dynamic tags that have not been
used on any node within the configured demotion window, then removes them from
the silo's TagConfigService record in Postgres.

Design notes:
- Uses get_session() from context_service.db directly (no PostgresResource).
- Queries Memgraph for tag usage via MemgraphResource (rule 8).
- Drives async logic via run_async from pipelines.utils.
- demotion_days is read from the silo's SiloTagConfig.settings, falling back to
  DEFAULT_SETTINGS["demotion_days"] (30) if the config row does not exist.
"""

import time
from typing import Any
from uuid import UUID

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource
from context_service.pipelines.utils import run_async

# Query all distinct tag values that appear on nodes for a given silo within the
# demotion window.  A tag is "used" if any node carries it and was stored or
# updated within the window.
_ACTIVE_TAGS_CYPHER = """
MATCH (n)
WHERE n.silo_id = $silo_id
  AND n.tags IS NOT NULL
  AND (
    n.stored_at >= $cutoff
    OR n.updated_at >= $cutoff
  )
UNWIND n.tags AS tag
RETURN DISTINCT tag
"""


@dg.asset(
    name="tag_maintenance",
    partitions_def=silo_partitions,
    description=(
        "Daily pruning of dynamic tags that have not appeared on any node within "
        "the silo's demotion window. Removes stale entries from SiloTagConfig."
    ),
    compute_kind="postgres",
    group_name="maintenance",
    retry_policy=dg.RetryPolicy(max_retries=1, delay=30.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "tag_maintenance"},
)
def tag_maintenance(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Prune stale dynamic tags for the silo partition."""
    silo_id_str: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        import datetime

        from context_service.db import get_session
        from context_service.models.tag_config import DEFAULT_SETTINGS
        from context_service.services.tag_config import TagConfigService

        silo_uuid = UUID(silo_id_str)

        # Resolve demotion_days from the silo config; fall back to default.
        async with get_session() as session:
            svc = TagConfigService(session)
            cfg = await svc.get(silo_uuid)
            if cfg is None:
                context.log.info(f"silo={silo_id_str} no tag config found, skipping")
                return {"silo_id": silo_id_str, "demoted": 0, "skipped": 0}

            dynamic_tags: list[str] = list(cfg.dynamic_tags or [])
            demotion_days: int = int(
                (cfg.settings or {}).get("demotion_days", DEFAULT_SETTINGS["demotion_days"])
            )

        if not dynamic_tags:
            context.log.info(f"silo={silo_id_str} no dynamic tags registered, skipping")
            return {"silo_id": silo_id_str, "demoted": 0, "skipped": 0}

        cutoff = (
            datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(days=demotion_days)
        ).isoformat()

        # Query Memgraph for tags active within the window.
        driver = await memgraph.driver()
        async with driver.session() as mg_session:
            result = await mg_session.run(
                _ACTIVE_TAGS_CYPHER,
                silo_id=silo_id_str,
                cutoff=cutoff,
            )
            rows = await result.data()

        active_tags: set[str] = {str(r["tag"]) for r in rows if r.get("tag")}
        stale = [t for t in dynamic_tags if t not in active_tags]

        if not stale:
            context.log.info(
                f"silo={silo_id_str} demotion_days={demotion_days} "
                f"all {len(dynamic_tags)} dynamic tags active, nothing to prune"
            )
            return {"silo_id": silo_id_str, "demoted": 0, "skipped": len(dynamic_tags)}

        # Remove stale tags.
        async with get_session() as session:
            svc = TagConfigService(session)
            await svc.remove_dynamic_tags(silo_uuid, stale)

        context.log.info(
            f"silo={silo_id_str} demotion_days={demotion_days} "
            f"demoted={len(stale)} tags={stale}"
        )
        return {
            "silo_id": silo_id_str,
            "demoted": len(stale),
            "skipped": len(dynamic_tags) - len(stale),
        }

    result: dict[str, Any] = run_async(_run())
    duration_s = time.monotonic() - t0
    result["duration_s"] = duration_s

    context.log.info(
        f"silo={silo_id_str} "
        f"demoted={result['demoted']} "
        f"skipped={result['skipped']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value=result,
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id_str),
            "demoted": dg.MetadataValue.int(result["demoted"]),
            "skipped": dg.MetadataValue.int(result["skipped"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["tag_maintenance"]

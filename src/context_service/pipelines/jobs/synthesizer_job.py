"""Dagster job for synthesizing ProposedBeliefs from corroborating Facts (SAGE Phase C).

synthesizer_op: query active silos, find corroborating fact pairs, and call
synthesize_from_facts() for each qualified candidate.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import dagster as dg
import structlog
from dagster import ScheduleDefinition  # noqa: F401 (re-exported)

from context_service.config.settings import SynthesisSettings
from context_service.pipelines.resources import LLMResource, MemgraphResource
from context_service.synthesis.trigger import (
    evaluate_synthesis_candidates,
    find_corroborating_facts,
)

if TYPE_CHECKING:
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

_LIST_ACTIVE_SILOS = """
MATCH (n) WHERE n.silo_id IS NOT NULL RETURN DISTINCT n.silo_id AS silo_id LIMIT 100
"""


async def run_synthesis_for_silo(
    store: Any,
    silo_id: str,
    llm: LLMProvider,
    settings: SynthesisSettings,
    log: Any,
) -> dict[str, int]:
    """Run synthesis pipeline for a single silo.

    Finds corroborating fact pairs, evaluates independence, and calls
    synthesize_from_facts() for each qualified candidate.
    """
    from context_service.sage.transactions import synthesize_from_facts

    candidates = await find_corroborating_facts(
        store,
        silo_id=silo_id,
        similarity_threshold=settings.similarity_threshold,
    )

    if not candidates:
        log.info(f"synthesizer_op: silo={silo_id} no corroborating candidates")
        return {"synthesized": 0, "skipped": 0, "errors": 0}

    qualified = await evaluate_synthesis_candidates(
        store,
        candidates=candidates,
        threshold=settings.independence_threshold,
        silo_id=silo_id,
    )

    log.info(
        f"synthesizer_op: silo={silo_id} candidates={len(candidates)} qualified={len(qualified)}"
    )

    synthesized = 0
    skipped = 0
    errors = 0

    for candidate in qualified:
        try:
            result, _ = await synthesize_from_facts(
                store,
                fact_ids=candidate.fact_ids,
                silo_id=silo_id,
                llm=llm,
                mode="async",
            )
            if result.belief_id is not None:
                synthesized += 1
                logger.info(
                    "synthesizer.proposed_belief_created",
                    belief_id=result.belief_id,
                    silo_id=silo_id,
                    fact_count=result.fact_count,
                    confidence=result.confidence,
                )
                log.info(
                    f"synthesizer_op: created belief_id={result.belief_id}"
                    f" silo={silo_id} facts={result.fact_count}"
                )
            else:
                skipped += 1
                logger.info(
                    "synthesizer.candidate_skipped",
                    silo_id=silo_id,
                    fact_ids=candidate.fact_ids,
                    fact_count=result.fact_count,
                    confidence=result.confidence,
                    timed_out=result.timed_out,
                )
                log.info(f"synthesizer_op: skipped silo={silo_id} fact_ids={candidate.fact_ids}")
        except Exception as exc:
            errors += 1
            logger.error(
                "synthesizer.error",
                silo_id=silo_id,
                fact_ids=candidate.fact_ids,
                error=str(exc),
            )
            log.info(
                f"synthesizer_op: error silo={silo_id} fact_ids={candidate.fact_ids} error={exc}"
            )

    return {"synthesized": synthesized, "skipped": skipped, "errors": errors}


@dg.op(required_resource_keys={"memgraph", "llm"})
def synthesizer_op(context) -> dict[str, int]:
    """Synthesize ProposedBeliefs from corroborating Facts."""
    memgraph: MemgraphResource = context.resources.memgraph
    llm_resource: LLMResource = context.resources.llm

    async def _run() -> dict[str, int]:
        from context_service.config.settings import get_settings

        settings = get_settings()
        synthesis_settings = settings.synthesis

        if synthesis_settings.tier == "disabled":
            context.log.info("synthesizer_op: synthesis disabled, skipping")
            return {"synthesized": 0, "skipped": 0, "errors": 0}

        store = await memgraph.store()
        llm = llm_resource.get_client()

        silo_rows = await store.execute_query(_LIST_ACTIVE_SILOS, {})
        silos = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]
        context.log.info(f"synthesizer_op: scanning {len(silos)} silo(s)")

        total: dict[str, int] = {"synthesized": 0, "skipped": 0, "errors": 0}
        for silo_id in silos:
            counts = await run_synthesis_for_silo(
                store, silo_id, llm, synthesis_settings, context.log
            )
            for key in total:
                total[key] += counts[key]

        return total

    result = asyncio.run(_run())
    context.log.info(
        f"synthesizer_op: done synthesized={result['synthesized']}"
        f" skipped={result['skipped']} errors={result['errors']}"
    )
    return result


@dg.job(
    name="sage_synthesizer_job",
    description="SAGE Phase C: synthesize ProposedBeliefs from corroborating Facts every 15 minutes.",
)
def sage_synthesizer_job() -> None:
    """Belief synthesis job."""
    synthesizer_op()


sage_synthesizer_schedule = ScheduleDefinition(
    job=sage_synthesizer_job,
    cron_schedule="*/15 * * * *",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

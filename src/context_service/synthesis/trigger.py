"""Synthesis trigger for CITE v2 belief synthesis pipeline.

Queries the graph for corroborating fact pairs sharing entity mentions,
evaluates independence scores, and emits synthesis requests when the
independence threshold is met.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from context_service.config.logging import get_logger
from context_service.config.settings import SynthesisSettings
from context_service.engine.protocols import HyperGraphStore
from context_service.synthesis.independence import FactMetadata, check_synthesis_threshold

logger = get_logger(__name__)

__all__ = [
    "CorroborationCandidate",
    "evaluate_synthesis_candidates",
    "find_corroborating_facts",
    "trigger_synthesis",
]

_CORROBORATION_QUERY = """
MATCH (a:Fact {silo_id: $silo_id})-[:CORROBORATES]-(b:Fact)
WHERE a.id < b.id
MATCH (a)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(b)
RETURN a.id AS fact_a_id, b.id AS fact_b_id, collect(e.name) AS shared_entities
"""

_FACT_METADATA_QUERY = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.id IN $fact_ids
RETURN f.id AS fact_id, f.document_id AS document_id, f.agent_id AS agent_id,
       f.created_at AS created_at, f.source_tier AS source_tier
"""


@dataclass
class CorroborationCandidate:
    """A pair (or group) of facts that share corroboration and entity mentions."""

    fact_ids: list[str]
    shared_entities: list[str]
    independence_score: float = field(default=0.0)


async def find_corroborating_facts(
    graph_store: HyperGraphStore,
    silo_id: str,
    similarity_threshold: float,  # noqa: ARG001
) -> list[CorroborationCandidate]:
    """Query for fact pairs that share CORROBORATES edges and at least one entity.

    The similarity_threshold parameter is available for callers to pass but is
    not applied at the graph layer — CORROBORATES edges are created by the
    extraction pipeline at ingest time and already encode semantic similarity.

    Args:
        graph_store: Graph storage backend.
        silo_id: Silo to scope the query.
        similarity_threshold: Reserved for caller-side filtering; not applied here.

    Returns:
        List of CorroborationCandidate, one per corroborating fact pair.
    """
    rows = await graph_store.execute_query(
        _CORROBORATION_QUERY,
        {"silo_id": silo_id},
    )

    candidates: list[CorroborationCandidate] = []
    for row in rows:
        fact_a = row.get("fact_a_id") or row.get("a.id")
        fact_b = row.get("fact_b_id") or row.get("b.id")
        shared = row.get("shared_entities") or row.get("collect(e.name)") or []

        if not fact_a or not fact_b:
            continue

        candidates.append(
            CorroborationCandidate(
                fact_ids=[fact_a, fact_b],
                shared_entities=list(shared),
            )
        )

    logger.debug("corroboration_candidates_found", silo_id=silo_id, count=len(candidates))
    return candidates


async def evaluate_synthesis_candidates(
    graph_store: HyperGraphStore,
    candidates: list[CorroborationCandidate],
    threshold: float,
) -> list[CorroborationCandidate]:
    """Filter candidates to those that meet the independence threshold.

    Fetches FactMetadata from the graph for each unique fact referenced in
    candidates, calculates pairwise independence, and returns only those
    candidates whose score meets or exceeds threshold.

    Args:
        graph_store: Graph storage backend.
        candidates: Candidates from find_corroborating_facts.
        threshold: Minimum independence score (passed to check_synthesis_threshold).

    Returns:
        Subset of candidates that cleared the threshold.
    """
    if not candidates:
        return []

    # Collect unique fact IDs across all candidates
    all_fact_ids: list[str] = list(
        {fid for c in candidates for fid in c.fact_ids}
    )

    # Infer silo_id from graph_store context; fetch metadata without silo filter
    # when no silo is available — callers already scope by silo upstream.
    rows = await graph_store.execute_query(
        """
        MATCH (f:Fact)
        WHERE f.id IN $fact_ids
        RETURN f.id AS fact_id, f.document_id AS document_id, f.agent_id AS agent_id,
               f.created_at AS created_at, f.source_tier AS source_tier
        """,
        {"fact_ids": all_fact_ids},
    )

    metadata_by_id: dict[str, FactMetadata] = {}
    for row in rows:
        fid = row.get("fact_id") or row.get("f.id")
        if not fid:
            continue

        raw_ts = row.get("created_at") or row.get("f.created_at")
        created_at: datetime | None = None
        if isinstance(raw_ts, datetime):
            created_at = raw_ts
        elif isinstance(raw_ts, str):
            with contextlib.suppress(ValueError):
                created_at = datetime.fromisoformat(raw_ts)

        metadata_by_id[fid] = FactMetadata(
            fact_id=fid,
            document_id=row.get("document_id") or row.get("f.document_id"),
            agent_id=row.get("agent_id") or row.get("f.agent_id"),
            created_at=created_at,
            source_tier=row.get("source_tier") or row.get("f.source_tier"),
        )

    qualified: list[CorroborationCandidate] = []
    for candidate in candidates:
        facts = [metadata_by_id[fid] for fid in candidate.fact_ids if fid in metadata_by_id]
        if len(facts) < 2:
            logger.debug(
                "candidate_skipped_missing_metadata",
                fact_ids=candidate.fact_ids,
                resolved=len(facts),
            )
            continue

        passes = check_synthesis_threshold(facts, threshold)
        # Compute pairwise sum for the candidate's independence_score field
        from itertools import combinations

        from context_service.synthesis.independence import calculate_independence

        score = sum(calculate_independence(a, b) for a, b in combinations(facts, 2))
        candidate.independence_score = score

        if passes:
            qualified.append(candidate)

    logger.debug(
        "candidates_evaluated",
        total=len(candidates),
        qualified=len(qualified),
        threshold=threshold,
    )
    return qualified


async def trigger_synthesis(
    graph_store: HyperGraphStore,
    silo_id: str,
    settings: SynthesisSettings,
) -> list[str]:
    """Orchestrate corroboration discovery and emit synthesis requests.

    Finds corroborating fact pairs, evaluates independence, and for each
    qualifying candidate logs a synthesis request. Actual belief creation
    is handled by a downstream synthesizer component.

    Args:
        graph_store: Graph storage backend.
        silo_id: Silo to scope the synthesis run.
        settings: Synthesis configuration (thresholds and tier).

    Returns:
        List of synthesis request IDs emitted during this run.
    """
    if settings.tier == "disabled":
        logger.info("synthesis_disabled", silo_id=silo_id)
        return []

    log = logger.bind(silo_id=silo_id, tier=settings.tier)
    log.info("synthesis_trigger_start")

    candidates = await find_corroborating_facts(
        graph_store,
        silo_id=silo_id,
        similarity_threshold=settings.similarity_threshold,
    )

    if not candidates:
        log.info("synthesis_trigger_no_candidates")
        return []

    qualified = await evaluate_synthesis_candidates(
        graph_store,
        candidates=candidates,
        threshold=settings.independence_threshold,
    )

    request_ids: list[str] = []
    for candidate in qualified:
        request_id = str(uuid.uuid4())
        log.info(
            "synthesis_request_emitted",
            request_id=request_id,
            fact_ids=candidate.fact_ids,
            shared_entities=candidate.shared_entities,
            independence_score=round(candidate.independence_score, 4),
        )
        request_ids.append(request_id)

    log.info(
        "synthesis_trigger_complete",
        requests_emitted=len(request_ids),
        candidates_evaluated=len(candidates),
    )
    return request_ids

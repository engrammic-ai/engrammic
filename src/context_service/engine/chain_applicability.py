"""Reasoning chain applicability matching.

Three-layer funnel:

1. Query intent similarity (Qdrant ANN with configurable threshold).
2. Step-level DTW similarity (warm start only; skipped on cold start).
3. Evidence accessibility check.

Each layer narrows the candidate set. The first chain that passes all layers
is returned; if none pass, returns None.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from context_service.config.settings import get_settings
from context_service.engine.dtw import dtw_similarity
from context_service.telemetry.metrics import record_chain_lookup

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Module-level helpers (designed for testability via patching)
# ---------------------------------------------------------------------------


async def embed_query(query: str) -> list[float]:
    """Embed a query string using the configured embedding service."""
    from context_service.embeddings import build_embedding_service

    svc = build_embedding_service()
    return await svc.embed_single(query)


REASONING_CHAINS_COLLECTION = "reasoning_chains"


async def search_chains(
    query_embedding: list[float],
    top_k: int,
    threshold: float,
    silo_id: str,
) -> list[dict[str, Any]]:
    """Search Qdrant for chains similar to the given query embedding.

    Queries the dedicated reasoning_chains collection with silo_id filter.

    Returns a list of dicts with keys:
        id (str): Chain node ID.
        score (float): Similarity score.
        step_embeddings (list[list[float]]): Per-step embeddings (may be empty).
        evidence_used (list[str]): Evidence node IDs referenced by the chain.
        payload (dict): Raw Qdrant payload.
    """
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models as qdrant_models

    settings = get_settings()
    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
    )

    try:
        # Check if collection exists
        collections = await client.get_collections()
        if REASONING_CHAINS_COLLECTION not in {c.name for c in collections.collections}:
            return []

        response = await client.query_points(
            collection_name=REASONING_CHAINS_COLLECTION,
            query=query_embedding,
            query_filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="silo_id",
                        match=qdrant_models.MatchValue(value=silo_id),
                    )
                ]
            ),
            limit=top_k,
            score_threshold=threshold,
        )
        results = response.points
    finally:
        await client.close()

    return [
        {
            "id": r.payload.get("node_id", str(r.id)) if r.payload else str(r.id),
            "score": r.score,
            "step_embeddings": r.payload.get("step_embeddings", []) if r.payload else [],
            "evidence_used": r.payload.get("evidence_used", []) if r.payload else [],
            "payload": r.payload or {},
        }
        for r in results
    ]


async def get_session_step_embeddings(session_id: str) -> list[list[float]]:  # noqa: ARG001
    """Return pre-computed step embeddings for the current session's reasoning.

    Returns an empty list when no steps have been recorded (cold start).
    Full implementation requires a session store that persists step embeddings
    as reasoning chains are built.
    """
    return []


async def get_accessible_evidence(silo_id: str, session_id: str) -> set[str]:  # noqa: ARG001
    """Return the set of evidence node IDs accessible within this session context.

    Returns an empty set when evidence access cannot be determined. The empty
    set causes evidence_used.issubset(accessible) to be True only for chains
    with no required evidence, which is a safe default.

    Full implementation requires querying the graph store for nodes reachable
    from the session's knowledge layer.
    """
    return set()


async def log_chain_delivery(
    session_id: str,
    chain_id: str,
    query: str,
    similarity_score: float | None,
) -> None:
    """Persist a chain delivery record for feedback tracking.

    Failures are logged and swallowed so that a Postgres outage does not
    prevent chain delivery.
    """
    try:
        from context_service.db.postgres import get_session
        from context_service.models.postgres.chain_feedback import ChainDelivery

        async with get_session() as db:
            delivery = ChainDelivery(
                session_id=UUID(session_id),
                chain_id=UUID(chain_id),
                query=query,
                similarity_score=similarity_score,
            )
            db.add(delivery)
    except Exception:
        log.warning(
            "chain_delivery_log_failed",
            session_id=session_id,
            chain_id=chain_id,
        )


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


async def find_applicable_chain(
    query: str,
    silo_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    """Find an applicable cached reasoning chain for the given query.

    Three-layer matching:

    1. Query intent similarity via Qdrant ANN. Uses a stricter threshold on
       cold start (no session step hints available) and a relaxed threshold on
       warm start.
    2. Step-level DTW similarity (warm start only). Skipped entirely when
       ``get_session_step_embeddings`` returns an empty list. Aborts the
       candidate loop when cumulative DTW wall time exceeds the configured
       abort threshold.
    3. Evidence accessibility. Chains whose required evidence is not a subset
       of accessible evidence are skipped.

    Args:
        query: Natural-language query to match against cached chains.
        silo_id: Tenant isolation identifier.
        session_id: Current session ID, used to retrieve step hints and
            evidence accessibility.

    Returns:
        The first matching chain dict, or None if no applicable chain is found.
    """
    start_time = time.perf_counter()
    settings = get_settings()
    config = settings.reasoning_chain_matching

    # Determine warm/cold start from session step hints.
    step_hints = await get_session_step_embeddings(session_id)
    is_cold_start = len(step_hints) == 0

    # Embed the query for Layer 1 search.
    query_embedding = await embed_query(query)

    # Layer 1: Qdrant ANN with threshold scaled to warm/cold context.
    threshold = config.query_threshold_cold if is_cold_start else config.query_threshold_warm
    candidates = await search_chains(
        query_embedding=query_embedding,
        top_k=config.top_k_candidates,
        threshold=threshold,
        silo_id=silo_id,
    )

    if not candidates:
        latency_ms = (time.perf_counter() - start_time) * 1000
        record_chain_lookup(
            hit=False,
            layer_reached=1,
            similarity_score=None,
            cold_start=is_cold_start,
            latency_ms=latency_ms,
        )
        return None

    # Resolve accessible evidence once for all candidates.
    accessible = await get_accessible_evidence(silo_id, session_id)

    cumulative_dtw_ms = 0.0

    for chain in candidates:
        similarity_score: float | None

        if is_cold_start:
            # Layer 2 skipped: no step hints available.
            similarity_score = None
        else:
            # Layer 2: DTW step similarity.
            chain_steps: list[list[float]] = chain.get("step_embeddings", [])
            if not chain_steps:
                # No step embeddings stored; cannot perform DTW comparison.
                continue

            dtw_start = time.perf_counter()
            similarity_score = dtw_similarity(chain_steps, step_hints)
            dtw_elapsed_ms = (time.perf_counter() - dtw_start) * 1000
            cumulative_dtw_ms += dtw_elapsed_ms

            if dtw_elapsed_ms > config.dtw_latency_warn_ms:
                log.warning(
                    "dtw_latency_warning",
                    chain_id=chain["id"],
                    dtw_ms=round(dtw_elapsed_ms, 2),
                )

            if cumulative_dtw_ms > config.dtw_latency_abort_ms:
                log.warning(
                    "dtw_latency_abort",
                    cumulative_ms=round(cumulative_dtw_ms, 2),
                )
                break

            if similarity_score < config.step_threshold:
                continue

        # Layer 3: Evidence accessibility.
        evidence_used: set[str] = set(chain.get("evidence_used", []))
        if not evidence_used.issubset(accessible):
            continue

        # All layers passed. Emit telemetry and return.
        await log_chain_delivery(
            session_id=session_id,
            chain_id=chain["id"],
            query=query,
            similarity_score=similarity_score,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000
        record_chain_lookup(
            hit=True,
            layer_reached=3,
            similarity_score=similarity_score,
            cold_start=is_cold_start,
            latency_ms=latency_ms,
        )

        log.info(
            "chain_applicability_hit",
            chain_id=chain["id"],
            cold_start=is_cold_start,
            similarity_score=similarity_score,
            latency_ms=round(latency_ms, 2),
        )

        return chain

    latency_ms = (time.perf_counter() - start_time) * 1000
    record_chain_lookup(
        hit=False,
        layer_reached=3,
        similarity_score=None,
        cold_start=is_cold_start,
        latency_ms=latency_ms,
    )
    return None


async def record_evidence_modification(
    evidence_ids: list[str],
    chain_created_at: str | None,
) -> None:
    """Emit a metric if any evidence was modified after chain creation.

    This is a non-blocking monitoring signal. Failures are silently ignored.

    Full implementation requires querying the graph store for the updated_at
    timestamp of each evidence node and comparing against chain_created_at.
    """
    if not evidence_ids or not chain_created_at:
        return
    # Stub: full implementation wires into the graph store.
    # record_chain_evidence_modified() will be called here once wired.

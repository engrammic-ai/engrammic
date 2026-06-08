"""Dagster asset for background step embedding computation.

Processes reasoning chains that have empty step_embeddings and computes
embeddings for each step's reasoning text. Updates Qdrant with the results.

Per spec: "Background task embeds step, caches on session/WorkingHypothesis.
At lookup time, step embeddings already available (no inline embedding cost)."
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any
from uuid import UUID

import dagster as dg
import structlog

log = structlog.get_logger()


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


REASONING_CHAINS_COLLECTION = "reasoning_chains"


async def get_chains_needing_embedding(
    qdrant_client: Any, limit: int = 100
) -> list[dict[str, Any]]:
    """Find chains in Qdrant with empty step_embeddings.

    Returns list of dicts with chain_id, silo_id, and node_id.
    """
    client = qdrant_client

    collections = await client.get_collections()
    if REASONING_CHAINS_COLLECTION not in {c.name for c in collections.collections}:
        return []

    # Scroll through points, filter for empty step_embeddings
    # Qdrant doesn't support filtering on array length, so we fetch and filter client-side
    result = await client.scroll(
        collection_name=REASONING_CHAINS_COLLECTION,
        limit=limit * 2,  # Fetch extra since we'll filter
        with_payload=True,
        with_vectors=False,
    )

    chains = []
    for point in result[0]:
        payload = point.payload or {}
        step_embeddings = payload.get("step_embeddings", [])
        if not step_embeddings:  # Empty list means needs embedding
            chains.append(
                {
                    "point_id": point.id,
                    "chain_id": payload.get("node_id", str(point.id)),
                    "silo_id": payload.get("silo_id"),
                }
            )
            if len(chains) >= limit:
                break

    return chains


async def get_chain_steps(chain_id: str, silo_id: str) -> list[dict[str, Any]]:
    """Fetch reasoning steps from Postgres for a chain."""
    from sqlalchemy import select

    from context_service.db import get_session
    from context_service.models.postgres.reasoning import ReasoningChainSteps

    try:
        chain_uuid = UUID(chain_id)
        silo_uuid = UUID(silo_id)
    except ValueError:
        return []

    async with get_session() as session:
        result = await session.execute(
            select(ReasoningChainSteps).where(
                ReasoningChainSteps.chain_id == chain_uuid,
                ReasoningChainSteps.silo_id == silo_uuid,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return []
        return row.steps or []


async def embed_steps(steps: list[dict[str, Any]]) -> list[list[float]]:
    """Embed each step's reasoning text."""
    from context_service.embeddings import build_embedding_service

    svc = build_embedding_service()

    # Extract reasoning text from each step
    texts = []
    for step in steps:
        reasoning = step.get("reasoning") or step.get("conclusion") or ""
        if reasoning:
            texts.append(reasoning)

    if not texts:
        return []

    # Batch embed all steps
    embeddings = await svc.embed(texts)
    return embeddings


async def update_chain_step_embeddings(
    qdrant_client: Any,
    point_id: str | int,
    step_embeddings: list[list[float]],
) -> bool:
    """Update the step_embeddings payload in Qdrant."""
    client = qdrant_client

    try:
        await client.set_payload(
            collection_name=REASONING_CHAINS_COLLECTION,
            points=[point_id],
            payload={"step_embeddings": step_embeddings},
        )
        return True
    except Exception as e:
        log.warning("step_embedding_update_failed", point_id=point_id, error=str(e))
        return False


async def process_chain(chain: dict[str, Any]) -> str:
    """Process a single chain: fetch steps, embed, update Qdrant.

    Returns: "success", "no_steps", "embed_failed", or "update_failed"
    """
    qdrant_client = chain.get("_qdrant_client")
    chain_id = chain["chain_id"]
    silo_id = chain["silo_id"]
    point_id = chain["point_id"]

    if not silo_id:
        return "no_silo"

    steps = await get_chain_steps(chain_id, silo_id)
    if not steps:
        return "no_steps"

    try:
        embeddings = await embed_steps(steps)
    except Exception as e:
        log.warning("step_embedding_failed", chain_id=chain_id, error=str(e))
        return "embed_failed"

    if not embeddings:
        return "no_embeddings"

    success = await update_chain_step_embeddings(qdrant_client, point_id, embeddings)
    return "success" if success else "update_failed"


@dg.asset(
    name="step_embedding_backfill",
    description="Computes step embeddings for reasoning chains missing them",
    group_name="chain_feedback",
    required_resource_keys={"qdrant"},
)
def step_embedding_backfill(context) -> dg.Output[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Process chains with empty step_embeddings and compute their embeddings.

    This enables Layer 2 (DTW trajectory matching) in chain applicability.
    """
    t0 = time.monotonic()
    qdrant_resource = context.resources.qdrant

    async def _run() -> dict[str, int]:
        qdrant_client = qdrant_resource.client()
        chains = await get_chains_needing_embedding(qdrant_client, limit=50)
        for chain in chains:
            chain["_qdrant_client"] = qdrant_client

        results = {
            "processed": 0,
            "success": 0,
            "no_steps": 0,
            "embed_failed": 0,
            "update_failed": 0,
            "other": 0,
        }

        for chain in chains:
            try:
                status = await process_chain(chain)
                results["processed"] += 1
                if status in results:
                    results[status] += 1
                else:
                    results["other"] += 1
            except Exception as exc:
                context.log.warning(f"Failed to process chain {chain['chain_id']}: {exc}")
                results["other"] += 1

        return results

    results = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"step_embedding_backfill processed={results['processed']} "
        f"success={results['success']} no_steps={results['no_steps']} "
        f"embed_failed={results['embed_failed']} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={**results, "duration_s": duration_s},
        metadata={
            "processed": dg.MetadataValue.int(results["processed"]),
            "success": dg.MetadataValue.int(results["success"]),
            "no_steps": dg.MetadataValue.int(results["no_steps"]),
            "embed_failed": dg.MetadataValue.int(results["embed_failed"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


async def get_unembedded_hypotheses(
    memgraph_store: Any, limit: int = 100
) -> list[dict[str, Any]]:
    """Find WorkingHypotheses that don't have embeddings yet.

    Queries Memgraph for recent hypotheses, filters out those already
    in session_step_embedding table.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from context_service.db.postgres import get_session as get_pg_session
    from context_service.models.postgres.chain_feedback import SessionStepEmbedding

    store = memgraph_store

    # Get recent WorkingHypotheses from Memgraph (last 1 hour)
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    query = """
    MATCH (h:WorkingHypothesis)
    WHERE h.created_at > $cutoff
    RETURN h.id as id, h.session_id as session_id, h.content as content
    ORDER BY h.created_at DESC
    LIMIT $limit
    """

    try:
        result = await store.execute_query(
            query, {"cutoff": cutoff.isoformat(), "limit": limit * 2}
        )
    except Exception as e:
        log.warning("get_unembedded_hypotheses_query_failed", error=str(e))
        return []

    if not result:
        return []

    # Get already-embedded hypothesis IDs
    async with get_pg_session() as session:
        embedded_result = await session.execute(select(SessionStepEmbedding.hypothesis_id))
        embedded_ids = {str(r) for r in embedded_result.scalars().all()}

    # Filter to unembedded
    hypotheses = []
    for row in result:
        hyp_id = row.get("id")
        if hyp_id and str(hyp_id) not in embedded_ids:
            hypotheses.append(
                {
                    "hypothesis_id": hyp_id,
                    "session_id": row.get("session_id"),
                    "content": row.get("content"),
                }
            )
            if len(hypotheses) >= limit:
                break

    return hypotheses


async def embed_and_store_hypothesis(hypothesis: dict[str, Any]) -> str:
    """Embed a hypothesis and store in session_step_embedding.

    Returns: "success", "no_content", "embed_failed", or "store_failed"
    """
    from context_service.db.postgres import get_session as get_pg_session
    from context_service.embeddings import build_embedding_service
    from context_service.models.postgres.chain_feedback import SessionStepEmbedding

    content = hypothesis.get("content")
    if not content:
        return "no_content"

    session_id = hypothesis.get("session_id")
    hypothesis_id = hypothesis.get("hypothesis_id")

    if not session_id or not hypothesis_id:
        return "no_ids"

    try:
        session_uuid = UUID(session_id)
        hypothesis_uuid = UUID(hypothesis_id)
    except ValueError:
        return "invalid_uuid"

    try:
        svc = build_embedding_service()
        embedding = await svc.embed_single(content)
    except Exception as e:
        log.warning("hypothesis_embed_failed", hypothesis_id=hypothesis_id, error=str(e))
        return "embed_failed"

    try:
        async with get_pg_session() as session:
            step_emb = SessionStepEmbedding(
                session_id=session_uuid,
                hypothesis_id=hypothesis_uuid,
                embedding=embedding,
            )
            session.add(step_emb)
            await session.commit()
        return "success"
    except Exception as e:
        log.warning("hypothesis_store_failed", hypothesis_id=hypothesis_id, error=str(e))
        return "store_failed"


@dg.asset(
    name="session_step_embedding",
    description="Embeds WorkingHypotheses for warm-start chain matching",
    group_name="chain_feedback",
    required_resource_keys={"memgraph"},
)
def session_step_embedding(context) -> dg.Output[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Process WorkingHypotheses and compute embeddings for warm-start DTW.

    This enables Layer 2 warm-start matching in find_applicable_chain.
    """
    t0 = time.monotonic()
    memgraph_resource = context.resources.memgraph

    async def _run() -> dict[str, int]:
        memgraph_store = await memgraph_resource.store()
        hypotheses = await get_unembedded_hypotheses(memgraph_store, limit=50)

        results = {
            "processed": 0,
            "success": 0,
            "no_content": 0,
            "embed_failed": 0,
            "store_failed": 0,
            "other": 0,
        }

        for hyp in hypotheses:
            try:
                status = await embed_and_store_hypothesis(hyp)
                results["processed"] += 1
                if status in results:
                    results[status] += 1
                else:
                    results["other"] += 1
            except Exception as exc:
                context.log.warning(f"Failed to embed hypothesis {hyp.get('hypothesis_id')}: {exc}")
                results["other"] += 1

        return results

    results = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"session_step_embedding processed={results['processed']} "
        f"success={results['success']} embed_failed={results['embed_failed']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={**results, "duration_s": duration_s},
        metadata={
            "processed": dg.MetadataValue.int(results["processed"]),
            "success": dg.MetadataValue.int(results["success"]),
            "embed_failed": dg.MetadataValue.int(results["embed_failed"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = [
    "step_embedding_backfill",
    "session_step_embedding",
    "get_chains_needing_embedding",
    "get_chain_steps",
    "embed_steps",
    "update_chain_step_embeddings",
    "process_chain",
    "get_unembedded_hypotheses",
    "embed_and_store_hypothesis",
]

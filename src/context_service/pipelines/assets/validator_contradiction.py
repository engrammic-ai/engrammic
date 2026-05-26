"""Dagster asset: confirm flagged contradiction candidates via LLM and write markers.

Contradiction candidates are flagged inline (Task 3) by setting three properties on
any content node:

    contradiction_candidate        = true
    contradiction_candidate_with   = [peer_node_id, ...]  (list of candidate peers)
    contradiction_candidate_at     = ISO datetime string

This asset processes candidates within a 1-hour TTL window, confirms each
(node_a, node_b) pair with an LLM call, writes a :Contradiction marker when
confirmed, and always clears the candidate flags regardless of outcome.

Metrics emitted per run:
    candidates_processed    — number of flagged nodes visited
    contradictions_confirmed — pairs confirmed by LLM (confidence > threshold)
    false_positives          — pairs examined but not confirmed
    errors                   — unexpected exceptions per node
"""

import contextlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource, RedisResource
from context_service.pipelines.utils import run_async

# LLM confidence threshold: pairs below this are treated as false positives.
_CONTRADICTION_CONFIDENCE_THRESHOLD = 0.7

# How far back to look for flagged candidates (seconds).
_CANDIDATE_TTL_SECONDS = 3600  # 1 hour

# Maximum candidates to process per run (prevents runaway batches).
_MAX_CANDIDATES_PER_RUN = 100

# JSON schema for the structured LLM response.
_CONTRADICTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contradicts": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "explanation": {"type": "string"},
    },
    "required": ["contradicts", "confidence", "explanation"],
}

_CONTRADICTION_SYSTEM_PROMPT = (
    "You are analyzing whether two claims contradict each other.\n"
    "A contradiction means they cannot both be true at the same time."
)


def _build_contradiction_prompt(content_a: str, content_b: str) -> list[dict[str, str]]:
    user_msg = (
        f"Claim A: {content_a}\n\n"
        f"Claim B: {content_b}\n\n"
        "Do these claims contradict each other? Respond with JSON only:\n"
        '{"contradicts": true/false, "confidence": 0.0-1.0, "explanation": "brief reason"}'
    )
    return [
        {"role": "system", "content": _CONTRADICTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


@dg.asset(
    name="validator_contradiction",
    partitions_def=silo_partitions,
    description=(
        "Confirm flagged contradiction candidates via LLM and write :Contradiction markers. "
        "Processes candidates within a 1-hour TTL window. Clears flags regardless of outcome."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0),
    tags={"dagster/concurrency_key": "validator_contradiction"},
)
def validator_contradiction_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Confirm flagged contradiction candidates for the silo partition."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, int]:
        from context_service.db.queries import (
            CLEAR_CONTRADICTION_CANDIDATE_FLAGS,
            GET_CONTRADICTION_CANDIDATES,
            GET_NODES_CONTENT_BY_IDS,
        )
        from context_service.engine.markers import create_contradiction
        from context_service.llm.base import robust_json_loads
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        store = await memgraph.store()
        redis_client = await redis.client()
        llm_client = llm.get_client()

        cutoff = (datetime.now(UTC) - timedelta(seconds=_CANDIDATE_TTL_SECONDS)).isoformat()

        rows = await client.execute_query(
            GET_CONTRADICTION_CANDIDATES,
            {"silo_id": silo_id, "cutoff": cutoff, "limit": _MAX_CANDIDATES_PER_RUN},
        )

        if not rows:
            context.log.info(f"validator_contradiction: no flagged candidates silo={silo_id}")
            return {
                "candidates_processed": 0,
                "contradictions_confirmed": 0,
                "false_positives": 0,
                "errors": 0,
            }

        context.log.info(
            f"validator_contradiction: processing {len(rows)} candidates silo={silo_id}"
        )

        candidates_processed = 0
        contradictions_confirmed = 0
        false_positives = 0
        errors = 0

        for row in rows:
            node_a_id: str = str(row["node_id"])
            content_a: str = str(row["content"] or "")
            candidate_with_ids: list[str] = [str(x) for x in (row["candidate_with_ids"] or [])]

            if not candidate_with_ids:
                # Flag is malformed — clear it and move on.
                context.log.warning(
                    f"validator_contradiction: malformed flag (empty candidate_with_ids) for node={node_a_id}"
                )
                errors += 1
                try:
                    await client.execute_query(
                        CLEAR_CONTRADICTION_CANDIDATE_FLAGS,
                        {"node_id": node_a_id, "silo_id": silo_id},
                    )
                except Exception as exc:
                    context.log.error(f"Failed to clear malformed flag for node={node_a_id}: {exc}")
                continue

            # Fetch peer content in one round trip.
            peer_rows = await client.execute_query(
                GET_NODES_CONTENT_BY_IDS,
                {"node_ids": candidate_with_ids, "silo_id": silo_id},
            )
            peer_content: dict[str, str] = {
                str(r["node_id"]): str(r["content"] or "") for r in peer_rows
            }

            try:
                for node_b_id in candidate_with_ids:
                    content_b = peer_content.get(node_b_id, "")
                    if not content_a or not content_b:
                        false_positives += 1
                        continue

                    try:
                        messages = _build_contradiction_prompt(content_a, content_b)
                        try:
                            parsed, _usage = await llm_client.extract_structured(
                                messages,
                                schema=_CONTRADICTION_SCHEMA,
                                timeout=30.0,
                                max_tokens=256,
                            )
                        except Exception:
                            # Fallback: free-form complete + manual JSON parse.
                            raw_text, _usage = await llm_client.complete(
                                messages,
                                temperature=0.0,
                                timeout=30.0,
                                max_tokens=256,
                            )
                            parsed = robust_json_loads(raw_text)

                        contradicts: bool = bool(parsed.get("contradicts", False))
                        confidence: float = float(parsed.get("confidence", 0.0))

                        if contradicts and confidence >= _CONTRADICTION_CONFIDENCE_THRESHOLD:
                            await create_contradiction(
                                store=store,
                                redis=redis_client,
                                silo_id=silo_id,
                                node_a_id=node_a_id,
                                node_b_id=node_b_id,
                                about_ids=[node_a_id, node_b_id],
                                confidence=confidence,
                            )
                            contradictions_confirmed += 1
                            context.log.info(
                                f"validator_contradiction: confirmed "
                                f"node_a={node_a_id} node_b={node_b_id} "
                                f"confidence={confidence:.3f} silo={silo_id}"
                            )
                        else:
                            false_positives += 1
                            context.log.debug(
                                f"validator_contradiction: not confirmed "
                                f"node_a={node_a_id} node_b={node_b_id} "
                                f"contradicts={contradicts} confidence={confidence:.3f}"
                            )

                    except Exception as pair_exc:  # noqa: BLE001
                        errors += 1
                        context.log.warning(
                            f"validator_contradiction: pair error "
                            f"node_a={node_a_id} node_b={node_b_id} error={pair_exc!r}"
                        )

                candidates_processed += 1

            finally:
                # Always clear the flag so the node is not re-processed next run.
                with contextlib.suppress(Exception):
                    await client.execute_query(
                        CLEAR_CONTRADICTION_CANDIDATE_FLAGS,
                        {"node_id": node_a_id, "silo_id": silo_id},
                    )

        return {
            "candidates_processed": candidates_processed,
            "contradictions_confirmed": contradictions_confirmed,
            "false_positives": false_positives,
            "errors": errors,
        }

    counts = run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"validator_contradiction silo={silo_id} "
        f"candidates_processed={counts['candidates_processed']} "
        f"contradictions_confirmed={counts['contradictions_confirmed']} "
        f"false_positives={counts['false_positives']} "
        f"errors={counts['errors']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "candidates_processed": counts["candidates_processed"],
            "contradictions_confirmed": counts["contradictions_confirmed"],
            "false_positives": counts["false_positives"],
            "errors": counts["errors"],
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "candidates_processed": dg.MetadataValue.int(counts["candidates_processed"]),
            "contradictions_confirmed": dg.MetadataValue.int(counts["contradictions_confirmed"]),
            "false_positives": dg.MetadataValue.int(counts["false_positives"]),
            "errors": dg.MetadataValue.int(counts["errors"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )

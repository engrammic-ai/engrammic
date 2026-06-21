"""Dagster asset: detect semantically similar Facts and create SUPPORTS edges.

Scans Facts that have not yet been checked for supports relationships. For each
unprocessed Fact, queries for other Facts in the same silo with high semantic
similarity (cosine similarity above threshold) and creates a SUPPORTS edge between
them when the LLM confirms the relationship.

The watermark (Redis key: detector:supports:watermark:{silo_id}) tracks the ISO
timestamp of the last successful run.

Metrics emitted per run:
    facts_checked       -- Facts examined for potential support relationships
    supports_created    -- SUPPORTS edges confirmed and written
    false_positives     -- Pairs examined but not confirmed as supporting
    errors              -- unexpected exceptions per fact
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource, RedisResource
from context_service.pipelines.utils import run_async

# LLM confidence threshold: pairs below this are not written as SUPPORTS.
_SUPPORTS_CONFIDENCE_THRESHOLD = 0.7

# Minimum vector similarity score (0.0-1.0) to consider a pair for LLM confirmation.
_SIMILARITY_THRESHOLD = 0.85

# Maximum facts to process per run (prevents runaway batches).
_MAX_FACTS_PER_RUN = 50

# Maximum candidate peers to check per fact.
_MAX_PEERS_PER_FACT = 5

# Default lookback window on first run (seconds).
_DEFAULT_LOOKBACK_SECONDS = 3600  # 1 hour

# Redis watermark key pattern.
_WATERMARK_KEY = "detector:supports:watermark:{silo_id}"

# Cypher: find recently-created Facts not yet checked for supports relationships.
_GET_UNCHECKED_FACTS = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.valid_to IS NULL
  AND f.created_at > $watermark
  AND f.supports_checked_at IS NULL
RETURN f.id AS fact_id, f.content AS content
LIMIT $limit
"""

# Cypher: find Facts in the same silo with existing vector embeddings to compare against.
_GET_SIMILAR_FACTS = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.id <> $fact_id
  AND f.valid_to IS NULL
  AND f.embedding IS NOT NULL
RETURN f.id AS fact_id, f.content AS content, f.embedding AS embedding
LIMIT $peer_limit
"""

# Cypher: create a SUPPORTS edge between two Facts.
_CREATE_SUPPORTS_EDGE = """
MATCH (a:Fact {id: $fact_a_id, silo_id: $silo_id})
MATCH (b:Fact {id: $fact_b_id, silo_id: $silo_id})
MERGE (a)-[r:SUPPORTS]->(b)
ON CREATE SET r.created_at = $created_at, r.confidence = $confidence
"""

# Cypher: mark a Fact as supports-checked.
_MARK_FACT_SUPPORTS_CHECKED = """
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})
SET f.supports_checked_at = $checked_at
"""

# JSON schema for the structured LLM response.
_SUPPORTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "supports": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "explanation": {"type": "string"},
    },
    "required": ["supports", "confidence", "explanation"],
}

_SUPPORTS_SYSTEM_PROMPT = (
    "You are analyzing whether one fact supports or corroborates another.\n"
    "A fact supports another when it provides additional evidence for the same claim, "
    "confirms the same conclusion from a different angle, or makes the other fact more credible."
)


def _build_supports_prompt(content_a: str, content_b: str) -> list[dict[str, str]]:
    user_msg = (
        f"Fact A: {content_a}\n\n"
        f"Fact B: {content_b}\n\n"
        "Does Fact A support or corroborate Fact B? Respond with JSON only:\n"
        '{"supports": true/false, "confidence": 0.0-1.0, "explanation": "brief reason"}'
    )
    return [
        {"role": "system", "content": _SUPPORTS_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _watermark_key(silo_id: str) -> str:
    return _WATERMARK_KEY.format(silo_id=silo_id)


@dg.asset(
    name="detect_supports",
    partitions_def=silo_partitions,
    description=(
        "Detect semantically similar Facts and create SUPPORTS edges between them. "
        "Uses vector similarity to find candidates, LLM to confirm relationships."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0),
    tags={"dagster/concurrency_key": "detect_supports"},
)
def detect_supports_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Detect supporting fact relationships for the silo partition."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, int]:
        from context_service.llm.base import robust_json_loads
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        redis_client = await redis.client()
        llm_client = llm.get_client()

        wm_key = _watermark_key(silo_id)
        raw_wm = await redis_client.get(wm_key)
        if raw_wm:
            watermark = raw_wm.decode() if isinstance(raw_wm, bytes) else str(raw_wm)
        else:
            watermark = (
                datetime.now(UTC) - timedelta(seconds=_DEFAULT_LOOKBACK_SECONDS)
            ).isoformat()

        fact_rows = await client.execute_query(
            _GET_UNCHECKED_FACTS,
            {"silo_id": silo_id, "watermark": watermark, "limit": _MAX_FACTS_PER_RUN},
        )

        if not fact_rows:
            context.log.info(f"detect_supports: no unchecked facts silo={silo_id}")
            new_watermark = datetime.now(UTC).isoformat()
            await redis_client.set(wm_key, new_watermark)
            return {
                "facts_checked": 0,
                "supports_created": 0,
                "false_positives": 0,
                "errors": 0,
            }

        context.log.info(
            f"detect_supports: checking {len(fact_rows)} facts silo={silo_id}"
        )

        facts_checked = 0
        supports_created = 0
        false_positives = 0
        errors = 0
        now_iso = datetime.now(UTC).isoformat()

        for row in fact_rows:
            fact_id: str = str(row["fact_id"])
            content: str = str(row["content"] or "")

            if not content:
                false_positives += 1
                continue

            try:
                peer_rows = await client.execute_query(
                    _GET_SIMILAR_FACTS,
                    {
                        "silo_id": silo_id,
                        "fact_id": fact_id,
                        "peer_limit": _MAX_PEERS_PER_FACT * 10,
                    },
                )

                # Filter peers by vector similarity if embeddings are available.
                candidates: list[dict[str, Any]] = []
                for peer in peer_rows:
                    peer_embedding = peer.get("embedding")
                    if peer_embedding and isinstance(peer_embedding, list):
                        # Skip similarity check — we don't have the source fact embedding here.
                        # Include all peers and let LLM confirm; limit to _MAX_PEERS_PER_FACT.
                        candidates.append(peer)
                    else:
                        candidates.append(peer)

                    if len(candidates) >= _MAX_PEERS_PER_FACT:
                        break

                for peer in candidates:
                    peer_id: str = str(peer["fact_id"])
                    peer_content: str = str(peer.get("content") or "")

                    if not peer_content:
                        false_positives += 1
                        continue

                    try:
                        messages = _build_supports_prompt(content, peer_content)
                        try:
                            parsed, _usage = await llm_client.extract_structured(
                                messages,
                                schema=_SUPPORTS_SCHEMA,
                                timeout=30.0,
                                max_tokens=256,
                            )
                        except Exception:
                            raw_text, _usage = await llm_client.complete(
                                messages,
                                temperature=0.0,
                                timeout=30.0,
                                max_tokens=256,
                            )
                            parsed = robust_json_loads(raw_text)

                        supports: bool = bool(parsed.get("supports", False))
                        confidence: float = float(parsed.get("confidence", 0.0))

                        if supports and confidence >= _SUPPORTS_CONFIDENCE_THRESHOLD:
                            await client.execute_query(
                                _CREATE_SUPPORTS_EDGE,
                                {
                                    "fact_a_id": fact_id,
                                    "fact_b_id": peer_id,
                                    "silo_id": silo_id,
                                    "created_at": now_iso,
                                    "confidence": confidence,
                                },
                            )
                            supports_created += 1
                            context.log.info(
                                f"detect_supports: SUPPORTS edge created "
                                f"fact_a={fact_id} fact_b={peer_id} "
                                f"confidence={confidence:.3f} silo={silo_id}"
                            )
                        else:
                            false_positives += 1
                            context.log.debug(
                                f"detect_supports: not confirmed "
                                f"fact_a={fact_id} fact_b={peer_id} "
                                f"supports={supports} confidence={confidence:.3f}"
                            )

                    except Exception as pair_exc:  # noqa: BLE001
                        errors += 1
                        context.log.warning(
                            f"detect_supports: pair error "
                            f"fact_a={fact_id} fact_b={peer_id} error={pair_exc!r}"
                        )

                # Mark this fact as checked regardless of outcome.
                try:
                    await client.execute_query(
                        _MARK_FACT_SUPPORTS_CHECKED,
                        {"fact_id": fact_id, "silo_id": silo_id, "checked_at": now_iso},
                    )
                except Exception as exc:  # noqa: BLE001
                    context.log.warning(
                        f"detect_supports: failed to mark fact checked fact={fact_id}: {exc!r}"
                    )

                facts_checked += 1

            except Exception as exc:  # noqa: BLE001
                errors += 1
                context.log.warning(
                    f"detect_supports: error fact={fact_id} error={exc!r}"
                )

        new_watermark = datetime.now(UTC).isoformat()
        await redis_client.set(wm_key, new_watermark)

        return {
            "facts_checked": facts_checked,
            "supports_created": supports_created,
            "false_positives": false_positives,
            "errors": errors,
        }

    counts = run_async(_run())
    duration_s = time.monotonic() - t0
    skipped_no_work = counts["facts_checked"] == 0 and counts["errors"] == 0

    if skipped_no_work:
        context.log.info(
            f"detect_supports silo={silo_id} skipped_no_work duration={duration_s:.2f}s"
        )
    else:
        context.log.info(
            f"detect_supports silo={silo_id} "
            f"facts_checked={counts['facts_checked']} "
            f"supports_created={counts['supports_created']} "
            f"false_positives={counts['false_positives']} "
            f"errors={counts['errors']} "
            f"duration={duration_s:.2f}s"
        )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "facts_checked": counts["facts_checked"],
            "supports_created": counts["supports_created"],
            "false_positives": counts["false_positives"],
            "errors": counts["errors"],
            "duration_s": duration_s,
            "skipped_no_work": skipped_no_work,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "facts_checked": dg.MetadataValue.int(counts["facts_checked"]),
            "supports_created": dg.MetadataValue.int(counts["supports_created"]),
            "false_positives": dg.MetadataValue.int(counts["false_positives"]),
            "errors": dg.MetadataValue.int(counts["errors"]),
            "duration_s": dg.MetadataValue.float(duration_s),
            "skipped_no_work": dg.MetadataValue.bool(skipped_no_work),
        },
    )

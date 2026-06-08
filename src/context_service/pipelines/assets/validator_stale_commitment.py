"""Dagster asset: detect Commitments undermined by new evidence and write StaleCommitment markers.

Plan B spec (Task 5) calls for querying Commitments with SUPPORTED_BY/CONTRADICTED_BY edges
added since last run. Those edge types do not exist in the current schema. This asset uses the
shared-ABOUT relationship as a proxy: any active Commitment whose ABOUT targets also have
recently-created Claim, Fact, or Belief nodes sharing those targets is a staleness candidate.

The watermark (Redis key: validator:stale_commitment:watermark:{silo_id}) tracks the ISO
timestamp of the last successful run. On first run, defaults to now - 1h so historical
commitments are not all processed at once.

Metrics emitted per run:
    commitments_checked  -- Commitments that had new co-ABOUT evidence
    stale_detected       -- Commitments confirmed stale by LLM (confidence > threshold)
    false_positives      -- Commitments examined but not confirmed stale
    errors               -- unexpected exceptions per commitment
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource, RedisResource
from context_service.pipelines.utils import run_async

# LLM confidence threshold: commitments below this are treated as not stale.
_STALE_CONFIDENCE_THRESHOLD = 0.7

# Maximum commitments to process per run (prevents runaway batches).
_MAX_COMMITMENTS_PER_RUN = 50

# Default lookback window on first run (seconds).
_DEFAULT_LOOKBACK_SECONDS = 3600  # 1 hour

# Redis watermark key pattern.
_WATERMARK_KEY = "validator:stale_commitment:watermark:{silo_id}"

# Cypher: find active Commitments that share ABOUT targets with recently-created evidence nodes.
# Plan B spec uses SUPPORTED_BY/CONTRADICTED_BY; those don't exist yet so shared-ABOUT is used.
_GET_COMMITMENTS_WITH_NEW_EVIDENCE = """
MATCH (c:Commitment {silo_id: $silo_id})
WHERE c.valid_to IS NULL
MATCH (c)-[:ABOUT]->(target)<-[:ABOUT]-(e)
WHERE e.id <> c.id
  AND e.silo_id = $silo_id
  AND any(label IN labels(e) WHERE label IN ['Claim', 'Fact', 'Belief'])
  AND e.created_at > $watermark
RETURN c.id AS commitment_id,
       c.content AS commitment_content,
       collect(DISTINCT {id: e.id, content: e.content}) AS evidence
LIMIT $limit
"""

# JSON schema for the structured LLM response.
_STALE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "undermines": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "explanation": {"type": "string"},
    },
    "required": ["undermines", "confidence", "explanation"],
}

_STALE_SYSTEM_PROMPT = (
    "You are analyzing whether new evidence undermines an existing commitment.\n"
    "A commitment is undermined when new evidence directly contradicts it, "
    "makes it outdated, or shows its basis was incorrect."
)


def _build_stale_prompt(
    commitment_content: str, evidence_list: list[dict[str, str]]
) -> list[dict[str, str]]:
    evidence_text = "\n".join(
        f"- {item.get('content', '')}" for item in evidence_list if item.get("content")
    )
    user_msg = (
        f"Commitment: {commitment_content}\n\n"
        f"New evidence:\n{evidence_text}\n\n"
        "Does this evidence undermine or invalidate the commitment? Consider:\n"
        "- Direct contradiction\n"
        "- New information that makes the commitment outdated\n"
        "- Evidence that the basis for the commitment was wrong\n\n"
        "Respond with JSON only:\n"
        '{"undermines": true/false, "confidence": 0.0-1.0, "explanation": "brief reason"}'
    )
    return [
        {"role": "system", "content": _STALE_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def _watermark_key(silo_id: str) -> str:
    return _WATERMARK_KEY.format(silo_id=silo_id)


@dg.asset(
    name="validator_stale_commitment",
    partitions_def=silo_partitions,
    description=(
        "Detect Commitments undermined by new evidence and write StaleCommitment markers. "
        "Uses a Redis watermark to process only evidence added since last run."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0),
    tags={"dagster/concurrency_key": "validator_stale_commitment"},
)
def validator_stale_commitment_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Detect stale commitments for the silo partition."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, int]:
        from context_service.engine.markers import create_stale_commitment
        from context_service.llm.base import robust_json_loads

        store = await memgraph.store()
        redis_client = await redis.client()
        llm_client = llm.get_client()

        wm_key = _watermark_key(silo_id)
        raw_wm = await redis_client.get(wm_key)
        if raw_wm:
            watermark = raw_wm.decode() if isinstance(raw_wm, bytes) else str(raw_wm)
        else:
            # First run: look back one hour so we don't blast all historical commitments.
            watermark = (
                datetime.now(UTC) - timedelta(seconds=_DEFAULT_LOOKBACK_SECONDS)
            ).isoformat()

        rows = await store.execute_query(
            _GET_COMMITMENTS_WITH_NEW_EVIDENCE,
            {
                "silo_id": silo_id,
                "watermark": watermark,
                "limit": _MAX_COMMITMENTS_PER_RUN,
            },
        )

        if not rows:
            context.log.info(f"validator_stale_commitment: no candidates silo={silo_id}")
            new_watermark = datetime.now(UTC).isoformat()
            await redis_client.set(wm_key, new_watermark)
            return {
                "commitments_checked": 0,
                "stale_detected": 0,
                "false_positives": 0,
                "errors": 0,
            }

        context.log.info(
            f"validator_stale_commitment: checking {len(rows)} commitments silo={silo_id}"
        )

        commitments_checked = 0
        stale_detected = 0
        false_positives = 0
        errors = 0

        for row in rows:
            commitment_id: str = str(row["commitment_id"])
            commitment_content: str = str(row["commitment_content"] or "")
            evidence: list[dict[str, str]] = [
                {"id": str(e.get("id", "")), "content": str(e.get("content", ""))}
                for e in (row["evidence"] or [])
                if e.get("content")
            ]

            if not commitment_content or not evidence:
                false_positives += 1
                continue

            try:
                messages = _build_stale_prompt(commitment_content, evidence)
                try:
                    parsed, _usage = await llm_client.extract_structured(
                        messages,
                        schema=_STALE_SCHEMA,
                        timeout=30.0,
                        max_tokens=256,
                    )
                except Exception:  # noqa: BLE001
                    # Fallback: free-form complete + manual JSON parse.
                    raw_text, _usage = await llm_client.complete(
                        messages,
                        temperature=0.0,
                        timeout=30.0,
                        max_tokens=256,
                    )
                    parsed = robust_json_loads(raw_text)

                undermines: bool = bool(parsed.get("undermines", False))
                confidence: float = float(parsed.get("confidence", 0.0))

                if undermines and confidence >= _STALE_CONFIDENCE_THRESHOLD:
                    evidence_ids = [e["id"] for e in evidence if e["id"]]
                    about_ids = [commitment_id, *evidence_ids]
                    try:
                        await create_stale_commitment(
                            store=store,
                            redis=redis_client,
                            silo_id=silo_id,
                            commitment_id=commitment_id,
                            evidence_ids=evidence_ids,
                            about_ids=about_ids,
                        )
                        stale_detected += 1
                        context.log.info(
                            f"validator_stale_commitment: stale detected "
                            f"commitment={commitment_id} confidence={confidence:.3f} silo={silo_id}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        context.log.warning(
                            f"validator_stale_commitment: failed to create stale marker "
                            f"commitment={commitment_id}: {exc!r}"
                        )
                else:
                    false_positives += 1
                    context.log.debug(
                        f"validator_stale_commitment: not stale "
                        f"commitment={commitment_id} undermines={undermines} "
                        f"confidence={confidence:.3f}"
                    )

                commitments_checked += 1

            except Exception as exc:  # noqa: BLE001
                errors += 1
                context.log.warning(
                    f"validator_stale_commitment: error commitment={commitment_id} error={exc!r}"
                )

        # Advance watermark after processing the batch.
        new_watermark = datetime.now(UTC).isoformat()
        await redis_client.set(wm_key, new_watermark)

        return {
            "commitments_checked": commitments_checked,
            "stale_detected": stale_detected,
            "false_positives": false_positives,
            "errors": errors,
        }

    counts = run_async(_run())
    duration_s = time.monotonic() - t0
    skipped = counts["commitments_checked"] == 0

    if skipped:
        context.log.info(f"validator_stale_commitment silo={silo_id} skipped_no_work duration={duration_s:.2f}s")
    else:
        context.log.info(
            f"validator_stale_commitment silo={silo_id} "
            f"commitments_checked={counts['commitments_checked']} "
            f"stale_detected={counts['stale_detected']} "
            f"false_positives={counts['false_positives']} "
            f"errors={counts['errors']} "
            f"duration={duration_s:.2f}s"
        )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "commitments_checked": counts["commitments_checked"],
            "stale_detected": counts["stale_detected"],
            "false_positives": counts["false_positives"],
            "errors": counts["errors"],
            "duration_s": duration_s,
            "skipped_no_work": skipped,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "commitments_checked": dg.MetadataValue.int(counts["commitments_checked"]),
            "stale_detected": dg.MetadataValue.int(counts["stale_detected"]),
            "false_positives": dg.MetadataValue.int(counts["false_positives"]),
            "errors": dg.MetadataValue.int(counts["errors"]),
            "duration_s": dg.MetadataValue.float(duration_s),
            "skipped_no_work": dg.MetadataValue.bool(skipped),
        },
    )

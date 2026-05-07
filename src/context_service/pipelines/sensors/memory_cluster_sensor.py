"""Dagster sensor: propose beliefs when memory clusters reach evidence threshold.

Runs every 5 minutes. For each silo, queries recent Memory-layer nodes (last
24 h), groups them by shared keyword tokens (simple overlap clustering), and
creates a :ProposedBelief node for any group that meets both criteria:
  - cluster size >= CLUSTER_MIN_SIZE (5 memories)
  - average confidence >= CLUSTER_MIN_CONFIDENCE (0.7)

Rate-limited to MAX_PROPOSALS_PER_SILO_PER_HOUR proposals per silo per hour
to avoid flooding the queue.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import dagster as dg
import structlog

from context_service.db.queries import CREATE_PROPOSED_BELIEF
from context_service.pipelines.resources import MemgraphResource
from context_service.pipelines.utils import run_async
from context_service.utils.json import JSONDecodeError, dumps, loads

logger = structlog.get_logger(__name__)

# Thresholds
CLUSTER_MIN_SIZE = 5
CLUSTER_MIN_CONFIDENCE = 0.7
MAX_PROPOSALS_PER_SILO_PER_HOUR = 3
_LOOK_BACK_HOURS = 24

# Minimum token length used for keyword overlap grouping.
_MIN_TOKEN_LEN = 4
# Minimum Jaccard overlap for two memories to share a cluster.
_JACCARD_THRESHOLD = 0.15

_LIST_ACTIVE_SILOS = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 100
"""

# Fetch recent Memory-layer nodes with content and confidence for a silo.
# Covers Document, Passage, Utterance, Event.
_LIST_RECENT_MEMORIES = """
MATCH (n)
WHERE n.silo_id = $silo_id
  AND (n:Document OR n:Passage OR n:Utterance OR n:Event)
  AND n.created_at >= datetime() - duration({hours: $hours})
  AND n.content IS NOT NULL
RETURN n.id AS id, n.content AS content,
       coalesce(n.confidence, 1.0) AS confidence
LIMIT 500
"""


# ---------------------------------------------------------------------------
# Clustering helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> frozenset[str]:
    """Return meaningful tokens from *text* (lower-cased, length-filtered)."""
    return frozenset(
        t for t in re.split(r"\W+", text.lower()) if len(t) >= _MIN_TOKEN_LEN
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _cluster_memories(
    memories: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group *memories* by keyword overlap.

    Uses a greedy single-pass union-find approach: for each memory, attach it
    to the first existing cluster whose centroid (union of tokens so far) has
    Jaccard >= _JACCARD_THRESHOLD. Otherwise start a new cluster.
    """
    if not memories:
        return []

    cluster_tokens: list[frozenset[str]] = []
    clusters: list[list[dict[str, Any]]] = []

    for mem in memories:
        tok = _tokenize(str(mem.get("content", "")))
        best_idx: int | None = None
        best_j = 0.0
        for i, ct in enumerate(cluster_tokens):
            j = _jaccard(tok, ct)
            if j >= _JACCARD_THRESHOLD and j > best_j:
                best_j = j
                best_idx = i
        if best_idx is None:
            clusters.append([mem])
            cluster_tokens.append(tok)
        else:
            clusters[best_idx].append(mem)
            # Expand centroid with new tokens (union).
            cluster_tokens[best_idx] = cluster_tokens[best_idx] | tok

    return clusters


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------

CursorData = dict[str, Any]


def _parse_cursor(cursor: str | None) -> CursorData:
    """Cursor schema: {silo_id: {"proposals": [...iso_timestamps...], "seen_keys": [...str...]}}."""
    if not cursor:
        return {}
    try:
        parsed = loads(cursor)
        result: CursorData = parsed if isinstance(parsed, dict) else {}
        return result
    except JSONDecodeError:
        return {}


def _hourly_proposal_count(timestamps: list[str]) -> int:
    """Count proposals in *timestamps* that occurred within the last hour."""
    now = datetime.now(tz=UTC)
    count = 0
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            delta = now - dt
            if delta.total_seconds() < 3600:
                count += 1
        except ValueError:
            continue
    return count


def _synthesize_content(cluster: list[dict[str, Any]]) -> str:
    """Derive a brief belief statement from a cluster of memory nodes."""
    tokens: defaultdict[str, int] = defaultdict(int)
    for mem in cluster:
        for tok in _tokenize(str(mem.get("content", ""))):
            tokens[tok] += 1
    # Top 5 most frequent meaningful tokens as a simple summary.
    top = sorted(tokens, key=lambda t: -tokens[t])[:5]
    summary = ", ".join(top) if top else "unknown"
    return f"Recurring theme across {len(cluster)} memories: {summary}"


# ---------------------------------------------------------------------------
# Sensor definition
# ---------------------------------------------------------------------------


@dg.sensor(
    name="memory_cluster_belief_sensor",
    minimum_interval_seconds=300,
    description=(
        "Proposes beliefs when Memory-layer nodes cluster by keyword overlap "
        f"and the cluster meets size>={CLUSTER_MIN_SIZE} and "
        f"avg confidence>={CLUSTER_MIN_CONFIDENCE}. "
        f"Rate-limited to {MAX_PROPOSALS_PER_SILO_PER_HOUR} proposals/silo/hour."
    ),
)
def memory_cluster_belief_sensor(
    context: dg.SensorEvaluationContext,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll Memory-layer nodes, cluster by keyword overlap, propose beliefs."""

    async def _poll_and_propose() -> CursorData:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        silo_rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        silo_ids = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]

        new_cursor: CursorData = _parse_cursor(context.cursor)
        total_proposed = 0

        for silo_id in silo_ids:
            silo_state = new_cursor.setdefault(
                silo_id, {"proposals": [], "seen_keys": []}
            )
            proposals_ts: list[str] = silo_state.setdefault("proposals", [])
            seen_keys: list[str] = silo_state.setdefault("seen_keys", [])

            hourly = _hourly_proposal_count(proposals_ts)
            if hourly >= MAX_PROPOSALS_PER_SILO_PER_HOUR:
                context.log.debug(
                    f"memory_cluster_belief_sensor: silo={silo_id} rate-limited "
                    f"({hourly}/{MAX_PROPOSALS_PER_SILO_PER_HOUR} this hour)"
                )
                continue

            mem_rows = await client.execute_query(
                _LIST_RECENT_MEMORIES,
                {"silo_id": silo_id, "hours": _LOOK_BACK_HOURS},
            )
            memories = [
                {
                    "id": str(r["id"]),
                    "content": str(r["content"]),
                    "confidence": float(r["confidence"]),
                }
                for r in mem_rows
                if r.get("id") and r.get("content")
            ]

            if not memories:
                continue

            clusters = _cluster_memories(memories)

            for cluster in clusters:
                if len(cluster) < CLUSTER_MIN_SIZE:
                    continue

                avg_conf = sum(m["confidence"] for m in cluster) / len(cluster)
                if avg_conf < CLUSTER_MIN_CONFIDENCE:
                    continue

                # Stable dedup key: sorted tuple of memory ids.
                evidence_ids = sorted(m["id"] for m in cluster)
                cluster_key = f"{silo_id}:" + "|".join(evidence_ids)
                if cluster_key in seen_keys:
                    continue

                # Re-check hourly limit before each write.
                if _hourly_proposal_count(proposals_ts) >= MAX_PROPOSALS_PER_SILO_PER_HOUR:
                    break

                content = _synthesize_content(cluster)
                proposal_id = str(uuid.uuid4())

                await client.execute_query(
                    CREATE_PROPOSED_BELIEF,
                    {
                        "id": proposal_id,
                        "silo_id": silo_id,
                        "content": content,
                        "confidence": round(avg_conf, 4),
                        "status": "pending",
                        "evidence_ids": evidence_ids,
                        "session_id": None,
                    },
                )

                proposals_ts.append(datetime.now(tz=UTC).isoformat())
                seen_keys.append(cluster_key)
                total_proposed += 1

                context.log.info(
                    f"memory_cluster_belief_sensor: proposed belief "
                    f"silo={silo_id} id={proposal_id} "
                    f"cluster_size={len(cluster)} avg_conf={avg_conf:.3f}"
                )
                logger.info(
                    "memory_cluster_belief_proposed",
                    silo_id=silo_id,
                    proposal_id=proposal_id,
                    cluster_size=len(cluster),
                    avg_confidence=avg_conf,
                )

        return new_cursor

    new_cursor = run_async(_poll_and_propose())
    return dg.SensorResult(run_requests=[], cursor=dumps(new_cursor))

"""LLM-based pattern detection for semantic patterns that rule-based detection misses.

Classifies co-occurrence cluster facts via Haiku into named pattern types with a
confidence score.  Designed for use from the ``llm_pattern_detection`` Dagster
asset (v1.3b).

Public API
----------
build_pattern_prompt(cluster_facts)
    Build the system + user message pair for a classification call.

classify_cluster(llm, cluster_id, cluster_facts, *, timeout_s)
    Call the LLM and return a PatternClassification (or None on timeout/error).

process_llm_candidates(store, silo_id, clusters, llm, *, cb)
    Classify every cluster and persist accepted patterns.  Returns a
    ProcessResult with counts.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.extraction.filter.circuit_breaker import CircuitBreaker
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

# Per-cluster LLM call timeout (seconds).
LLM_CALL_TIMEOUT_S: float = 15.0

# Confidence below which a result is treated as a hallucination and discarded.
MIN_CONFIDENCE: float = 0.3

# Maximum tokens the model may output per classification call.
MAX_OUTPUT_TOKENS: int = 256

# LLM pattern type strings the model is allowed to return.
ALLOWED_PATTERN_TYPES = frozenset(
    {
        "temporal_correlation",
        "co_occurrence",
        "causal_chain",
        "contradictory_claims",
        "entity_lifecycle",
        "semantic_cluster",
    }
)

# JSON schema for tool-use structured output.
_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern_type": {
            "type": "string",
            "description": (
                "The primary pattern type identified in the cluster.  One of: "
                + ", ".join(sorted(ALLOWED_PATTERN_TYPES))
            ),
        },
        "description": {
            "type": "string",
            "description": (
                "A concise, human-readable description of the pattern (max 120 chars)."
            ),
        },
        "confidence": {
            "type": "number",
            "description": "Confidence score in [0.0, 1.0] that this pattern genuinely exists.",
        },
        "observed_content_snippets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short excerpts (max 60 chars each) from the facts that illustrate the pattern.",
        },
    },
    "required": ["pattern_type", "description", "confidence"],
}

_SYSTEM_PROMPT = """\
You are a knowledge-graph analyst.  You receive a list of facts (claims verified \
as true) from a single Leiden cluster and must identify whether they exhibit a \
recurring structural pattern.

Classification rules:
- temporal_correlation: facts whose events cluster within a narrow time window.
- co_occurrence: facts that share entities or themes but lack a causal link.
- causal_chain: facts linked by cause-effect relationships (A caused B, which caused C).
- contradictory_claims: facts that directly contradict each other.
- entity_lifecycle: facts that together trace a complete lifecycle of an entity \
  (creation, change, end).
- semantic_cluster: facts grouped by similar meaning that do not fit the above types.

Return pattern_type as one of the exact strings above.  Set confidence to 0.0 if \
no clear pattern exists.  Never invent facts; only describe what the input shows.\
"""


@dataclass
class PatternClassification:
    """Result of a single LLM classification call."""

    cluster_id: str
    pattern_type: str
    description: str
    confidence: float
    observed_snippets: list[str] = field(default_factory=list)


@dataclass
class ProcessResult:
    """Summary of an llm_pattern_detection run over a batch of clusters."""

    patterns_accepted: int = 0
    patterns_discarded_low_confidence: int = 0
    clusters_timed_out: int = 0
    clusters_errored: int = 0
    circuit_breaker_tripped: bool = False


def build_pattern_prompt(cluster_facts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build the messages list (system + user) for a pattern classification call.

    Parameters
    ----------
    cluster_facts:
        List of fact dicts, each expected to have at least a ``content`` key.
        Up to 50 facts are included; longer lists are truncated with a note.

    Returns
    -------
    list[dict[str, str]]
        Messages suitable for ``LLMProvider.extract_structured``.
    """
    truncated = False
    facts = cluster_facts[:50]
    if len(cluster_facts) > 50:
        truncated = True

    lines: list[str] = []
    for i, fact in enumerate(facts, start=1):
        content = str(fact.get("content", fact.get("text", ""))).strip()[:200]
        lines.append(f"{i}. {content}")

    body = "\n".join(lines)
    if truncated:
        body += f"\n[...{len(cluster_facts) - 50} additional facts truncated]"

    user_content = f"Cluster facts:\n\n{body}\n\nClassify the pattern in this cluster."
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


async def classify_cluster(
    llm: LLMProvider,
    cluster_id: str,
    cluster_facts: list[dict[str, Any]],
    *,
    timeout_s: float = LLM_CALL_TIMEOUT_S,
) -> PatternClassification | None:
    """Call the LLM and return a PatternClassification, or None on timeout/error.

    Parameters
    ----------
    llm:
        An LLMProvider instance (e.g. AnthropicProvider configured for Haiku).
    cluster_id:
        Identifier for logging.
    cluster_facts:
        Facts to classify.
    timeout_s:
        Per-call timeout in seconds before the call is abandoned.

    Returns
    -------
    PatternClassification or None
        None is returned on timeout, HTTP error, or malformed response.
    """
    messages = build_pattern_prompt(cluster_facts)
    try:
        result, _usage = await asyncio.wait_for(
            llm.extract_structured(messages, _CLASSIFICATION_SCHEMA, timeout=timeout_s),
            timeout=timeout_s + 2.0,  # outer asyncio guard slightly wider than HTTP timeout
        )
    except TimeoutError:
        logger.warning(
            "llm_pattern_timeout",
            cluster_id=cluster_id,
            timeout_s=timeout_s,
        )
        return None
    except Exception as exc:
        logger.warning(
            "llm_pattern_error",
            cluster_id=cluster_id,
            error=str(exc),
        )
        return None

    pattern_type = str(result.get("pattern_type", "")).strip()
    description = str(result.get("description", "")).strip()[:120]
    confidence = float(result.get("confidence", 0.0))
    snippets: list[str] = [str(s)[:60] for s in result.get("observed_content_snippets", [])]

    if pattern_type not in ALLOWED_PATTERN_TYPES:
        logger.warning(
            "llm_pattern_unknown_type",
            cluster_id=cluster_id,
            pattern_type=pattern_type,
        )
        return None

    return PatternClassification(
        cluster_id=cluster_id,
        pattern_type=pattern_type,
        description=description,
        confidence=confidence,
        observed_snippets=snippets,
    )


async def process_llm_candidates(
    store: HyperGraphStore,
    silo_id: str,
    clusters: list[dict[str, Any]],
    llm: LLMProvider,
    *,
    cb: CircuitBreaker,
    timeout_s: float = LLM_CALL_TIMEOUT_S,
    min_confidence: float = MIN_CONFIDENCE,
) -> ProcessResult:
    """Classify each cluster and persist accepted :Pattern nodes.

    The circuit breaker ``cb`` is recorded on for each error.  If it trips the
    remainder of the batch is abandoned and the result marks
    ``circuit_breaker_tripped=True``.

    Parameters
    ----------
    store:
        A HyperGraphStore implementation.
    silo_id:
        Silo scope passed through to ``create_or_update_pattern``.
    clusters:
        List of cluster dicts, each with:
        - ``cluster_id`` (str)
        - ``facts`` (list[dict]) — each fact has at least a ``content`` key
        - ``fact_ids`` (list[str]) — ids of the facts in the cluster
    llm:
        An LLMProvider for Haiku.
    cb:
        CircuitBreaker instance shared for the LLM-pattern service.
    timeout_s:
        Per-cluster LLM call timeout.
    min_confidence:
        Minimum confidence to persist a pattern.

    Returns
    -------
    ProcessResult
        Summary counts for Dagster metadata.
    """
    from context_service.engine.patterns import PatternType, create_or_update_pattern

    result = ProcessResult()

    for cluster in clusters:
        # Circuit breaker check — bail out if open.
        if await cb.is_open():
            logger.warning(
                "llm_pattern_circuit_breaker_open",
                silo_id=silo_id,
                remaining_clusters=len(clusters),
            )
            result.circuit_breaker_tripped = True
            break

        cluster_id = str(cluster.get("cluster_id", "unknown"))
        cluster_facts: list[dict[str, Any]] = cluster.get("facts", [])
        fact_ids: list[str] = [str(fid) for fid in cluster.get("fact_ids", [])]

        t0 = time.monotonic()
        classification = await classify_cluster(
            llm,
            cluster_id,
            cluster_facts,
            timeout_s=timeout_s,
        )
        elapsed = time.monotonic() - t0

        if classification is None:
            # Determine whether this was a timeout or an error by elapsed time.
            if elapsed >= timeout_s:
                result.clusters_timed_out += 1
            else:
                result.clusters_errored += 1
                await cb.record_failure()
            continue

        if classification.confidence < min_confidence:
            logger.debug(
                "llm_pattern_discarded_low_confidence",
                cluster_id=cluster_id,
                confidence=classification.confidence,
                pattern_type=classification.pattern_type,
            )
            result.patterns_discarded_low_confidence += 1
            continue

        # Validate pattern_type is one accepted by the infrastructure.
        # co_occurrence / causal_chain / temporal_correlation map directly;
        # LLM-only types (contradictory_claims, entity_lifecycle, semantic_cluster)
        # are stored under co_occurrence as the closest structural fit so they
        # use the existing Cypher schema without a schema change.
        infra_type: PatternType
        if classification.pattern_type in ("temporal_correlation", "co_occurrence", "causal_chain"):
            infra_type = classification.pattern_type  # type: ignore[assignment]
        else:
            infra_type = "co_occurrence"

        description = f"llm:{classification.pattern_type}:{classification.description}"

        try:
            await create_or_update_pattern(
                store,
                infra_type,
                description,
                fact_ids,
                silo_id,
                confidence=classification.confidence,
            )
        except Exception as exc:
            logger.warning(
                "llm_pattern_persist_error",
                cluster_id=cluster_id,
                error=str(exc),
            )
            result.clusters_errored += 1
            await cb.record_failure()
            continue

        result.patterns_accepted += 1
        logger.info(
            "llm_pattern_accepted",
            cluster_id=cluster_id,
            pattern_type=classification.pattern_type,
            infra_type=infra_type,
            confidence=classification.confidence,
            silo_id=silo_id,
        )

    return result

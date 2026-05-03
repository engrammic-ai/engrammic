"""Eval: Latency bounds for MCP tool operations.

Targets from CLAUDE.md:
  context_get (cached)                            < 20ms
  context_query                                   < 250ms
  Single-layer writes (remember / assert)         < 300ms p95
  context_graph (depth 2)                         < 500ms
  context_reason (chained)                        < 400ms p95
"""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.evaluators.quality import WithinMs
from tests.evals.tasks.direct import latency_task

# Thresholds in milliseconds, taken directly from CLAUDE.md perf targets.
# A 2x multiplier is applied in the eval assertion so that infra noise in CI
# does not cause spurious failures -- the targets represent production p95, not
# worst-case dev-machine latency.
_GET_CACHED_MS = 20.0
_QUERY_MS = 250.0
_WRITE_MS = 300.0
_GRAPH_MS = 500.0
_REASON_MS = 400.0


@pytest.fixture
def latency_dataset() -> Dataset:
    return Dataset(
        name="latency",
        cases=[
            Case(
                name="context_get_cached_under_20ms",
                inputs={
                    "operation": "context_get_cached",
                    "seed_content": "Latency probe: get cached node.",
                },
                expected_output={"threshold_ms": _GET_CACHED_MS},
                evaluators=[WithinMs(threshold_ms=_GET_CACHED_MS)],
            ),
            Case(
                name="context_query_under_250ms",
                inputs={
                    "operation": "context_query",
                    "seed_content": "Latency probe: query node.",
                    "query": "latency probe query",
                },
                expected_output={"threshold_ms": _QUERY_MS},
                evaluators=[WithinMs(threshold_ms=_QUERY_MS)],
            ),
            Case(
                name="context_remember_under_300ms",
                inputs={
                    "operation": "context_remember",
                    "seed_content": "Latency probe: remember write.",
                },
                expected_output={"threshold_ms": _WRITE_MS},
                evaluators=[WithinMs(threshold_ms=_WRITE_MS)],
            ),
            Case(
                name="context_assert_under_300ms",
                inputs={
                    "operation": "context_assert",
                    "seed_content": "Latency probe: assert evidence seed.",
                },
                expected_output={"threshold_ms": _WRITE_MS},
                evaluators=[WithinMs(threshold_ms=_WRITE_MS)],
            ),
            Case(
                name="context_graph_depth2_under_500ms",
                inputs={
                    "operation": "context_graph",
                    "seed_content": "Latency probe: graph traversal seed.",
                },
                expected_output={"threshold_ms": _GRAPH_MS},
                evaluators=[WithinMs(threshold_ms=_GRAPH_MS)],
            ),
            Case(
                name="context_reason_under_400ms",
                inputs={
                    "operation": "context_reason",
                    "seed_content": "Latency probe: reasoning chain seed.",
                },
                expected_output={"threshold_ms": _REASON_MS},
                evaluators=[WithinMs(threshold_ms=_REASON_MS)],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_latency_bounds(
    latency_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
) -> None:
    """Measure operation latencies and report against CLAUDE.md targets.

    Hard assertions use a 2x multiplier so that infra jitter in dev / CI
    environments does not cause spurious failures.  The raw elapsed_ms values
    are visible in the printed report for tracking regressions over time.
    """

    async def task(inputs: dict) -> dict:
        return await latency_task(inputs, context_service, scope_context)

    report = await latency_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        output = case_result.output
        assert output is not None, f"Case {case_result.name}: no output"
        elapsed = output.get("elapsed_ms")
        assert elapsed is not None, f"Case {case_result.name}: elapsed_ms missing"

        threshold = case_result.case.expected_output["threshold_ms"]
        # 2x safety margin for non-production environments.
        hard_limit = threshold * 2
        assert elapsed < hard_limit, (
            f"Case {case_result.name}: {elapsed:.1f}ms exceeds hard limit "
            f"{hard_limit:.0f}ms (target {threshold:.0f}ms)"
        )

"""Unit tests for WritePath.references_upserted count.

Verifies that WritePathResult.references_upserted reflects the number of
distinct (node_id, kind) CITES edge pairs produced during write_visit,
not the hardcoded zero that was there before the fix.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.custodian.models import Citation, Claim, FindingOutput
from context_service.custodian.write_path import WritePath

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result_with_single(rows: list[dict[str, Any]]) -> AsyncMock:
    """Return a mock that behaves like a neo4j AsyncResult with .single()."""
    result = AsyncMock()
    if rows:
        result.single = AsyncMock(return_value=rows[0])
    else:
        result.single = AsyncMock(return_value=None)
    return result


def _make_tx(*, prior_finding: dict[str, Any] | None, merge_row: dict[str, Any]) -> AsyncMock:
    """Build a fake neo4j transaction mock.

    The write path calls tx.run() multiple times in sequence:
      1. fetch_current_finding (FETCH_CURRENT_FINDING_*) -> .single() used
      2. FINDING_MERGE_* -> .single() used for finding_id
      3. CITES_EDGE_CREATE_NODE_BATCH (optional)
      4. PROPOSED_EDGE_MERGE_BATCH (optional)
      5. CLUSTER_LAST_CUSTODIAN_UPDATE (cluster scope)
      6. PASS_CLAIMED_EDGE_MERGE (cluster scope)

    We use a side_effect queue: first call returns the prior-finding result,
    second returns the merge result, subsequent calls return a no-op mock.
    """
    prior_result = _make_result_with_single([prior_finding] if prior_finding else [])
    merge_result = _make_result_with_single([merge_row])
    noop_result = _make_result_with_single([])

    call_count = [0]

    async def run_side_effect(query: str, **kwargs: Any) -> AsyncMock:
        call_count[0] += 1
        if call_count[0] == 1:
            return prior_result
        if call_count[0] == 2:
            return merge_result
        return noop_result

    tx = AsyncMock()
    tx.run = AsyncMock(side_effect=run_side_effect)
    return tx


def _make_memgraph_client(tx: AsyncMock) -> MagicMock:
    """Wrap a transaction mock in a memgraph client context manager."""
    client = MagicMock()

    @asynccontextmanager
    async def _transaction_ctx():  # type: ignore[misc]
        yield tx

    client.transaction = _transaction_ctx
    return client


def _make_citation_validator(surviving_claims: list[Claim]) -> AsyncMock:
    """Return a CitationValidator mock that passes the given claims."""
    from context_service.custodian.validators import ClaimValidationResult

    mock = AsyncMock()

    claim_results = [MagicMock(spec=ClaimValidationResult, accepted=True) for _ in surviving_claims]
    edge_results: list[Any] = []
    mock.validate_finding = AsyncMock(return_value=(claim_results, edge_results))
    return mock


def _make_business_validator(quality: float = 0.75) -> MagicMock:
    from context_service.custodian.business_rules import BusinessRuleResult

    mock = MagicMock()
    mock.evaluate = MagicMock(
        return_value=BusinessRuleResult(accepted=True, computed_quality=quality)
    )
    return mock


def _make_finding(claims: list[Claim]) -> FindingOutput:
    return FindingOutput(
        cluster_id="cluster-1",
        silo_id="silo-1",
        scope="cluster",
        claims=claims,
        inferred_relations=[],
        summary=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_path_counts_references_single_claim_two_citations() -> None:
    """Two distinct citations on one claim -> references_upserted == 2."""
    claims = [
        Claim(
            text="Fact about nodes A and B.",
            citations=[
                Citation(node_id="node-a", kind="primary"),
                Citation(node_id="node-b", kind="supporting"),
            ],
        )
    ]
    finding = _make_finding(claims)

    merge_row = {"id": "finding-uuid-1"}
    tx = _make_tx(prior_finding=None, merge_row=merge_row)
    client = _make_memgraph_client(tx)
    citation_validator = _make_citation_validator(claims)
    business_validator = _make_business_validator()

    write_path = WritePath(
        client,
        citation_validator,
        business_validator=business_validator,
    )

    result = await write_path.write_visit(
        finding=finding,
        pass_id="pass-1",
        cluster_size=3,
        seen_node_ids={"node-a", "node-b"},
        org_id="org-1",
    )

    assert result.skipped is False
    assert result.references_upserted == 2


@pytest.mark.asyncio
async def test_write_path_counts_references_deduplicates_same_pair() -> None:
    """Two claims citing the same (node_id, kind) pair -> counted once."""
    claims = [
        Claim(
            text="First claim about node A.",
            citations=[Citation(node_id="node-a", kind="primary")],
        ),
        Claim(
            text="Second claim also citing node A.",
            citations=[Citation(node_id="node-a", kind="primary")],
        ),
    ]
    finding = _make_finding(claims)

    merge_row = {"id": "finding-uuid-2"}
    tx = _make_tx(prior_finding=None, merge_row=merge_row)
    client = _make_memgraph_client(tx)
    citation_validator = _make_citation_validator(claims)
    business_validator = _make_business_validator()

    write_path = WritePath(
        client,
        citation_validator,
        business_validator=business_validator,
    )

    result = await write_path.write_visit(
        finding=finding,
        pass_id="pass-2",
        cluster_size=3,
        seen_node_ids={"node-a"},
        org_id="org-1",
    )

    assert result.skipped is False
    # Duplicate (node-a, primary) pair collapsed -> only 1 unique CITES edge
    assert result.references_upserted == 1


@pytest.mark.asyncio
async def test_write_path_references_zero_on_failed_pipeline() -> None:
    """When pipeline fails, references_upserted stays 0 (no CITES edges created)."""
    from context_service.custodian.validators import ClaimValidationResult

    claims = [
        Claim(
            text="Claim that will be rejected.",
            citations=[Citation(node_id="node-x", kind="primary")],
        )
    ]
    finding = _make_finding(claims)

    # Validator rejects all claims
    rejected_result = MagicMock(spec=ClaimValidationResult, accepted=False)
    citation_validator = AsyncMock()
    citation_validator.validate_finding = AsyncMock(return_value=([rejected_result], []))

    business_validator = _make_business_validator(quality=0.0)
    # Business validator must also reject since no surviving claims
    from context_service.custodian.business_rules import BusinessRuleResult

    business_validator.evaluate = MagicMock(
        return_value=BusinessRuleResult(accepted=False, computed_quality=0.0)
    )

    client = MagicMock()

    write_path = WritePath(
        client,
        citation_validator,
        business_validator=business_validator,
    )

    result = await write_path.write_visit(
        finding=finding,
        pass_id="pass-3",
        cluster_size=3,
        seen_node_ids=set(),
        org_id="org-1",
    )

    assert result.skipped is True
    assert result.references_upserted == 0

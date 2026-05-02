"""Unit tests for run_validation() pipeline function."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.custodian.pipeline import PipelineResult, run_validation

# ---------------------------------------------------------------------------
# Minimal stubs -- no live Memgraph needed
# ---------------------------------------------------------------------------


def _mock_citation_validator(*, all_pass: bool = True) -> Any:
    """Return a CitationValidator mock whose validate_finding returns all-pass or all-fail."""
    from context_service.custodian.validators import ClaimValidationResult, EdgeValidationResult

    mock = AsyncMock()
    claim_result = MagicMock(spec=ClaimValidationResult)
    claim_result.accepted = all_pass
    edge_result = MagicMock(spec=EdgeValidationResult)
    edge_result.accepted = all_pass
    mock.validate_finding = AsyncMock(return_value=([claim_result], [edge_result]))
    return mock


def _mock_business_validator(*, accepted: bool = True) -> Any:
    from context_service.custodian.business_rules import BusinessRuleResult

    mock = MagicMock()
    result = BusinessRuleResult(accepted=accepted, computed_quality=0.75)
    mock.evaluate = MagicMock(return_value=result)
    return mock


def _make_finding() -> Any:
    """Minimal FindingOutput stub."""
    from context_service.custodian.models import FindingOutput

    finding = MagicMock(spec=FindingOutput)
    finding.silo_id = "test-silo"
    finding.scope = "cluster"
    finding.claims = [MagicMock()]
    finding.inferred_relations = [MagicMock()]
    finding.model_copy = MagicMock(return_value=finding)
    return finding


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_validation_pass() -> None:
    """Both stages pass -> PipelineResult.passed is True."""
    result = await run_validation(
        finding=_make_finding(),
        seen_node_ids={"node-1"},
        citation_validator=_mock_citation_validator(all_pass=True),
        business_validator=_mock_business_validator(accepted=True),
        cluster_size=5,
    )
    assert isinstance(result, PipelineResult)
    assert result.passed is True
    assert result.failed_at is None
    assert result.citation is not None
    assert result.business is not None


@pytest.mark.asyncio
async def test_run_validation_business_rejects_when_all_claims_fail_citation() -> None:
    """All claims rejected by citation -> business sees empty survivors -> rejects with failed_at='business'."""
    biz = _mock_business_validator(accepted=False)
    result = await run_validation(
        finding=_make_finding(),
        seen_node_ids=set(),
        citation_validator=_mock_citation_validator(all_pass=False),
        business_validator=biz,
        cluster_size=5,
    )
    assert result.passed is False
    assert result.failed_at == "business"
    assert result.citation is not None
    assert result.citation.claims_rejected == 1
    biz.evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_run_validation_business_fail() -> None:
    """Citation passes, business fails -> failed_at='business', citation result present."""
    result = await run_validation(
        finding=_make_finding(),
        seen_node_ids={"node-1"},
        citation_validator=_mock_citation_validator(all_pass=True),
        business_validator=_mock_business_validator(accepted=False),
        cluster_size=5,
    )
    assert result.passed is False
    assert result.failed_at == "business"
    assert result.citation is not None
    assert result.business is not None

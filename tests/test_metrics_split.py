"""Verify that rejection metrics route to the correct layer-specific counter.

Each test patches the three new counters and the legacy alias, fires one
rejection via record_claim_rejection or CustodianRejectionMetrics, and
asserts that only the expected counter was incremented AND that the legacy
alias was also incremented (deprecation dual-emit).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from context_service.custodian.metrics import (
    CustodianRejectionMetrics,
    record_claim_rejection,
)
from context_service.custodian.rejection_reasons import (
    BusinessRejection,
    CitationRejection,
    StructuralRejection,
)

_MODULE = "context_service.custodian.metrics"


def _make_counter() -> MagicMock:
    c = MagicMock()
    c.add = MagicMock()
    return c


class TestRecordClaimRejectionRouting:
    def test_structural_rejection_routes_to_structural_counter(self) -> None:
        structural = _make_counter()
        citation = _make_counter()
        business = _make_counter()
        legacy = _make_counter()

        with (
            patch(f"{_MODULE}._structural_rejections", structural),
            patch(f"{_MODULE}._citation_rejections", citation),
            patch(f"{_MODULE}._business_rejections", business),
            patch(f"{_MODULE}._claim_rejections", legacy),
        ):
            record_claim_rejection(StructuralRejection.SCHEMA_VIOLATION)

        structural.add.assert_called_once_with(1, attributes={"reason": "schema_violation"})
        legacy.add.assert_called_once_with(1, attributes={"reason": "schema_violation"})
        citation.add.assert_not_called()
        business.add.assert_not_called()

    def test_citation_rejection_routes_to_citation_counter(self) -> None:
        structural = _make_counter()
        citation = _make_counter()
        business = _make_counter()
        legacy = _make_counter()

        with (
            patch(f"{_MODULE}._structural_rejections", structural),
            patch(f"{_MODULE}._citation_rejections", citation),
            patch(f"{_MODULE}._business_rejections", business),
            patch(f"{_MODULE}._claim_rejections", legacy),
        ):
            record_claim_rejection(CitationRejection.HALLUCINATED_NODE_ID)

        citation.add.assert_called_once_with(1, attributes={"reason": "hallucinated_node_id"})
        legacy.add.assert_called_once_with(1, attributes={"reason": "hallucinated_node_id"})
        structural.add.assert_not_called()
        business.add.assert_not_called()

    def test_business_rejection_routes_to_business_counter(self) -> None:
        structural = _make_counter()
        citation = _make_counter()
        business = _make_counter()
        legacy = _make_counter()

        with (
            patch(f"{_MODULE}._structural_rejections", structural),
            patch(f"{_MODULE}._citation_rejections", citation),
            patch(f"{_MODULE}._business_rejections", business),
            patch(f"{_MODULE}._claim_rejections", legacy),
        ):
            record_claim_rejection(BusinessRejection.QUALITY_BELOW_THRESHOLD)

        business.add.assert_called_once_with(1, attributes={"reason": "quality_below_threshold"})
        legacy.add.assert_called_once_with(1, attributes={"reason": "quality_below_threshold"})
        structural.add.assert_not_called()
        citation.add.assert_not_called()


class TestCustodianRejectionMetricsRouting:
    def test_structural_rejection_routes_to_structural_counter(self) -> None:
        structural = _make_counter()
        citation = _make_counter()
        business = _make_counter()
        legacy = _make_counter()

        with (
            patch(f"{_MODULE}._structural_rejections", structural),
            patch(f"{_MODULE}._citation_rejections", citation),
            patch(f"{_MODULE}._business_rejections", business),
            patch(f"{_MODULE}._claim_rejections", legacy),
        ):
            CustodianRejectionMetrics().increment_claim_rejection(
                StructuralRejection.LOW_CONFIDENCE
            )

        structural.add.assert_called_once_with(1, attributes={"reason": "low_confidence"})
        legacy.add.assert_called_once_with(1, attributes={"reason": "low_confidence"})
        citation.add.assert_not_called()
        business.add.assert_not_called()

    def test_citation_rejection_routes_to_citation_counter(self) -> None:
        structural = _make_counter()
        citation = _make_counter()
        business = _make_counter()
        legacy = _make_counter()

        with (
            patch(f"{_MODULE}._structural_rejections", structural),
            patch(f"{_MODULE}._citation_rejections", citation),
            patch(f"{_MODULE}._business_rejections", business),
            patch(f"{_MODULE}._claim_rejections", legacy),
        ):
            CustodianRejectionMetrics().increment_claim_rejection(
                CitationRejection.CROSS_SILO, count=2
            )

        citation.add.assert_called_once_with(2, attributes={"reason": "cross_silo"})
        legacy.add.assert_called_once_with(2, attributes={"reason": "cross_silo"})
        structural.add.assert_not_called()
        business.add.assert_not_called()

    def test_business_rejection_routes_to_business_counter(self) -> None:
        structural = _make_counter()
        citation = _make_counter()
        business = _make_counter()
        legacy = _make_counter()

        with (
            patch(f"{_MODULE}._structural_rejections", structural),
            patch(f"{_MODULE}._citation_rejections", citation),
            patch(f"{_MODULE}._business_rejections", business),
            patch(f"{_MODULE}._claim_rejections", legacy),
        ):
            CustodianRejectionMetrics().increment_claim_rejection(
                BusinessRejection.ALL_CLAIMS_REJECTED
            )

        business.add.assert_called_once_with(1, attributes={"reason": "all_claims_rejected"})
        legacy.add.assert_called_once_with(1, attributes={"reason": "all_claims_rejected"})
        structural.add.assert_not_called()
        citation.add.assert_not_called()

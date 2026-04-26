"""Rejection reason enums split by validation layer.

Three separate enums map to three distinct Prometheus label prefixes so that
metric pollution across layers is eliminated:

- ``StructuralRejection``  -> custodian_structural_rejections  (Stage 0: Pydantic)
- ``CitationRejection``    -> custodian_citation_rejections    (Stage 2: DB lookup)
- ``BusinessRejection``    -> custodian_business_rejections    (Stage 3: pure rules)

``CitationRejectionReason`` in ``validators.py`` previously held SCHEMA_VIOLATION
and LOW_CONFIDENCE; those belong to the structural layer and live here as
``StructuralRejection`` members.
"""

from __future__ import annotations

from enum import StrEnum


class StructuralRejection(StrEnum):
    """Stage 0 rejection reasons -- Pydantic / schema shape failures."""

    SCHEMA_VIOLATION = "schema_violation"
    INVALID_JSON = "invalid_json"
    MISSING_FIELD = "missing_field"
    LOW_CONFIDENCE = "low_confidence"


class CitationRejection(StrEnum):
    """Stage 2 rejection reasons -- citation existence and silo membership."""

    HALLUCINATED_NODE_ID = "hallucinated_node_id"
    INVALID_CITATION = "invalid_citation"
    CROSS_TENANT = "cross_tenant"
    CROSS_SILO = "cross_silo"
    NOT_CITED = "not_cited"


class BusinessRejection(StrEnum):
    """Stage 3 rejection reasons -- business rule gates."""

    LOW_CONFIDENCE = "low_confidence"
    QUALITY_BELOW_THRESHOLD = "quality_below_threshold"
    ALL_CLAIMS_REJECTED = "all_claims_rejected"


__all__ = [
    "BusinessRejection",
    "CitationRejection",
    "StructuralRejection",
]

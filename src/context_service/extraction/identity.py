"""Deterministic ID generation for Claim and CONTRADICTS edge nodes (spec O-12)."""

from __future__ import annotations

import hashlib


def claim_id(
    subject_canonical: str,
    predicate: str,
    object_canonical: str,
    valid_from: str,
    valid_to: str | None,
    source_doc_id: str,
) -> str:
    """Return a deterministic SHA-256 hex ID for a Claim node.

    SHA256 of colon-delimited fields ensures identical triples from different
    extraction runs hash to the same ID, making MERGE idempotent.
    """
    raw = ":".join(
        [
            subject_canonical,
            predicate,
            object_canonical,
            valid_from,
            valid_to or "",
            source_doc_id,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def contradicts_edge_id(fingerprint_a: str, fingerprint_b: str) -> str:
    """Return a deterministic SHA-256 hex ID for a CONTRADICTS edge.

    Sorted pair ensures (A, B) and (B, A) produce the same ID, preventing
    duplicate edges from bidirectional detection runs.
    """
    raw = ":".join(sorted([fingerprint_a, fingerprint_b]))
    return hashlib.sha256(raw.encode()).hexdigest()

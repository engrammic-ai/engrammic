"""Sage: Reactive transaction layer for CITE v2.

This module implements the sage architecture replacing cadence-based Dagster jobs
with write-time invariants and event-driven reactions.

See context/specs/brain-transactions-overview.md for the full specification.
"""

from context_service.sage.confidence import (
    CredibilityBreakdown,
    compute_credibility,
)
from context_service.sage.transactions import (
    ConflictStatus,
    LinkResult,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeResult,
    check_corroboration,
    detect_spo_conflict,
    tx0_store_memory,
    tx2_store_claim,
    tx3_supersede,
    tx17_link,
)

__all__ = [
    # Results
    "StoreMemoryResult",
    "StoreClaimResult",
    "SupersedeResult",
    "LinkResult",
    "CredibilityBreakdown",
    # Enums
    "ConflictStatus",
    # Transactions (internal naming preserved for spec traceability)
    "tx0_store_memory",
    "tx2_store_claim",
    "tx3_supersede",
    "tx17_link",
    # Helpers (public API for ContextService integration)
    "compute_credibility",
    "check_corroboration",
    "detect_spo_conflict",
]

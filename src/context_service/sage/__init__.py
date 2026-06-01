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
    ClusterState,
    CommitResult,
    ConflictStatus,
    CrystallizeResult,
    LinkResult,
    ReviseBeliefResult,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeResult,
    SynthesisState,
    SynthesizeResult,
    check_corroboration,
    detect_spo_conflict,
    tx0_store_memory,
    tx2_store_claim,
    tx3_supersede,
    tx4_synthesize,
    tx5_revise_belief,
    tx8_commit,
    tx14_crystallize,
    tx17_link,
)

__all__ = [
    # Results
    "StoreMemoryResult",
    "StoreClaimResult",
    "SupersedeResult",
    "LinkResult",
    "CommitResult",
    "CrystallizeResult",
    "SynthesizeResult",
    "ReviseBeliefResult",
    "CredibilityBreakdown",
    # Enums
    "ClusterState",
    "ConflictStatus",
    "SynthesisState",
    # Transactions (internal naming preserved for spec traceability)
    "tx0_store_memory",
    "tx2_store_claim",
    "tx3_supersede",
    "tx4_synthesize",
    "tx5_revise_belief",
    "tx8_commit",
    "tx14_crystallize",
    "tx17_link",
    # Helpers (public API for ContextService integration)
    "compute_credibility",
    "check_corroboration",
    "detect_spo_conflict",
]

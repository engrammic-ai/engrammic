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
    CANCEL_WINDOW_DURATION_SECONDS,
    MAX_CASCADE_DEPTH,
    CancelForgetResult,
    ClusterState,
    CommitResult,
    ConflictStatus,
    CrystallizeResult,
    DemoteResult,
    ForgetResult,
    HardDeleteResult,
    LinkResult,
    PromoteResult,
    ReviseBeliefResult,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeResult,
    SynthesisState,
    SynthesizeResult,
    cascade_staleness,
    check_corroboration,
    detect_spo_conflict,
    tx0_store_memory,
    tx2_store_claim,
    tx3_supersede,
    tx4_synthesize,
    tx5_revise_belief,
    tx8_commit,
    tx10_hard_delete,
    tx14_crystallize,
    tx15_forget,
    tx16_cancel_forget,
    tx17_link,
    tx18_promote,
    tx19_demote,
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
    "ForgetResult",
    "CancelForgetResult",
    "HardDeleteResult",
    "PromoteResult",
    "DemoteResult",
    "CredibilityBreakdown",
    # Enums
    "ClusterState",
    "ConflictStatus",
    "SynthesisState",
    # Constants
    "CANCEL_WINDOW_DURATION_SECONDS",
    "MAX_CASCADE_DEPTH",
    # Transactions (internal naming preserved for spec traceability)
    "tx0_store_memory",
    "tx2_store_claim",
    "tx3_supersede",
    "tx4_synthesize",
    "tx5_revise_belief",
    "tx8_commit",
    "tx10_hard_delete",
    "tx14_crystallize",
    "tx15_forget",
    "tx16_cancel_forget",
    "tx17_link",
    "tx18_promote",
    "tx19_demote",
    # Helpers (public API for ContextService integration)
    "compute_credibility",
    "check_corroboration",
    "detect_spo_conflict",
    "cascade_staleness",
]

"""Sage: Reactive transaction layer for CITE v2.

This module implements the sage architecture replacing cadence-based Dagster jobs
with write-time invariants and event-driven reactions.

See context/specs/brain-transactions-overview.md for the full specification.
"""

from context_service.sage.confidence import (
    CredibilityBreakdown,
    compute_credibility,
)
from context_service.sage.recall import (
    Layer,
    RecallOptions,
    RecallResult,
    RecallResultItem,
    RelatedNode,
    compute_recall_score,
    recall,
    traverse_graph,
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
    cancel_forget,
    cascade_staleness,
    check_corroboration,
    commit,
    crystallize,
    demote,
    detect_spo_conflict,
    forget,
    hard_delete,
    link,
    promote,
    revise_belief,
    store_claim,
    store_memory,
    supersede,
    synthesize,
    would_create_cycle,
)

__all__ = [
    # Results
    "RecallResult",
    "RecallResultItem",
    "RelatedNode",
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
    "Layer",
    "SynthesisState",
    # Options
    "RecallOptions",
    # Constants
    "CANCEL_WINDOW_DURATION_SECONDS",
    "MAX_CASCADE_DEPTH",
    # Transactions
    "store_memory",
    "store_claim",
    "supersede",
    "synthesize",
    "revise_belief",
    "commit",
    "hard_delete",
    "crystallize",
    "forget",
    "cancel_forget",
    "link",
    # Layer movement (TX18, TX19)
    "promote",
    "demote",
    # Helpers (public API for ContextService integration)
    "compute_credibility",
    "check_corroboration",
    "detect_spo_conflict",
    "cascade_staleness",
    "would_create_cycle",
    # Recall (Phase 6)
    "recall",
    "compute_recall_score",
    "traverse_graph",
]

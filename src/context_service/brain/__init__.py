"""Brain: Reactive transaction layer for CITE v2.

This module implements the brain architecture that replaces SAGE's
cadence-based Dagster jobs with write-time invariants and event-driven reactions.

See context/specs/brain-transactions-overview.md for the full specification.
"""

from context_service.brain.transactions import (
    LinkResult,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeResult,
    tx0_store_memory,
    tx2_store_claim,
    tx3_supersede,
    tx17_link,
)

__all__ = [
    "StoreMemoryResult",
    "StoreClaimResult",
    "SupersedeResult",
    "LinkResult",
    "tx0_store_memory",
    "tx2_store_claim",
    "tx3_supersede",
    "tx17_link",
]

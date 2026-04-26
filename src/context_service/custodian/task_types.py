"""Custodian task type taxonomy (O-7)."""

from __future__ import annotations

from enum import IntEnum


class CustodianTaskType(IntEnum):
    CONTRADICTION = 1
    STALENESS = 2
    COVERAGE_GAP = 3
    SUPERSESSION = 4
    QUALITY_REVIEW = 5
    SILO_SYNTHESIS = 6
    CLAIM_VALIDATION = 7
    CONSENSUS_ON_CHAINS = 8


CONSENSUS_ON_CHAINS = CustodianTaskType.CONSENSUS_ON_CHAINS

__all__ = ["CONSENSUS_ON_CHAINS", "CustodianTaskType"]
